import tkapi
import json
import requests
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
import tempfile
import os
import time

# For text extraction
try:
    import PyPDF2
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

try:
    from docx import Document as DocxDocument
    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False

try:
    import mammoth
    MAMMOTH_AVAILABLE = True
except ImportError:
    MAMMOTH_AVAILABLE = False

class DocumentProcessor:
    """
    Enhanced processor to download and extract text from Tweede Kamer documents
    """
    
    def __init__(self):
        self.api = tkapi.TKApi()
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'TK-Summary-Bot/1.0'
        })
    
    def explore_verslag_structure(self, verslag_id: str):
        """Explore the structure of a verslag to understand how to access documents"""
        try:
            # Get all verslagen and find the one we want
            verslagen = self.api.get_verslagen(max_items=100)
            verslag = None
            
            for v in verslagen:
                if v.id == verslag_id:
                    verslag = v
                    break
            
            if not verslag:
                print(f"Could not find verslag with ID {verslag_id}")
                return None
            
            print(f"Exploring verslag structure:")
            print(f"  - ID: {verslag.id}")
            print(f"  - Available attributes: {[attr for attr in dir(verslag) if not attr.startswith('_')]}")
            
            # Try different ways to access document content
            methods_to_try = [
                'get_resource_url_or_none',
                'url',
                'resource_url'
            ]
            
            for method in methods_to_try:
                if hasattr(verslag, method):
                    try:
                        result = getattr(verslag, method)
                        if callable(result):
                            result = result()
                        print(f"  - {method}: {result}")
                    except Exception as e:
                        print(f"  - {method}: Error - {e}")
            
            # Try to get related documents
            if hasattr(verslag, 'related_items'):
                try:
                    documents = verslag.related_items('Document')
                    print(f"  - Related documents: {len(documents) if documents else 0}")
                    if documents:
                        doc = documents[0]
                        print(f"    - Document attributes: {[attr for attr in dir(doc) if not attr.startswith('_')]}")
                        if hasattr(doc, 'get_resource_url_or_none'):
                            print(f"    - Document URL: {doc.get_resource_url_or_none()}")
                except Exception as e:
                    print(f"  - Related documents error: {e}")
            
            return verslag
            
        except Exception as e:
            print(f"Error exploring verslag structure: {e}")
            return None

    def get_document_content(self, verslag_id: str) -> Optional[bytes]:
        """
        Download the raw document content for a verslag
        
        Args:
            verslag_id: ID of the verslag
            
        Returns:
            Raw document bytes or None
        """
        try:
            # First, let's explore the structure
            verslag = self.explore_verslag_structure(verslag_id)
            if not verslag:
                return None
            
            # Try different ways to get the document URL
            document_url = None
            
            # Method 1: Direct resource URL
            if hasattr(verslag, 'get_resource_url_or_none'):
                try:
                    document_url = verslag.get_resource_url_or_none()
                    print(f"Method 1 - Direct resource URL: {document_url}")
                except Exception as e:
                    print(f"Method 1 failed: {e}")
            
            # Method 2: Through URL property
            if not document_url and hasattr(verslag, 'url'):
                try:
                    base_url = verslag.url
                    if base_url:
                        # Try appending /resource to the base URL
                        document_url = base_url + '/resource'
                        print(f"Method 2 - URL + /resource: {document_url}")
                except Exception as e:
                    print(f"Method 2 failed: {e}")
            
            # Method 3: Through related documents
            if not document_url and hasattr(verslag, 'related_items'):
                try:
                    documents = verslag.related_items('Document')
                    if documents:
                        document = documents[0]
                        if hasattr(document, 'get_resource_url_or_none'):
                            document_url = document.get_resource_url_or_none()
                            print(f"Method 3 - Related document URL: {document_url}")
                except Exception as e:
                    print(f"Method 3 failed: {e}")
            
            # Method 4: Try direct API URL construction
            if not document_url:
                # Construct URL based on tkapi patterns
                base_api_url = "https://opendata.tweedekamer.nl/v4/2.0"
                document_url = f"{base_api_url}/Verslag('{verslag_id}')/resource"
                print(f"Method 4 - Direct API construction: {document_url}")
            
            if document_url:
                print(f"Attempting to download from: {document_url}")
                response = self.session.get(document_url)
                
                if response.status_code == 200:
                    print(f"Successfully downloaded {len(response.content)} bytes")
                    return response.content
                else:
                    print(f"Download failed with status code: {response.status_code}")
                    print(f"Response: {response.text[:200]}")
                    return None
            else:
                print(f"No document URL found for verslag {verslag_id}")
                return None
                
        except Exception as e:
            print(f"Error downloading document for {verslag_id}: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def extract_text_from_pdf(self, pdf_content: bytes) -> Optional[str]:
        """Extract text from PDF content"""
        if not PDF_AVAILABLE:
            print("PyPDF2 not available. Install with: pip install PyPDF2")
            return None
        
        try:
            with tempfile.NamedTemporaryFile() as temp_file:
                temp_file.write(pdf_content)
                temp_file.flush()
                
                with open(temp_file.name, 'rb') as file:
                    pdf_reader = PyPDF2.PdfReader(file)
                    text = ""
                    
                    for page in pdf_reader.pages:
                        text += page.extract_text() + "\n"
                    
                    return text.strip()
        except Exception as e:
            print(f"Error extracting PDF text: {e}")
            return None
    
    def extract_text_from_docx(self, docx_content: bytes) -> Optional[str]:
        """Extract text from DOCX content"""
        if not DOCX_AVAILABLE:
            print("python-docx not available. Install with: pip install python-docx")
            return None
        
        try:
            with tempfile.NamedTemporaryFile() as temp_file:
                temp_file.write(docx_content)
                temp_file.flush()
                
                doc = DocxDocument(temp_file.name)
                text = ""
                
                for paragraph in doc.paragraphs:
                    text += paragraph.text + "\n"
                
                return text.strip()
        except Exception as e:
            print(f"Error extracting DOCX text: {e}")
            return None
    
    def extract_text_from_doc(self, doc_content: bytes) -> Optional[str]:
        """Extract text from DOC content using mammoth"""
        if not MAMMOTH_AVAILABLE:
            print("mammoth not available. Install with: pip install mammoth")
            return None
        
        try:
            with tempfile.NamedTemporaryFile() as temp_file:
                temp_file.write(doc_content)
                temp_file.flush()
                
                with open(temp_file.name, 'rb') as file:
                    result = mammoth.extract_raw_text(file)
                    return result.value.strip()
        except Exception as e:
            print(f"Error extracting DOC text: {e}")
            return None
    
    def detect_content_type(self, content: bytes) -> str:
        """Detect the content type of the document"""
        if content.startswith(b'%PDF'):
            return 'pdf'
        elif content.startswith(b'PK'):  # ZIP-based formats like DOCX
            return 'docx'
        elif content.startswith(b'\xd0\xcf\x11\xe0'):  # OLE format like DOC
            return 'doc'
        else:
            return 'unknown'
    
    def extract_text_from_document(self, document_content: bytes) -> Optional[str]:
        """
        Extract text from document based on its type
        
        Args:
            document_content: Raw document bytes
            
        Returns:
            Extracted text or None
        """
        content_type = self.detect_content_type(document_content)
        
        print(f"Detected content type: {content_type}")
        
        if content_type == 'pdf':
            return self.extract_text_from_pdf(document_content)
        elif content_type == 'docx':
            return self.extract_text_from_docx(document_content)
        elif content_type == 'doc':
            return self.extract_text_from_doc(document_content)
        else:
            print(f"Unsupported content type: {content_type}")
            # Try to decode as plain text as fallback
            try:
                return document_content.decode('utf-8', errors='ignore')
            except:
                return None
    
    def process_verslag_with_content(self, verslag_data: Dict) -> Dict:
        """
        Process a verslag and extract its text content
        
        Args:
            verslag_data: Dictionary with verslag information
            
        Returns:
            Enhanced dictionary with text content
        """
        print(f"\nProcessing verslag: {verslag_data.get('vergadering_titel', 'Unknown')}")
        print(f"Verslag ID: {verslag_data['id']}")
        
        # Download document content
        document_content = self.get_document_content(verslag_data['id'])
        
        if document_content:
            print(f"Downloaded document: {len(document_content)} bytes")
            
            # Extract text
            extracted_text = self.extract_text_from_document(document_content)
            
            if extracted_text:
                print(f"Extracted text: {len(extracted_text)} characters")
                verslag_data['document_text'] = extracted_text
                verslag_data['document_size_bytes'] = len(document_content)
                verslag_data['text_length'] = len(extracted_text)
                verslag_data['content_extracted'] = True
                
                # Preview of the text
                preview = extracted_text[:200] + "..." if len(extracted_text) > 200 else extracted_text
                print(f"Text preview: {preview}")
            else:
                print("Failed to extract text from document")
                verslag_data['content_extracted'] = False
                verslag_data['error'] = "Text extraction failed"
        else:
            print("Failed to download document")
            verslag_data['content_extracted'] = False
            verslag_data['error'] = "Document download failed"
        
        return verslag_data

def save_to_json(data: List[Dict], filename: str):
    """Save data to JSON with proper encoding"""
    def convert_enums(item):
        if isinstance(item, dict):
            return {k: convert_enums(v) for k, v in item.items()}
        elif isinstance(item, list):
            return [convert_enums(v) for v in item]
        elif hasattr(item, '__str__') and not isinstance(item, (str, int, float, bool)) and item is not None:
            return str(item)
        else:
            return item
    
    converted_data = convert_enums(data)
    
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(converted_data, f, ensure_ascii=False, indent=2)
    
    print(f"Saved {len(data)} items to {filename}")

def main():
    """
    Main function to process documents and extract text
    """
    print("=== Tweede Kamer Document Processor ===")
    print()
    
    # Check what text extraction libraries are available
    print("Available text extraction libraries:")
    print(f"  - PyPDF2 (PDF): {'✓' if PDF_AVAILABLE else '✗ (install with: pip install PyPDF2)'}")
    print(f"  - python-docx (DOCX): {'✓' if DOCX_AVAILABLE else '✗ (install with: pip install python-docx)'}")
    print(f"  - mammoth (DOC): {'✓' if MAMMOTH_AVAILABLE else '✗ (install with: pip install mammoth)'}")
    print()
    
    # Load existing plenaire verslagen
    try:
        with open('plenaire_verslagen.json', 'r', encoding='utf-8') as f:
            plenaire_verslagen = json.load(f)
        
        print(f"Found {len(plenaire_verslagen)} plenaire verslagen to process")
        
        processor = DocumentProcessor()
        processed_verslagen = []  # Initialize early to avoid UnboundLocalError
        successful_count = 0
        failed_count = 0
        
        # Process ALL verslagen
        for i, verslag in enumerate(plenaire_verslagen):
            print(f"\n--- Processing {i+1}/{len(plenaire_verslagen)} ---")
            
            try:
                processed_verslag = processor.process_verslag_with_content(verslag.copy())
                processed_verslagen.append(processed_verslag)
                
                if processed_verslag.get('content_extracted', False):
                    successful_count += 1
                    print("✓ SUCCESS")
                else:
                    failed_count += 1
                    print("✗ FAILED")
                
                # Add a small delay to be respectful to the API
                time.sleep(1)
                
                # Save progress every 10 items (in case of interruption)
                if (i + 1) % 10 == 0:
                    print(f"\n--- Saving progress ({i+1}/{len(plenaire_verslagen)}) ---")
                    save_to_json(processed_verslagen, f"verslagen_with_content_progress_{i+1}.json")
                
            except Exception as e:
                print(f"✗ ERROR processing verslag {verslag.get('id', 'Unknown')}: {e}")
                # Add the verslag with error info
                verslag_copy = verslag.copy()
                verslag_copy['content_extracted'] = False
                verslag_copy['error'] = str(e)
                processed_verslagen.append(verslag_copy)
                failed_count += 1
                
                # Continue with next verslag
                continue
        
        # Save final results
        save_to_json(processed_verslagen, "verslagen_with_content.json")
        
        # Show summary
        print(f"\n=== Processing Complete ===")
        print(f"Total processed: {len(processed_verslagen)} documents")
        print(f"Successfully extracted: {successful_count} documents")
        print(f"Failed: {failed_count} documents")
        print(f"Success rate: {(successful_count/len(processed_verslagen)*100):.1f}%")
        
        if successful_count > 0:
            print("\nReady for next step: AI summarization!")
            print("You now have text content that can be fed to an LLM for summarization.")
            
            # Show some stats about the extracted content
            successful_verslagen = [v for v in processed_verslagen if v.get('content_extracted', False)]
            if successful_verslagen:
                avg_length = sum(v.get('text_length', 0) for v in successful_verslagen) / len(successful_verslagen)
                total_chars = sum(v.get('text_length', 0) for v in successful_verslagen)
                print(f"\nContent statistics:")
                print(f"  - Average text length: {avg_length:,.0f} characters")
                print(f"  - Total text extracted: {total_chars:,.0f} characters")
                print(f"  - Estimated tokens (÷4): {total_chars/4:,.0f} tokens")
        else:
            print("\nNext step: Install text extraction libraries and try again:")
            print("pip install PyPDF2 python-docx mammoth")
        
    except FileNotFoundError:
        print("No plenaire_verslagen.json found. Please run tk_data_retriever.py first.")
    except KeyboardInterrupt:
        print("\n\nProcessing interrupted by user.")
        # Check if we have any processed results to save
        if 'processed_verslagen' in locals() and processed_verslagen:
            print(f"Saving partial results ({len(processed_verslagen)} items)...")
            save_to_json(processed_verslagen, "verslagen_with_content_partial.json")
            print("Partial results saved. You can resume processing later.")
        else:
            print("No results to save (processing was interrupted too early).")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()