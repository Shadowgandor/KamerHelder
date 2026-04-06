import json
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional
import re
from datetime import datetime

class VLOSDocumentParser:
    """
    Parser for VLOS (Verslaglegging Ondersteunend Systeem) XML documents
    """
    
    def __init__(self):
        self.namespace = "{http://www.tweedekamer.nl/ggm/vergaderverslag/v1.0}"
    
    def clean_xml_content(self, xml_content: str) -> str:
        """Clean up the XML content by removing the BOM and other artifacts"""
        # Remove BOM (Byte Order Mark) if present
        if xml_content.startswith('\ufeff'):
            xml_content = xml_content[1:]
        
        # Remove any leading non-XML characters
        xml_start = xml_content.find('<?xml')
        if xml_start > 0:
            xml_content = xml_content[xml_start:]
        
        return xml_content
    
    def parse_vergadering_info(self, root) -> Dict:
        """Extract meeting information from the XML"""
        vergadering = root.find(f"{self.namespace}vergadering")
        if vergadering is None:
            return {}
        
        info = {
            'soort': vergadering.get('soort'),
            'kamer': vergadering.get('kamer'),
            'titel': self.get_text(vergadering, 'titel'),
            'zaal': self.get_text(vergadering, 'zaal'),
            'vergaderjaar': self.get_text(vergadering, 'vergaderjaar'),
            'vergaderingnummer': self.get_text(vergadering, 'vergaderingnummer'),
            'datum': self.get_text(vergadering, 'datum'),
            'aanvangstijd': self.get_text(vergadering, 'aanvangstijd'),
        }
        
        return {k: v for k, v in info.items() if v}
    
    def get_text(self, element, tag_name):
        """Safely get text from an XML element"""
        child = element.find(f"{self.namespace}{tag_name}")
        return child.text if child is not None else None
    
    def parse_agendapunten(self, root) -> List[Dict]:
        """Extract agenda items from the XML"""
        agendapunten = []
        
        # Look for agendapunt elements
        for agendapunt in root.findall(f".//{self.namespace}agendapunt"):
            item = {
                'nummer': agendapunt.get('nummer'),
                'onderwerp': self.get_text(agendapunt, 'onderwerp'),
                'tekst': self.extract_agendapunt_text(agendapunt)
            }
            agendapunten.append(item)
        
        return agendapunten
    
    def extract_agendapunt_text(self, agendapunt) -> str:
        """Extract all text content from an agenda item"""
        text_parts = []
        
        # Get text from various elements within the agendapunt
        for elem in agendapunt.iter():
            if elem.text and elem.text.strip():
                text_parts.append(elem.text.strip())
        
        return ' '.join(text_parts)
    
    def parse_sprekers(self, root) -> List[Dict]:
        """Extract speaker information and their contributions"""
        sprekers = []
        
        # Look for spreker elements
        for spreker in root.findall(f".//{self.namespace}spreker"):
            speaker_info = {
                'naam': spreker.get('naam'),
                'functie': spreker.get('functie'),
                'fractie': spreker.get('fractie'),
                'tekst': self.extract_spreker_text(spreker)
            }
            sprekers.append(speaker_info)
        
        return sprekers
    
    def extract_spreker_text(self, spreker) -> str:
        """Extract all text content from a speaker's contribution"""
        text_parts = []
        
        for elem in spreker.iter():
            if elem.text and elem.text.strip():
                text_parts.append(elem.text.strip())
        
        return ' '.join(text_parts)
    
    def extract_all_text(self, root) -> str:
        """Extract all readable text from the document"""
        text_parts = []
        
        # Walk through all elements and collect text
        for elem in root.iter():
            if elem.text and elem.text.strip():
                text = elem.text.strip()
                # Skip very short strings and timestamps
                if len(text) > 3 and not re.match(r'^\d{4}-\d{2}-\d{2}T', text):
                    text_parts.append(text)
        
        # Join and clean up the text
        full_text = ' '.join(text_parts)
        
        # Clean up multiple spaces
        full_text = re.sub(r'\s+', ' ', full_text)
        
        return full_text.strip()
    
    def parse_document(self, xml_content: str) -> Dict:
        """
        Parse a VLOS XML document and extract structured information
        
        Args:
            xml_content: Raw XML content string
            
        Returns:
            Dictionary with parsed document information
        """
        try:
            # Clean the XML content
            cleaned_xml = self.clean_xml_content(xml_content)
            
            # Parse XML
            root = ET.fromstring(cleaned_xml)
            
            # Extract document metadata
            document_info = {
                'message_id': root.get('MessageID'),
                'source': root.get('Source'),
                'message_type': root.get('MessageType'),
                'timestamp': root.get('Timestamp'),
                'soort': root.get('soort'),
                'status': root.get('status'),
                'versie': root.get('versie'),
            }
            
            # Extract meeting information
            vergadering_info = self.parse_vergadering_info(root)
            
            # Extract agenda items
            agendapunten = self.parse_agendapunten(root)
            
            # Extract speakers
            sprekers = self.parse_sprekers(root)
            
            # Extract all text content
            full_text = self.extract_all_text(root)
            
            return {
                'document_info': document_info,
                'vergadering_info': vergadering_info,
                'agendapunten': agendapunten,
                'sprekers': sprekers,
                'full_text': full_text,
                'text_length': len(full_text),
                'num_agendapunten': len(agendapunten),
                'num_sprekers': len(sprekers),
                'parsed_successfully': True
            }
            
        except ET.XMLSyntaxError as e:
            return {
                'error': f'XML parsing error: {e}',
                'parsed_successfully': False
            }
        except Exception as e:
            return {
                'error': f'General parsing error: {e}',
                'parsed_successfully': False
            }

def process_verslagen_with_xml_parsing():
    """
    Process the verslagen with content and parse the XML properly
    """
    print("=== Processing VLOS XML Documents ===")
    
    try:
        # Load the verslagen with content
        with open('verslagen_with_content.json', 'r', encoding='utf-8') as f:
            verslagen = json.load(f)
        
        parser = VLOSDocumentParser()
        processed_verslagen = []
        
        for i, verslag in enumerate(verslagen):
            print(f"\n--- Processing {i+1}/{len(verslagen)} ---")
            print(f"Verslag: {verslag.get('vergadering_titel', 'Unknown')}")
            
            if verslag.get('content_extracted') and verslag.get('document_text'):
                # Parse the XML content
                parsed_content = parser.parse_document(verslag['document_text'])
                
                if parsed_content.get('parsed_successfully'):
                    print(f"✓ Successfully parsed XML")
                    print(f"  - Text length: {parsed_content['text_length']} characters")
                    print(f"  - Agenda items: {parsed_content['num_agendapunten']}")
                    print(f"  - Speakers: {parsed_content['num_sprekers']}")
                    
                    # Add parsed content to verslag
                    verslag['parsed_content'] = parsed_content
                    verslag['readable_text'] = parsed_content['full_text']
                    verslag['summary_ready'] = True
                    
                    # Show a preview
                    preview = parsed_content['full_text'][:300] + "..." if len(parsed_content['full_text']) > 300 else parsed_content['full_text']
                    print(f"  - Text preview: {preview}")
                    
                else:
                    print(f"✗ Failed to parse XML: {parsed_content.get('error', 'Unknown error')}")
                    verslag['summary_ready'] = False
            else:
                print("✗ No content to parse")
                verslag['summary_ready'] = False
            
            processed_verslagen.append(verslag)
        
        # Save processed results
        with open('verslagen_parsed.json', 'w', encoding='utf-8') as f:
            json.dump(processed_verslagen, f, ensure_ascii=False, indent=2)
        
        # Summary
        successful = sum(1 for v in processed_verslagen if v.get('summary_ready', False))
        print(f"\n=== Processing Complete ===")
        print(f"Successfully parsed: {successful}/{len(processed_verslagen)} documents")
        print(f"Saved results to: verslagen_parsed.json")
        
        if successful > 0:
            print(f"\n🎉 Ready for AI summarization!")
            print(f"You now have {successful} parliamentary meeting transcripts with clean, readable text.")
            print(f"Next step: Set up LLM integration for summarization!")
            
            # Show one example of the structure
            example = next((v for v in processed_verslagen if v.get('summary_ready')), None)
            if example:
                print(f"\nExample structure:")
                print(f"- Meeting: {example.get('vergadering_titel')}")
                print(f"- Date: {example.get('vergadering_datum')}")
                print(f"- Text length: {len(example.get('readable_text', ''))} characters")
                if example.get('parsed_content', {}).get('vergadering_info'):
                    print(f"- Meeting details: {example['parsed_content']['vergadering_info']}")
        
    except FileNotFoundError:
        print("No verslagen_with_content.json found. Please run document_processor.py first.")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    process_verslagen_with_xml_parsing()
