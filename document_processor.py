import tkapi
import json
import requests
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
import tempfile
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse

from summary_store import already_summarized

# Downloaded documents are cached here; a verslag id always maps to the same
# bytes, so a cached file never goes stale.
CACHE_DIR = Path("documents")
RETRIES = 3

# For text extraction
try:
    import pypdf
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
    
    def get_document_content(self, verslag_id: str) -> Optional[bytes]:
        """
        Download the raw document content for a verslag.

        Tries the known resource URL pattern directly, avoiding the need to
        search through a paginated list of verslagen.

        A verslag id identifies one specific version of a transcript and its
        bytes never change, so a downloaded document is cached on disk and
        reused. Transient failures are retried; without that, one bad response
        silently drops a debate for the night.
        """
        cached = CACHE_DIR / f"{verslag_id}.bin"
        if cached.exists():
            print(f"Using cached document ({cached.stat().st_size} bytes)")
            return cached.read_bytes()

        base = "https://gegevensmagazijn.tweedekamer.nl/OData/v4/2.0"
        url = f"{base}/Verslag({verslag_id})/TK.DA.GGM.OData.Resource()"

        for attempt in range(RETRIES):
            try:
                response = self.session.get(url, timeout=60)

                if response.status_code == 200:
                    print(f"Successfully downloaded {len(response.content)} bytes")
                    CACHE_DIR.mkdir(parents=True, exist_ok=True)
                    cached.write_bytes(response.content)
                    return response.content

                # 4xx other than rate limiting will not improve on retry.
                if response.status_code < 500 and response.status_code != 429:
                    print(f"Download failed with status code: {response.status_code}")
                    return None

                print(f"Download got {response.status_code}, attempt {attempt + 1}/{RETRIES}")
            except requests.RequestException as e:
                print(f"Download error ({attempt + 1}/{RETRIES}): {e}")

            if attempt < RETRIES - 1:
                time.sleep(2 ** attempt)

        print(f"Giving up on {verslag_id} after {RETRIES} attempts")
        return None
    
    def extract_text_from_pdf(self, pdf_content: bytes) -> Optional[str]:
        """Extract text from PDF content"""
        if not PDF_AVAILABLE:
            print("pypdf not available. Install with: pip install pypdf")
            return None

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp_file:
                tmp_path = temp_file.name
                temp_file.write(pdf_content)

            reader = pypdf.PdfReader(tmp_path)
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            return text.strip()
        except Exception as e:
            print(f"Error extracting PDF text: {e}")
            return None
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)
    
    def extract_text_from_docx(self, docx_content: bytes) -> Optional[str]:
        """Extract text from DOCX content"""
        if not DOCX_AVAILABLE:
            print("python-docx not available. Install with: pip install python-docx")
            return None

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as temp_file:
                tmp_path = temp_file.name
                temp_file.write(docx_content)

            doc = DocxDocument(tmp_path)
            text = "\n".join(p.text for p in doc.paragraphs)
            return text.strip()
        except Exception as e:
            print(f"Error extracting DOCX text: {e}")
            return None
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def extract_text_from_doc(self, doc_content: bytes) -> Optional[str]:
        """Extract text from DOC content using mammoth"""
        if not MAMMOTH_AVAILABLE:
            print("mammoth not available. Install with: pip install mammoth")
            return None

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".doc", delete=False) as temp_file:
                tmp_path = temp_file.name
                temp_file.write(doc_content)

            with open(tmp_path, 'rb') as file:
                result = mammoth.extract_raw_text(file)
                return result.value.strip()
        except Exception as e:
            print(f"Error extracting DOC text: {e}")
            return None
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)
    
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
    print(f"  - pypdf (PDF): {'✓' if PDF_AVAILABLE else '✗ (install with: pip install pypdf)'}")
    print(f"  - python-docx (DOCX): {'✓' if DOCX_AVAILABLE else '✗ (install with: pip install python-docx)'}")
    print(f"  - mammoth (DOC): {'✓' if MAMMOTH_AVAILABLE else '✗ (install with: pip install mammoth)'}")
    print()
    
    parser = argparse.ArgumentParser(description="Download and extract verslag text")
    parser.add_argument(
        "--all",
        action="store_true",
        help="also process verslagen that already have a summary "
        "(needed before re-summarizing one with summarizer.py --only)",
    )
    args = parser.parse_args()

    # Load existing plenaire verslagen
    try:
        with open('plenaire_verslagen.json', 'r', encoding='utf-8') as f:
            plenaire_verslagen = json.load(f)

        total = len(plenaire_verslagen)

        # A verslag that already has a summary has nothing left to contribute:
        # its document does not need downloading and its text does not need
        # parsing. The nightly run fetches a rolling 7-day window, so most of
        # what it sees was already handled on a previous night.
        if not args.all:
            plenaire_verslagen = [
                v for v in plenaire_verslagen
                if not already_summarized(v.get('id', ''))
            ]
            skipped = total - len(plenaire_verslagen)
            if skipped:
                print(f"Skipping {skipped} verslag(en) that already have a summary")

        if not plenaire_verslagen:
            print("Nothing new to process. Every verslag already has a summary.")
            save_to_json([], "verslagen_with_content.json")
            return

        print(f"Found {len(plenaire_verslagen)} plenaire verslagen to process")
        
        processor = DocumentProcessor()
        processed_verslagen = []
        successful_count = 0
        failed_count = 0
        MAX_WORKERS = 4

        def process_one(args):
            i, verslag = args
            print(f"\n--- Processing {i+1}/{len(plenaire_verslagen)} ---")
            try:
                result = processor.process_verslag_with_content(verslag.copy())
                status = "✓ SUCCESS" if result.get('content_extracted') else "✗ FAILED"
                print(status)
                return result
            except Exception as e:
                print(f"✗ ERROR processing verslag {verslag.get('id', 'Unknown')}: {e}")
                verslag_copy = verslag.copy()
                verslag_copy['content_extracted'] = False
                verslag_copy['error'] = str(e)
                return verslag_copy

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(process_one, (i, v)): i
                       for i, v in enumerate(plenaire_verslagen)}
            for future in as_completed(futures):
                result = future.result()
                processed_verslagen.append(result)
                if result.get('content_extracted'):
                    successful_count += 1
                else:
                    failed_count += 1


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