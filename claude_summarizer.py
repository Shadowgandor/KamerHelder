import json
import re
from typing import List, Dict, Optional, Tuple
from datetime import datetime
import anthropic
import os
from dataclasses import dataclass

@dataclass
class ChunkInfo:
    """Information about a text chunk"""
    chunk_number: int
    start_pos: int
    end_pos: int
    text: str
    topics_mentioned: List[str] = None

class ParliamentarySummarizer:
    """
    Summarizer for parliamentary debates using Claude API
    """
    
    def __init__(self, api_key: str = None):
        """
        Initialize the summarizer
        
        Args:
            api_key: Anthropic API key (or set ANTHROPIC_API_KEY env var)
        """
        api_key = api_key or os.getenv('ANTHROPIC_API_KEY')
        if not api_key:
            raise ValueError("Anthropic API key required. Set ANTHROPIC_API_KEY environment variable or pass api_key parameter")
        
        self.client = anthropic.Anthropic(api_key=api_key)
        self.max_chunk_size = 50000  # Characters per chunk (roughly 12-15k tokens)
    
    def identify_speakers_and_parties(self, text: str, verslag_data: Dict = None) -> Dict[str, str]:
        """
        Extract speaker names and their party affiliations from the text
        
        Args:
            text: Parliamentary debate text
            verslag_data: Full verslag data (to get pre-parsed speakers)
            
        Returns:
            Dictionary mapping speaker names to parties
        """
        # First try to use the parsed speaker data
        if verslag_data and 'parsed_content' in verslag_data and 'sprekers' in verslag_data['parsed_content']:
            sprekers = verslag_data['parsed_content']['sprekers']
            speakers_map = {}
            
            for spreker in sprekers:
                # Check if we have clean structured data
                naam = spreker.get('naam')
                fractie = spreker.get('fractie') 
                
                # Method 1: Use clean structured data if available
                if naam and fractie and naam != 'null' and fractie != 'null':
                    speakers_map[naam] = fractie
                    continue
                
                # Method 2: Parse the tekst field
                tekst = spreker.get('tekst', '')
                if tekst and tekst != 'null':
                    party = None
                    name = None
                    
                    # Known Dutch parties
                    known_parties = ['PVV', 'VVD', 'GroenLinks-PvdA', 'D66', 'CDA', 'SP', 'NSC', 
                                'BBB', 'DENK', 'Volt', 'JA21', 'SGP', 'ChristenUnie', 'FVD', 'PvdD']
                    
                    # Check if this is a minister/government official
                    if 'minister' in tekst.lower() or 'staatssecretaris' in tekst.lower():
                        words = tekst.split()
                        
                        # Find the name
                        if 'heer' in tekst.lower():
                            heer_index = next((j for j, part in enumerate(words) if 'heer' in part.lower()), -1)
                            if heer_index >= 0 and heer_index + 1 < len(words):
                                name = words[heer_index + 1]
                        elif 'mevrouw' in tekst.lower():
                            mevrouw_index = next((j for j, part in enumerate(words) if 'mevrouw' in part.lower()), -1)
                            if mevrouw_index >= 0 and mevrouw_index + 1 < len(words):
                                name = words[mevrouw_index + 1]
                        
                        # Extract ministerial role
                        if 'minister van' in tekst.lower():
                            van_index = tekst.lower().find('minister van')
                            role_part = tekst[van_index:].strip()
                            if ',' in role_part:
                                role_part = role_part.split(',')[0]
                            party = role_part.replace('minister van', 'Minister van')
                        elif 'staatssecretaris' in tekst.lower():
                            secretary_index = tekst.lower().find('staatssecretaris')
                            role_part = tekst[secretary_index:].strip()
                            if ',' in role_part:
                                role_part = role_part.split(',')[0]
                            party = role_part.replace('staatssecretaris', 'Staatssecretaris')
                        else:
                            party = "Minister"
                    
                    elif 'voorzitter' in tekst.lower():
                        name = "Voorzitter"
                        party = "Chair"
                    
                    else:
                        # This should be an MP - look for party
                        words = tekst.split()
                        for word in words:
                            if word in known_parties:
                                party = word
                                break
                        
                        # Extract name
                        if 'heer' in tekst.lower():
                            heer_index = next((j for j, part in enumerate(words) if 'heer' in part.lower()), -1)
                            if heer_index >= 0 and heer_index + 1 < len(words):
                                name = words[heer_index + 1]
                        elif 'mevrouw' in tekst.lower():
                            mevrouw_index = next((j for j, part in enumerate(words) if 'mevrouw' in part.lower()), -1)
                            if mevrouw_index >= 0 and mevrouw_index + 1 < len(words):
                                name = words[mevrouw_index + 1]
                    
                    # Add if we found both name and valid party/role
                    if name and party:
                        speakers_map[name] = party
            
            print(f"Extracted {len(speakers_map)} speakers from parsed data")
            if speakers_map:
                return speakers_map
        
        # If no parsed data, continue without speakers
        print("No parsed speaker data found, continuing without speaker mapping...")
        return {}
    
    def chunk_text_smartly(self, text: str) -> List[ChunkInfo]:
        """
        Split text into chunks, trying to preserve logical sections
        
        Args:
            text: Full parliamentary debate text
            
        Returns:
            List of ChunkInfo objects
        """
        chunks = []
        
        # Try to split on natural boundaries (speakers, agenda items, etc.)
        # Look for common patterns in Dutch parliamentary texts
        split_patterns = [
            r'\n\n(?=De heer|Mevrouw|Minister)',  # New speaker
            r'\n\n(?=Agendapunt|AGENDAPUNT)',     # New agenda item
            r'\n\n(?=Voorzitter:)',               # Chairman
            r'\n\n(?=[A-Z][a-z]+ [A-Z][a-z]+:)', # General speaker pattern
        ]
        
        current_pos = 0
        chunk_num = 1
        
        while current_pos < len(text):
            # Determine chunk end position
            target_end = min(current_pos + self.max_chunk_size, len(text))
            
            # If this would be the last chunk or we're near the end, take everything
            if target_end >= len(text) - 1000:
                chunk_end = len(text)
            else:
                # Try to find a good break point
                chunk_end = target_end
                best_break = None
                
                # Look for natural breaks within the last 2000 chars of the chunk
                search_start = max(target_end - 2000, current_pos)
                search_text = text[search_start:target_end + 1000]  # Look a bit ahead too
                
                for pattern in split_patterns:
                    matches = list(re.finditer(pattern, search_text))
                    if matches:
                        # Take the match closest to our target
                        for match in matches:
                            abs_pos = search_start + match.start()
                            if current_pos + 5000 <= abs_pos <= target_end + 500:  # Reasonable range
                                if best_break is None or abs(abs_pos - target_end) < abs(best_break - target_end):
                                    best_break = abs_pos
                
                if best_break:
                    chunk_end = best_break
            
            # Extract chunk
            chunk_text = text[current_pos:chunk_end].strip()
            
            if chunk_text:  # Only add non-empty chunks
                chunk = ChunkInfo(
                    chunk_number=chunk_num,
                    start_pos=current_pos,
                    end_pos=chunk_end,
                    text=chunk_text
                )
                chunks.append(chunk)
                chunk_num += 1
            
            current_pos = chunk_end
        
        print(f"Split text into {len(chunks)} chunks")
        for i, chunk in enumerate(chunks):
            print(f"  Chunk {i+1}: {len(chunk.text)} characters")
        
        return chunks
    
    def summarize_chunk(self, chunk: ChunkInfo, speakers_map: Dict[str, str], 
                   meeting_info: Dict, max_retries: int = 1) -> Dict:
        """
        Summarize a single chunk of parliamentary debate
        """
        # Get speakers that are actually mentioned in this chunk
        relevant_speakers = self.get_relevant_speakers(chunk.text[:3000], speakers_map)
        speaker_context = relevant_speakers if len(relevant_speakers) <= 30 else dict(list(speakers_map.items())[:30])
        
        prompt = f"""
        Analyze this Dutch parliamentary debate chunk and return valid JSON only.

        Meeting: {meeting_info.get('vergadering_titel', 'Unknown')}
        Date: {meeting_info.get('vergadering_datum', 'Unknown')}

        Speakers mentioned in this section: {speaker_context}

        Return this exact JSON structure with your analysis:
        {{
            "chunk_summary": "Brief overview of what was discussed",
            "topics": [
                {{
                    "topic": "Topic name",
                    "description": "What was discussed about this topic", 
                    "party_positions": [
                        {{
                            "party": "Party or speaker name",
                            "position": "Their stance on this topic",
                            "key_quotes": []
                        }}
                    ]
                }}
            ],
            "key_decisions": [],
            "notable_exchanges": []
        }}

        Text to analyze:
        {chunk.text[:3000]}...
        """
        
        for attempt in range(max_retries + 1):
            try:
                response = self.client.messages.create(
                    model="claude-3-haiku-20240307",
                    max_tokens=1500,
                    messages=[{"role": "user", "content": prompt}]
                )
                
                if not response.content or not response.content[0].text:
                    raise ValueError("Empty response from Claude")
                
                response_text = response.content[0].text.strip()
                
                # Clean up common formatting issues
                response_text = response_text.replace('```json', '').replace('```', '').strip()
                
                # Extract JSON part
                start_brace = response_text.find('{')
                end_brace = response_text.rfind('}')
                
                if start_brace != -1 and end_brace != -1:
                    json_part = response_text[start_brace:end_brace + 1]
                    
                    # Try parsing first
                    try:
                        chunk_analysis = json.loads(json_part)
                    except json.JSONDecodeError:
                        # Try fixing the JSON
                        print(f"  Attempting to repair JSON for chunk {chunk.chunk_number}...")
                        fixed_json = self.fix_broken_json(json_part)
                        chunk_analysis = json.loads(fixed_json)
                    
                    chunk_analysis['chunk_number'] = chunk.chunk_number
                    return chunk_analysis
                else:
                    raise ValueError("No JSON found in response")
                    
            except json.JSONDecodeError as e:
                if attempt < max_retries:
                    print(f"  JSON error, retrying chunk {chunk.chunk_number}...")
                    continue
                else:
                    print(f"  JSON parsing failed on chunk {chunk.chunk_number} - creating minimal response")
                    # Create a minimal but valid response so we don't lose the chunk completely
                    return {
                        'chunk_number': chunk.chunk_number,
                        'chunk_summary': f'Chunk {chunk.chunk_number} processing failed but contained parliamentary discussion',
                        'topics': [{
                            'topic': 'Parliamentary Discussion',
                            'description': 'Content could not be fully processed due to formatting issues',
                            'party_positions': []
                        }],
                        'key_decisions': [],
                        'notable_exchanges': []
                    }
                    
            except Exception as e:
                if attempt < max_retries:
                    print(f"  Error, retrying chunk {chunk.chunk_number}...")
                    continue
                else:
                    print(f"  Failed chunk {chunk.chunk_number}: {e}")
        
        # Return minimal valid response on failure
        return {
            'chunk_number': chunk.chunk_number,
            'chunk_summary': f'Chunk {chunk.chunk_number} could not be processed',
            'topics': [],
            'key_decisions': [],
            'notable_exchanges': []
        }

    def combine_chunk_summaries(self, chunk_summaries: List[Dict], 
                           meeting_info: Dict) -> Dict:
        """
        Combine multiple chunk summaries into a comprehensive meeting summary
        
        Args:
            chunk_summaries: List of chunk analysis results
            meeting_info: Meeting metadata
            
        Returns:
            Complete meeting summary
        """
        # Collect all topics across chunks
        all_topics = {}
        all_decisions = []
        all_exchanges = []
        
        for chunk_summary in chunk_summaries:
            if 'topics' in chunk_summary:
                for topic_info in chunk_summary['topics']:
                    topic_name = topic_info['topic']
                    
                    if topic_name not in all_topics:
                        all_topics[topic_name] = {
                            'topic': topic_name,
                            'description': topic_info['description'],
                            'party_positions': [],
                            'mentioned_in_chunks': []
                        }
                    
                    # Add party positions
                    all_topics[topic_name]['party_positions'].extend(
                        topic_info.get('party_positions', [])
                    )
                    all_topics[topic_name]['mentioned_in_chunks'].append(
                        chunk_summary['chunk_number']
                    )
            
            # Collect decisions and exchanges
            all_decisions.extend(chunk_summary.get('key_decisions', []))
            all_exchanges.extend(chunk_summary.get('notable_exchanges', []))
        
        # Create final summary using Claude
        topics_json = json.dumps(list(all_topics.values()), ensure_ascii=False, indent=2)
        
        synthesis_prompt = f"""
    Create a comprehensive summary of this Dutch parliamentary meeting.

    Meeting: {meeting_info.get('vergadering_titel', 'Unknown')}
    Date: {meeting_info.get('vergadering_datum', 'Unknown')}

    Topics found: {len(all_topics)}
    Decisions: {len(all_decisions)}

    Return this exact JSON structure:
    {{
        "executive_summary": "2-3 sentence overview of the entire meeting",
        "main_topics": [
            {{
                "topic": "Topic name",
                "summary": "What was discussed about this topic",
                "party_positions": {{
                    "Party/Speaker": "Their overall position on this topic"
                }},
                "outcome": "Any decisions or next steps"
            }}
        ],
        "key_decisions": ["List of decisions/motions/votes"],
        "political_dynamics": "Brief analysis of agreements, disagreements, coalition dynamics",
        "next_steps": ["What happens next based on this meeting"]
    }}

    Topics and positions data:
    {topics_json[:2000]}...

    Key decisions: {all_decisions[:10]}
    Notable exchanges: {all_exchanges[:5]}
    """
        
        try:
            response = self.client.messages.create(
                model="claude-3-haiku-20240307",
                max_tokens=3000,
                messages=[{"role": "user", "content": synthesis_prompt}]
            )
            
            response_text = response.content[0].text.strip()
            response_text = response_text.replace('```json', '').replace('```', '').strip()
            
            # Extract JSON part
            start_brace = response_text.find('{')
            end_brace = response_text.rfind('}')
            
            if start_brace != -1 and end_brace != -1:
                json_part = response_text[start_brace:end_brace + 1]
                final_summary = json.loads(json_part)
            else:
                raise ValueError("No JSON found in final summary")
            
            # Add metadata
            final_summary['meeting_info'] = meeting_info
            final_summary['processing_info'] = {
                'chunks_processed': len(chunk_summaries),
                'total_topics_found': len(all_topics),
                'processing_date': datetime.now().isoformat()
            }
            
            return final_summary
            
        except Exception as e:
            print(f"Error creating final summary: {e}")
            return {
                'error': str(e),
                'meeting_info': meeting_info,
                'raw_chunk_summaries': chunk_summaries
            }
    
    def summarize_parliamentary_meeting(self, verslag_data: Dict) -> Dict:
        """
        Complete pipeline to summarize a parliamentary meeting
        
        Args:
            verslag_data: Dictionary with meeting data and text content
            
        Returns:
            Complete summary of the meeting
        """
        print(f"\n=== Summarizing Meeting ===")
        print(f"Meeting: {verslag_data.get('vergadering_titel', 'Unknown')}")
        print(f"Date: {verslag_data.get('vergadering_datum', 'Unknown')}")
        
        # Get the readable text
        text = verslag_data.get('readable_text', '')
        if not text:
            return {'error': 'No readable text found in verslag data'}
        
        print(f"Text length: {len(text)} characters")
        
        # Extract meeting info
        meeting_info = {
            'vergadering_titel': verslag_data.get('vergadering_titel'),
            'vergadering_datum': verslag_data.get('vergadering_datum'),
            'verslag_id': verslag_data.get('id'),
            'status': verslag_data.get('status')
        }
        
        # Step 1: Identify speakers and parties
        print("Step 1: Identifying speakers and parties...")
        try:
            speakers_map = self.identify_speakers_and_parties(text, verslag_data)
            print(f"Found {len(speakers_map)} speakers/parties")
        except Exception as e:
            print(f"Speaker identification failed: {e}")
            print("Continuing without speaker mapping...")
            speakers_map = {}
        
        # Step 2: Chunk the text
        print("Step 2: Chunking text...")
        chunks = self.chunk_text_smartly(text)
        
        # Step 3: Summarize each chunk
        print("Step 3: Summarizing chunks...")
        chunk_summaries = []
        for i, chunk in enumerate(chunks):
            print(f"  Processing chunk {i+1}/{len(chunks)}...")
            chunk_summary = self.summarize_chunk(chunk, speakers_map, meeting_info)
            chunk_summaries.append(chunk_summary)
        
        # Step 4: Combine into final summary
        print("Step 4: Creating final summary...")
        final_summary = self.combine_chunk_summaries(chunk_summaries, meeting_info)
        
        print("✓ Summary complete!")
        return final_summary
    
    def fix_broken_json(self, json_text: str) -> str:
        """
        Attempt to fix common JSON formatting issues
        """
        # Remove common problematic patterns
        json_text = json_text.strip()
        json_text = re.sub(r',(\s*[}\]])', r'\1', json_text)  # Remove trailing commas
        json_text = re.sub(r'(["\w])\s*\n\s*(["\w])', r'\1 \2', json_text)  # Fix broken strings across lines
        json_text = re.sub(r'"\s*\n\s*"', r'""', json_text)  # Fix split quotes
        
        # Try to fix incomplete arrays/objects
        if json_text.count('{') > json_text.count('}'):
            json_text += '}' * (json_text.count('{') - json_text.count('}'))
        
        if json_text.count('[') > json_text.count(']'):
            json_text += ']' * (json_text.count('[') - json_text.count(']'))
        
        # Fix missing quotes around keys (common issue)
        json_text = re.sub(r'(\w+):', r'"\1":', json_text)
        
        return json_text
    
    def get_relevant_speakers(self, chunk_text: str, speakers_map: Dict[str, str]) -> Dict[str, str]:
        """
        Find speakers that are actually mentioned in this chunk
        """
        relevant_speakers = {}
        chunk_lower = chunk_text.lower()
        
        for name, party in speakers_map.items():
            # Check if this speaker's name appears in the chunk
            if name.lower() in chunk_lower:
                relevant_speakers[name] = party
        
        return relevant_speakers

def main():
    """
    Main function to summarize all available verslagen
    """
    print("=== Parliamentary Summarizer - Batch Mode ===")
    
    # Check for API key
    api_key = os.getenv('ANTHROPIC_API_KEY')
    if not api_key:
        print("❌ ANTHROPIC_API_KEY environment variable not set!")
        print("Please set your API key:")
        print("export ANTHROPIC_API_KEY='your-api-key-here'")
        return
    
    try:
        # Load parsed verslagen
        with open('verslagen_parsed.json', 'r', encoding='utf-8') as f:
            verslagen = json.load(f)
        
        # Find verslagen ready for summarization
        ready_verslagen = [v for v in verslagen if v.get('summary_ready', False)]
        
        if not ready_verslagen:
            print("No verslagen ready for summarization found!")
            print("Make sure you've run the document processor and XML parser first.")
            return
        
        print(f"Found {len(ready_verslagen)} verslagen ready for summarization")
        
        # Check which ones already have summaries
        existing_summaries = []
        new_verslagen = []
        
        for verslag in ready_verslagen:
            summary_filename = f"summary_{verslag.get('id', 'unknown')}.json"
            if os.path.exists(summary_filename):
                existing_summaries.append(verslag)
                print(f"✓ Already summarized: {verslag.get('vergadering_titel', 'Unknown')}")
            else:
                new_verslagen.append(verslag)
        
        if existing_summaries:
            print(f"\n{len(existing_summaries)} verslagen already have summaries")
        
        if not new_verslagen:
            print("All verslagen have already been summarized! ✓")
            return
        
        print(f"\n{len(new_verslagen)} verslagen need to be summarized")
        
        # Ask for confirmation
        print("\nVersions to be summarized:")
        for i, verslag in enumerate(new_verslagen, 1):
            print(f"  {i}. {verslag.get('vergadering_titel', 'Unknown')} ({verslag.get('vergadering_datum', 'Unknown date')})")
        
        confirm = input(f"\nProceed with summarizing {len(new_verslagen)} meetings? (y/n): ")
        if confirm.lower() != 'y':
            print("Cancelled.")
            return
        
        # Initialize summarizer
        summarizer = ParliamentarySummarizer(api_key)
        
        # Process each verslag
        successful = 0
        failed = 0
        
        for i, verslag in enumerate(new_verslagen, 1):
            print(f"\n{'='*60}")
            print(f"Processing {i}/{len(new_verslagen)}: {verslag.get('vergadering_titel', 'Unknown')}")
            print(f"{'='*60}")
            
            try:
                # Create summary
                summary = summarizer.summarize_parliamentary_meeting(verslag)
                
                # Check if summary was successful
                if 'error' in summary and 'executive_summary' not in summary:
                    print(f"❌ Summary failed: {summary['error']}")
                    failed += 1
                    continue
                
                # Save result
                output_filename = f"summary_{verslag.get('id', 'unknown')}.json"
                with open(output_filename, 'w', encoding='utf-8') as f:
                    json.dump(summary, f, ensure_ascii=False, indent=2)
                
                print(f"✓ Summary saved to: {output_filename}")
                successful += 1
                
                # Show brief preview
                if 'executive_summary' in summary:
                    print(f"\nPreview: {summary['executive_summary'][:150]}...")
                    if 'main_topics' in summary:
                        print(f"Topics covered: {len(summary['main_topics'])}")
                
            except KeyboardInterrupt:
                print(f"\n\n⚠️ Process interrupted by user")
                print(f"Progress: {successful} successful, {failed} failed, {len(new_verslagen) - i} remaining")
                print("You can restart the script to continue with remaining verslagen.")
                return
                
            except Exception as e:
                print(f"❌ Error processing verslag: {e}")
                failed += 1
                continue
        
        # Final summary
        print(f"\n{'='*60}")
        print("BATCH PROCESSING COMPLETE")
        print(f"{'='*60}")
        print(f"✓ Successfully processed: {successful}")
        print(f"❌ Failed: {failed}")
        print(f"📁 Total summaries available: {len(existing_summaries) + successful}")
        
        if successful > 0:
            print(f"\n🎉 You now have {len(existing_summaries) + successful} parliamentary meeting summaries!")
            print("Ready to load into your Angular app for testing!")
        
    except FileNotFoundError:
        print("verslagen_parsed.json not found. Please run the XML parser first.")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()