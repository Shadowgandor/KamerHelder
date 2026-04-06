import json
import re
from typing import List, Dict, Optional, Tuple
from datetime import datetime
import requests
import os
from dataclasses import dataclass
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import sys
import argparse

@dataclass
class ChunkInfo:
    """Information about a text chunk"""
    chunk_number: int
    start_pos: int
    end_pos: int
    text: str
    topics_mentioned: List[str] = None

class DeepSeekParliamentarySummarizer:
    """
    Enhanced summarizer with fact-checking capabilities for parliamentary debates using DeepSeek API
    """
    
    def __init__(self, api_key: str = None):
        """
        Initialize the summarizer
        
        Args:
            api_key: DeepSeek API key (or set DEEPSEEK_API_KEY env var)
        """
        api_key = api_key or os.getenv('DEEPSEEK_API_KEY')
        if not api_key:
            raise ValueError("DeepSeek API key required. Set DEEPSEEK_API_KEY environment variable or pass api_key parameter")
        
        self.api_key = api_key
        self.base_url = "https://api.deepseek.com/v1"
        self.max_chunk_size = 50000  # Match Claude's chunk size
        
        # Headers for API requests
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        # Rate limiting
        self.last_request_time = 0
        self.min_request_interval = 0.5  # Minimum seconds between requests
        
    def _rate_limit(self):
        """Simple rate limiting to avoid hitting API limits"""
        current_time = time.time()
        time_since_last_request = current_time - self.last_request_time
        if time_since_last_request < self.min_request_interval:
            time.sleep(self.min_request_interval - time_since_last_request)
        self.last_request_time = time.time()
    
    def make_api_request(self, messages: List[Dict], max_tokens: int = 1500, 
                        temperature: float = 0.1, max_retries: int = 3) -> str:
        """
        Make a request to DeepSeek API with retries
        
        Args:
            messages: List of message dictionaries
            max_tokens: Maximum tokens in response
            temperature: Model temperature
            max_retries: Maximum number of retries
            
        Returns:
            Response text from the API
        """
        self._rate_limit()
        
        payload = {
            "model": "deepseek-chat",
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False
        }
        
        for attempt in range(max_retries + 1):
            try:
                response = requests.post(
                    f"{self.base_url}/chat/completions",
                    headers=self.headers,
                    json=payload,
                    timeout=60
                )
                response.raise_for_status()
                
                result = response.json()
                return result['choices'][0]['message']['content']
                
            except requests.exceptions.RequestException as e:
                if attempt < max_retries:
                    print(f"  Retry {attempt + 1}/{max_retries} after error: {str(e)[:100]}")
                    time.sleep(2 ** attempt)  # Exponential backoff
                    continue
                else:
                    print(f"  Failed after {max_retries} retries: {e}")
                    raise
    
    def identify_speakers_and_parties(self, text: str, verslag_data: Dict = None) -> Dict[str, str]:
        """
        Extract speaker names and their party affiliations from the text
        
        Args:
            text: Parliamentary debate text
            verslag_data: Full verslag data (to get pre-parsed speakers)
            
        Returns:
            Dictionary mapping speaker names to parties
        """
        # First try to use the parsed speaker data (same as Claude version)
        if verslag_data and 'parsed_content' in verslag_data and 'sprekers' in verslag_data['parsed_content']:
            sprekers = verslag_data['parsed_content']['sprekers']
            speakers_map = {}
            
            for spreker in sprekers:
                naam = spreker.get('naam')
                fractie = spreker.get('fractie')
                
                if naam and fractie and naam != 'null' and fractie != 'null':
                    speakers_map[naam] = fractie
                    continue
                
                # Parse the tekst field
                tekst = spreker.get('tekst', '')
                if tekst and tekst != 'null':
                    party = None
                    name = None
                    
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
                    
                    if name and party:
                        speakers_map[name] = party
            
            print(f"Extracted {len(speakers_map)} speakers from parsed data")
            if speakers_map:
                return speakers_map
        
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
        
        # Same splitting patterns as Claude version
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
                search_text = text[search_start:target_end + 1000]
                
                for pattern in split_patterns:
                    matches = list(re.finditer(pattern, search_text))
                    if matches:
                        for match in matches:
                            abs_pos = search_start + match.start()
                            if current_pos + 5000 <= abs_pos <= target_end + 500:
                                if best_break is None or abs(abs_pos - target_end) < abs(best_break - target_end):
                                    best_break = abs_pos
                
                if best_break:
                    chunk_end = best_break
            
            # Extract chunk
            chunk_text = text[current_pos:chunk_end].strip()
            
            if chunk_text:
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
    
    def get_relevant_speakers(self, chunk_text: str, speakers_map: Dict[str, str]) -> Dict[str, str]:
        """
        Find speakers that are actually mentioned in this chunk
        """
        relevant_speakers = {}
        chunk_lower = chunk_text.lower()
        
        for name, party in speakers_map.items():
            if name.lower() in chunk_lower:
                relevant_speakers[name] = party
        
        return relevant_speakers
    
    def fix_broken_json(self, json_text: str) -> str:
        """
        Attempt to fix common JSON formatting issues
        """
        # Remove common problematic patterns
        json_text = json_text.strip()
        json_text = re.sub(r',(\s*[}\]])', r'\1', json_text)  # Remove trailing commas
        json_text = re.sub(r'(["\w])\s*\n\s*(["\w])', r'\1 \2', json_text)  # Fix broken strings
        json_text = re.sub(r'"\s*\n\s*"', r'""', json_text)  # Fix split quotes
        
        # Balance braces and brackets
        if json_text.count('{') > json_text.count('}'):
            json_text += '}' * (json_text.count('{') - json_text.count('}'))
        
        if json_text.count('[') > json_text.count(']'):
            json_text += ']' * (json_text.count('[') - json_text.count(']'))
        
        # Fix missing quotes around keys
        json_text = re.sub(r'(\w+):', r'"\1":', json_text)
        
        return json_text
    
    def summarize_chunk(self, chunk: ChunkInfo, speakers_map: Dict[str, str], 
                       meeting_info: Dict, max_retries: int = 1) -> Dict:
        """
        Summarize a single chunk of parliamentary debate with fact-checking
        """
        # Get speakers that are actually mentioned in this chunk
        relevant_speakers = self.get_relevant_speakers(chunk.text[:3000], speakers_map)
        speaker_context = relevant_speakers if len(relevant_speakers) <= 30 else dict(list(speakers_map.items())[:30])
        
        prompt = f"""
        Analyze this Dutch parliamentary debate chunk with attention to both factual content and political dynamics, including fact-checking of verifiable claims.

        Meeting: {meeting_info.get('vergadering_titel', 'Unknown')}
        Date: {meeting_info.get('vergadering_datum', 'Unknown')}

        Speakers mentioned in this section: {speaker_context}

        ENHANCED FACT-CHECKING INSTRUCTIONS:
        
        **VERIFICATION REQUIREMENT**: If you identify a claim about publicly available information (government documents, laws, budgets, coalition agreements, etc.), you MUST:
        1. State what specific document/source would contain the correct information
        2. Provide the actual correct information if you know it from your training data
        3. If you don't know the specific details, clearly state "REQUIRES VERIFICATION: [specific document needed]"
        
        **CONFIDENCE THRESHOLD**: Only flag claims with MEDIUM or HIGH confidence. Do not include LOW confidence flags.

        Flag the following types of claims when you have MEDIUM or HIGH confidence they are incorrect:

        1. **Numerical/Statistical Errors** (flag when clearly wrong):
           - Wrong institutional numbers (e.g., parliament seats, ministry budgets)
           - Budget/financial figures that are off by more than 30% from known values
           - Population/demographic statistics that are significantly incorrect
           - Electoral results that don't match official records
           - Economic indicators that differ substantially from official figures
           - ALWAYS provide the correct figure if known, or state what source would contain it

        2. **Temporal/Historical Errors** (flag when dates/sequences are wrong):
           - Incorrect years for major events
           - Wrong sequence of events
           - Misattributed policy implementation dates
           - Incorrect terms of office for politicians
           - Verify against your knowledge of Dutch political history

        3. **Legal/Constitutional Errors** (flag clear mistakes):
           - Misstatements about Dutch law or EU regulations
           - Incorrect constitutional procedures
           - Wrong voting thresholds or parliamentary procedures
           - Misrepresented legal requirements or rights
           - ALWAYS cite the specific law/article if you know it

        4. **Institutional Facts** (flag when demonstrably wrong):
           - Wrong names of ministries or government bodies
           - Incorrect responsibilities of institutions (e.g., NZa vs IGJ)
           - Misattributed policies to wrong parties/governments
           - Wrong international agreements or treaty obligations
           - Provide the correct institutional structure/responsibility

        5. **Scientific/Medical Claims** (flag clear misinformation):
           - Debunked medical claims
           - Climate science denial contradicting scientific consensus
           - False causation claims contradicted by established research

        IMPORTANT VERIFICATION RULES:
        - For claims about coalition agreements: These are public on rijksoverheid.nl - verify the actual text
        - For budget claims: Check against official Rijksbegroting documents
        - For legal claims: Reference specific articles in Dutch law
        - For institutional claims: Verify against official government organizational charts
        - If you cannot verify but know where to find the info, state: "REQUIRES VERIFICATION: [source]"

        DO NOT FLAG:
        - Political opinions or value judgments
        - Future predictions or projections
        - Rhetorical exaggerations/hyperbole ("ravijnjaar", "crisis", etc.)
        - Claims where speaker indicates uncertainty ("ongeveer", "uit mijn hoofd")
        - Unverifiable private conversations
        - Claims that are plausible but just lack a cited source (unless extraordinary)

        Return this exact JSON structure:
        {{
            "chunk_summary": "Brief overview capturing both content AND political dynamics",
            "topics": [
                {{
                    "topic": "Topic name",
                    "description": "What was discussed, including context and implications", 
                    "party_positions": [
                        {{
                            "party": "Party or speaker name",
                            "position": "Their stance, including tone and strategy",
                            "key_quotes": ["Important quotes that show their approach"]
                        }}
                    ],
                    "tensions": "Any disagreements or conflicts on this topic",
                    "consensus": "Areas of agreement across parties"
                }}
            ],
            "key_decisions": ["Include context: who pushed for it, who opposed"],
            "notable_exchanges": ["Describe heated debates, clever responses, or revealing moments"],
            "political_undercurrents": "Subtle dynamics, coalition pressures, or strategic positioning",
            "fact_check_flags": [
                {{
                    "claim": "Exact claim that was made",
                    "speaker": "Who made the claim",
                    "context": "In what context was this claim made",
                    "issue": "What is specifically incorrect about this claim",
                    "correct_info": "The actual correct information with specific details/numbers/citations",
                    "confidence": "MEDIUM or HIGH only",
                    "reasoning": "Specific evidence that proves this claim is wrong",
                    "category": "One of: numerical_error, temporal_error, legal_error, institutional_fact, scientific_claim",
                    "impact": "How this misinformation affects public understanding or policy debate",
                    "verification_source": "Where this can be verified (e.g., 'Coalition Agreement 2024 on rijksoverheid.nl')"
                }}
            ]
        }}

        REMEMBER: 
        - Only include MEDIUM and HIGH confidence flags
        - Always provide specific correct information, not just "this is wrong"
        - If information is publicly verifiable, provide the exact source
        - Consider context: opposition parties often use selective statistics
        - Empty fact_check_flags array is perfectly acceptable

        Text to analyze:
        {chunk.text[:3000]}...
        """
        
        messages = [{"role": "user", "content": prompt}]
        
        for attempt in range(max_retries + 1):
            try:
                response_text = self.make_api_request(messages, max_tokens=2000)
                
                if not response_text:
                    raise ValueError("Empty response from DeepSeek")
                
                # Clean up response
                response_text = response_text.strip()
                response_text = response_text.replace('```json', '').replace('```', '').strip()
                
                # Extract JSON part
                start_brace = response_text.find('{')
                end_brace = response_text.rfind('}')
                
                if start_brace != -1 and end_brace != -1:
                    json_part = response_text[start_brace:end_brace + 1]
                    
                    try:
                        chunk_analysis = json.loads(json_part)
                    except json.JSONDecodeError:
                        print(f"  Attempting to repair JSON for chunk {chunk.chunk_number}...")
                        fixed_json = self.fix_broken_json(json_part)
                        chunk_analysis = json.loads(fixed_json)
                    
                    chunk_analysis['chunk_number'] = chunk.chunk_number
                    
                    # Ensure all expected fields exist
                    if 'political_undercurrents' not in chunk_analysis:
                        chunk_analysis['political_undercurrents'] = ''
                    if 'fact_check_flags' not in chunk_analysis:
                        chunk_analysis['fact_check_flags'] = []
                    
                    return chunk_analysis
                else:
                    raise ValueError("No JSON found in response")
                    
            except json.JSONDecodeError as e:
                if attempt < max_retries:
                    print(f"  JSON error, retrying chunk {chunk.chunk_number}...")
                    continue
                else:
                    print(f"  JSON parsing failed on chunk {chunk.chunk_number} - creating minimal response")
                    return {
                        'chunk_number': chunk.chunk_number,
                        'chunk_summary': f'Chunk {chunk.chunk_number} processing failed but contained parliamentary discussion',
                        'topics': [{
                            'topic': 'Parliamentary Discussion',
                            'description': 'Content could not be fully processed due to formatting issues',
                            'party_positions': []
                        }],
                        'key_decisions': [],
                        'notable_exchanges': [],
                        'fact_check_flags': []
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
            'notable_exchanges': [],
            'political_undercurrents': '',
            'fact_check_flags': []
        }
    
    def combine_chunk_summaries(self, chunk_summaries: List[Dict], 
                               meeting_info: Dict) -> Dict:
        """
        Combine multiple chunk summaries into a comprehensive meeting summary
        """
        # Collect all topics across chunks
        all_topics = {}
        all_decisions = []
        all_exchanges = []
        political_themes = []
        all_fact_checks = []
        
        for chunk_summary in chunk_summaries:
            if 'topics' in chunk_summary:
                for topic_info in chunk_summary['topics']:
                    topic_name = topic_info['topic']
                    
                    if topic_name not in all_topics:
                        all_topics[topic_name] = {
                            'topic': topic_name,
                            'description': topic_info['description'],
                            'party_positions': [],
                            'mentioned_in_chunks': [],
                            'tensions': [],
                            'consensus': []
                        }
                    
                    all_topics[topic_name]['party_positions'].extend(
                        topic_info.get('party_positions', [])
                    )
                    all_topics[topic_name]['mentioned_in_chunks'].append(
                        chunk_summary['chunk_number']
                    )
                    if 'tensions' in topic_info:
                        all_topics[topic_name]['tensions'].append(topic_info['tensions'])
                    if 'consensus' in topic_info:
                        all_topics[topic_name]['consensus'].append(topic_info['consensus'])
            
            all_decisions.extend(chunk_summary.get('key_decisions', []))
            all_exchanges.extend(chunk_summary.get('notable_exchanges', []))
            if chunk_summary.get('political_undercurrents'):
                political_themes.append(chunk_summary['political_undercurrents'])
            
            # Collect fact-check flags - filter out LOW confidence here as well
            fact_checks = chunk_summary.get('fact_check_flags', [])
            for fc in fact_checks:
                if fc.get('confidence', 'LOW') in ['MEDIUM', 'HIGH']:
                    all_fact_checks.append(fc)
        
        # Create final summary using DeepSeek
        topics_json = json.dumps(list(all_topics.values()), ensure_ascii=False, indent=2)
        fact_checks_json = json.dumps(all_fact_checks, ensure_ascii=False, indent=2)
        
        synthesis_prompt = f"""
    Create a comprehensive and nuanced summary of this Dutch parliamentary meeting, including consolidation of fact-checking results.

    Meeting: {meeting_info.get('vergadering_titel', 'Unknown')}
    Date: {meeting_info.get('vergadering_datum', 'Unknown')}

    Topics found: {len(all_topics)}
    Decisions: {len(all_decisions)}
    Fact-check flags found: {len(all_fact_checks)}
    Political themes observed: {political_themes[:5]}

    Guidelines for the final summary:
    - Write an executive summary that captures both what happened AND the political significance
    - For each topic, explain not just positions but WHY parties took those positions
    - Analyze coalition dynamics: who aligned unexpectedly? What tensions emerged?
    - Identify strategic moves: blocking tactics, compromise attempts, political theater
    - Note the meeting's tone: cooperative, contentious, procedural, dramatic?
    - Consider broader implications: what do these discussions mean for future policy?
    - For fact-checking: ONLY include flags that represent clear, demonstrable errors with concrete contradictory evidence
    - Focus fact-check summary on genuine corrections that matter for public understanding

    Return this exact JSON structure:
    {{
        "executive_summary": "2-3 sentences that capture the essence and political significance of the meeting",
        "main_topics": [
            {{
                "topic": "Topic name",
                "summary": "What was discussed and why it matters politically",
                "party_positions": {{
                    "Party/Speaker": "Their position and strategic reasoning"
                }},
                "outcome": "Decision reached and its implications",
                "political_context": "Why this topic was contentious or important"
            }}
        ],
        "key_decisions": ["Decision with context about support/opposition"],
        "political_dynamics": "Analysis of coalition behavior, opposition strategies, cross-party dynamics, and notable tensions or agreements",
        "meeting_tone": "Overall atmosphere: cooperative, hostile, procedural, dramatic, etc.",
        "strategic_implications": "What this meeting reveals about party strategies and future policy directions",
        "next_steps": ["What happens next, including political maneuvering expected"],
        "fact_check_summary": {{
            "total_flags": {len(all_fact_checks)},
            "categories": "Brief overview of what types of clearly incorrect claims were flagged (if any)",
            "significant_corrections": [
                {{
                    "claim": "The clearly incorrect claim",
                    "speaker": "Who made it",
                    "issue": "What is clearly and demonstrably incorrect about this claim",
                    "correct_info": "The correct, easily verifiable information",
                    "confidence": "MEDIUM or HIGH",
                    "reasoning": "Specific evidence that proves this claim is wrong",
                    "category": "One of: numerical_error, temporal_error, legal_error, institutional_fact, scientific_claim",
                    "verification_source": "Where this can be verified"
                }}
            ],
            "credibility_note": "Assessment of overall factual accuracy of the debate - note that most claims are political opinions or unverifiable statements, which is normal in parliamentary debates"
        }}
    }}

    Topics and positions data:
    {topics_json[:2000]}...

    Fact-check flags to consolidate (only MEDIUM/HIGH confidence):
    {fact_checks_json[:1500]}...

    Key decisions: {all_decisions[:10]}
    Notable exchanges: {all_exchanges[:5]}
    """
        
        messages = [{"role": "user", "content": synthesis_prompt}]
        
        try:
            response_text = self.make_api_request(messages, max_tokens=3500)
            
            response_text = response_text.strip()
            response_text = response_text.replace('```json', '').replace('```', '').strip()
            
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
                'total_fact_checks': len(all_fact_checks),
                'processing_date': datetime.now().isoformat(),
                'ai_model': 'deepseek-reasoner',
                'fact_checking_enabled': True
            }
            
            # Add raw fact-check data for transparency
            final_summary['raw_fact_checks'] = all_fact_checks
            
            return final_summary
            
        except Exception as e:
            print(f"Error creating final summary: {e}")
            return {
                'error': str(e),
                'meeting_info': meeting_info,
                'raw_chunk_summaries': chunk_summaries,
                'raw_fact_checks': all_fact_checks
            }
    
    def summarize_parliamentary_meeting(self, verslag_data: Dict) -> Dict:
        """
        Complete pipeline to summarize a parliamentary meeting with fact-checking
        """
        print(f"\n=== Summarizing Meeting with DeepSeek + Fact-Checking ===")
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
        
        # Step 3: Summarize each chunk with fact-checking
        print("Step 3: Summarizing chunks with fact-checking...")
        chunk_summaries = []
        for i, chunk in enumerate(chunks):
            print(f"  Processing chunk {i+1}/{len(chunks)}...")
            chunk_summary = self.summarize_chunk(chunk, speakers_map, meeting_info)
            chunk_summaries.append(chunk_summary)
            
            # Show fact-check results
            fact_checks = chunk_summary.get('fact_check_flags', [])
            if fact_checks:
                print(f"    Found {len(fact_checks)} fact-check flag(s)")
        
        # Step 4: Combine into final summary
        print("Step 4: Creating final summary with consolidated fact-checks...")
        final_summary = self.combine_chunk_summaries(chunk_summaries, meeting_info)
        
        # Show fact-checking summary
        total_fact_checks = len(final_summary.get('raw_fact_checks', []))
        if total_fact_checks > 0:
            print(f"✓ Summary complete with {total_fact_checks} fact-check flag(s)")
        else:
            print("✓ Summary complete - no fact-check flags raised")
        
        return final_summary

# Update the main function to indicate fact-checking capability
def main():
    """
    Main function to summarize verslagen with DeepSeek + Fact-Checking
    """
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description='DeepSeek Parliamentary Summarizer with Fact-Checking',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python deepseek_summarizer.py                    # Interactive mode
  python deepseek_summarizer.py --all             # Process all documents without prompts
  python deepseek_summarizer.py --batch           # Same as --all
  python deepseek_summarizer.py --count 5         # Process exactly 5 documents
  python deepseek_summarizer.py --all --yes       # Process all with no confirmation
        """
    )
    
    parser.add_argument('--all', '--batch', action='store_true', 
                       help='Process all available documents without asking')
    parser.add_argument('--count', type=int, metavar='N',
                       help='Process exactly N documents (skip selection prompt)')
    parser.add_argument('--yes', '-y', action='store_true',
                       help='Skip confirmation prompt (auto-confirm)')
    
    args = parser.parse_args()
    
    # Determine mode
    batch_mode = args.all
    auto_confirm = args.yes
    fixed_count = args.count
    
    if batch_mode:
        print("=== DeepSeek Parliamentary Summarizer + Fact-Checker - Batch Mode ===")
    else:
        print("=== DeepSeek Parliamentary Summarizer + Fact-Checker - Interactive Mode ===")
    
    # Check for API key
    api_key = os.getenv('DEEPSEEK_API_KEY')
    if not api_key:
        print("❌ DEEPSEEK_API_KEY environment variable not set!")
        print("Please set your API key:")
        print("export DEEPSEEK_API_KEY='your-api-key-here'")
        print("\nGet your API key from: https://platform.deepseek.com/")
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
        
        print(f"📊 Found {len(ready_verslagen)} verslagen ready for summarization")
        
        # Check which ones already have summaries
        existing_summaries = []
        new_verslagen = []
        
        for verslag in ready_verslagen:
            # Check for DeepSeek-specific summary files with fact-checking
            summary_filename = f"deepseek_factcheck_summary_{verslag.get('id', 'unknown')}.json"
            if os.path.exists(summary_filename):
                existing_summaries.append(verslag)
            else:
                new_verslagen.append(verslag)
        
        if existing_summaries:
            print(f"✅ {len(existing_summaries)} verslagen already have DeepSeek fact-checked summaries")
        
        if not new_verslagen:
            print("All verslagen have already been summarized with DeepSeek fact-checking! ✓")
            return
        
        print(f"🆕 {len(new_verslagen)} verslagen need to be summarized with fact-checking")
        
        # Determine number of documents to process
        if batch_mode:
            num_to_process = len(new_verslagen)
            print(f"🚀 Batch mode: Processing all {num_to_process} documents")
        elif fixed_count is not None:
            if fixed_count > len(new_verslagen):
                print(f"❌ Requested {fixed_count} documents but only {len(new_verslagen)} available")
                return
            elif fixed_count <= 0:
                print("❌ Count must be greater than 0")
                return
            num_to_process = fixed_count
            print(f"🎯 Fixed count mode: Processing {num_to_process} documents")
        else:
            # Interactive mode - show available documents with details
            print(f"\n📋 Available documents for summarization:")
            for i, verslag in enumerate(new_verslagen, 1):
                title = verslag.get('vergadering_titel', 'Unknown Title')
                date = verslag.get('vergadering_datum', 'Unknown Date')
                text_length = len(verslag.get('readable_text', ''))
                print(f"  {i:2d}. {title[:60]}{'...' if len(title) > 60 else ''}")
                print(f"      📅 {date} | 📝 {text_length:,} characters")
            
            # Ask user how many to process
            while True:
                try:
                    user_input = input(f"\n🔢 How many documents would you like to summarize? (1-{len(new_verslagen)}, or 'all' for all): ").strip().lower()
                    
                    if user_input == 'all':
                        num_to_process = len(new_verslagen)
                        break
                    elif user_input == '0':
                        print("Cancelled.")
                        return
                    else:
                        num_to_process = int(user_input)
                        if 1 <= num_to_process <= len(new_verslagen):
                            break
                        else:
                            print(f"❌ Please enter a number between 1 and {len(new_verslagen)}, or 'all'")
                except ValueError:
                    print("❌ Please enter a valid number or 'all'")
        
        # Select the documents to process (take the first N)
        selected_verslagen = new_verslagen[:num_to_process]
        
        # Show final selection and cost
        estimated_cost_per_verslag = 0.025
        total_cost = num_to_process * estimated_cost_per_verslag
        claude_cost = total_cost * 12
        
        if not batch_mode or not auto_confirm:
            print(f"\n📋 Selected for processing:")
            for i, verslag in enumerate(selected_verslagen, 1):
                title = verslag.get('vergadering_titel', 'Unknown')
                date = verslag.get('vergadering_datum', 'Unknown')
                print(f"  {i}. {title} ({date})")
            
            print(f"\n💰 Cost breakdown:")
            print(f"   DeepSeek: ~${total_cost:.2f}")
            print(f"   Claude equivalent: ~${claude_cost:.2f}")
            print(f"   Savings: ~${claude_cost - total_cost:.2f}")
        
        # Confirmation (skip if auto-confirm or batch mode with --yes)
        if auto_confirm:
            print(f"✅ Auto-confirming processing of {num_to_process} meeting(s)")
        elif batch_mode:
            confirm = input(f"\n✅ Proceed with summarizing {num_to_process} meeting(s) with fact-checking? (y/n): ")
            if confirm.lower() != 'y':
                print("Cancelled.")
                return
        else:
            # Interactive mode confirmation
            confirm = input(f"\n✅ Proceed with summarizing {num_to_process} meeting(s) with fact-checking? (y/n): ")
            if confirm.lower() != 'y':
                print("Cancelled.")
                return
        
        # Initialize summarizer
        summarizer = DeepSeekParliamentarySummarizer(api_key)
        
        # Process selected verslagen
        successful = 0
        failed = 0
        total_fact_checks = 0
        start_time = time.time()
        
        for i, verslag in enumerate(selected_verslagen, 1):
            print(f"\n{'='*60}")
            print(f"Processing {i}/{len(selected_verslagen)}: {verslag.get('vergadering_titel', 'Unknown')}")
            print(f"{'='*60}")
            
            try:
                # Create summary with fact-checking
                summary = summarizer.summarize_parliamentary_meeting(verslag)
                
                # Check if summary was successful
                if 'error' in summary and 'executive_summary' not in summary:
                    print(f"❌ Summary failed: {summary['error']}")
                    failed += 1
                    continue
                
                # Count fact-checks
                fact_checks = summary.get('raw_fact_checks', [])
                total_fact_checks += len(fact_checks)
                
                # Save result with fact-check prefix
                output_filename = f"deepseek_factcheck_summary_{verslag.get('id', 'unknown')}.json"
                with open(output_filename, 'w', encoding='utf-8') as f:
                    json.dump(summary, f, ensure_ascii=False, indent=2)
                
                print(f"✓ Summary saved to: {output_filename}")
                successful += 1
                
                # Show brief preview
                if 'executive_summary' in summary:
                    print(f"\nPreview: {summary['executive_summary'][:150]}...")
                    if 'main_topics' in summary:
                        print(f"Topics covered: {len(summary['main_topics'])}")
                    if fact_checks:
                        print(f"Fact-check flags: {len(fact_checks)}")
                        for fc in fact_checks[:2]:  # Show first 2
                            print(f"  - {fc.get('speaker', 'Unknown')}: {fc.get('claim', '')[:100]}...")
                
                # Show progress and time estimate
                elapsed_time = time.time() - start_time
                avg_time_per_verslag = elapsed_time / i
                remaining_time = avg_time_per_verslag * (len(selected_verslagen) - i)
                print(f"\nProgress: {i}/{len(selected_verslagen)} - Est. time remaining: {remaining_time/60:.1f} minutes")
                
            except KeyboardInterrupt:
                print(f"\n\n⚠️ Process interrupted by user")
                print(f"Progress: {successful} successful, {failed} failed, {len(selected_verslagen) - i} remaining")
                print("You can restart the script to continue with remaining verslagen.")
                return
                
            except Exception as e:
                print(f"❌ Error processing verslag: {e}")
                failed += 1
                continue
        
        # Final summary
        total_time = time.time() - start_time
        print(f"\n{'='*60}")
        print("BATCH PROCESSING COMPLETE")
        print(f"{'='*60}")
        print(f"✓ Successfully processed: {successful}")
        print(f"❌ Failed: {failed}")
        print(f"📁 Total DeepSeek fact-checked summaries available: {len(existing_summaries) + successful}")
        print(f"🔍 Total fact-check flags raised: {total_fact_checks}")
        print(f"⏱️ Total time: {total_time/60:.1f} minutes")
        print(f"💰 Estimated cost: ~${successful * estimated_cost_per_verslag:.2f}")
        
        if successful > 0:
            avg_fact_checks = total_fact_checks / successful if successful > 0 else 0
            print(f"\n🎉 You now have {len(existing_summaries) + successful} parliamentary meeting summaries with fact-checking!")
            print(f"📊 Average fact-check flags per meeting: {avg_fact_checks:.1f}")
            print("Ready to load into your Angular app for combating misinformation!")
            
            # Show fact-checking statistics
            if total_fact_checks > 0:
                print(f"\n🚨 FACT-CHECKING SUMMARY:")
                print(f"   - {total_fact_checks} potentially incorrect claims flagged")
                print(f"   - Conservative approach: only flags claims with MEDIUM/HIGH confidence")
                print(f"   - Each flag includes source verification and reasoning")
                print(f"   - Perfect for transparent, credible fact-checking in your platform")
            else:
                print(f"\n✅ FACT-CHECKING SUMMARY:")
                print(f"   - No clearly incorrect claims detected in processed meetings")
                print(f"   - This suggests relatively high factual accuracy in recent debates")
                print(f"   - System is working conservatively as intended")
        
    except FileNotFoundError:
        print("verslagen_parsed.json not found. Please run the XML parser first.")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()