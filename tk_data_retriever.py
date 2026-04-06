import tkapi
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import requests
from pathlib import Path

class TweedeKamerDataRetriever:
    """
    A class to retrieve and process Tweede Kamer data using the tkapi library
    """
    
    def __init__(self):
        self.api = tkapi.TKApi()
        self.session = requests.Session()
        
    def _should_include_verslag(self, verslag) -> bool:
        """
        Determine if a verslag should be included based on status and soort filters
        
        Args:
            verslag: The verslag object to check
            
        Returns:
            True if verslag should be included, False otherwise
        """
        # Check soort - prefer EINDPUBLICATIE, but accept TUSSENPUBLICATIE for recent meetings
        soort = getattr(verslag, 'soort', None)
        if soort:
            soort_str = str(soort)
            # Accept EINDPUBLICATIE (preferred) or TUSSENPUBLICATIE (for recent meetings)
            if not ('EINDPUBLICATIE' in soort_str or 'TUSSENPUBLICATIE' in soort_str):
                return False
        
        # Check status - we're okay with ONGECORRIGEERD and GECORRIGEERD
        status = getattr(verslag, 'status', None)
        if status:
            status_str = str(status)
            # Accept both ONGECORRIGEERD and GECORRIGEERD
            if not ('ONGECORRIGEERD' in status_str or 'GECORRIGEERD' in status_str):
                return False
        
        return True
    
    def _deduplicate_verslagen(self, verslagen_data: List[Dict]) -> List[Dict]:
        """
        Remove duplicate verslagen based on vergadering_id, keeping only the preferred version
        
        Args:
            verslagen_data: List of processed verslag data
            
        Returns:
            Deduplicated list of verslagen
        """
        # Group by vergadering_id
        vergadering_groups = {}
        
        for verslag in verslagen_data:
            vergadering_id = verslag.get('vergadering_id')
            if not vergadering_id:
                continue
                
            if vergadering_id not in vergadering_groups:
                vergadering_groups[vergadering_id] = []
            
            vergadering_groups[vergadering_id].append(verslag)
        
        # For each group, select the best version
        deduplicated = []
        
        for vergadering_id, group in vergadering_groups.items():
            if len(group) == 1:
                deduplicated.append(group[0])
            else:
                # Multiple versions exist - select based on preference
                # Priority: EINDPUBLICATIE > TUSSENPUBLICATIE, GECORRIGEERD > ONGECORRIGEERD
                
                best_verslag = None
                best_score = -1
                
                for verslag in group:
                    score = 0
                    
                    # Soort scoring (higher is better)
                    soort = verslag.get('soort', '')
                    if 'EINDPUBLICATIE' in soort:
                        score += 100
                    elif 'TUSSENPUBLICATIE' in soort:
                        score += 50
                    
                    # Status scoring (higher is better)
                    status = verslag.get('status', '')
                    if 'GECORRIGEERD' in status:
                        score += 10
                    elif 'ONGECORRIGEERD' in status:
                        score += 5
                    
                    if score > best_score:
                        best_score = score
                        best_verslag = verslag
                
                if best_verslag:
                    deduplicated.append(best_verslag)
        
        # Also add verslagen without vergadering_id
        for verslag in verslagen_data:
            if not verslag.get('vergadering_id'):
                deduplicated.append(verslag)
        
        return deduplicated
        
    def get_recent_plenaire_verslagen(self, days_back: int = 30, max_items: int = 50) -> List[Dict]:
        """
        Retrieve recent plenaire verslagen (plenary meeting reports) with simple API calls
        
        Args:
            days_back: Number of days to look back from today
            max_items: Maximum number of verslagen to retrieve (before filtering)
            
        Returns:
            List of filtered and deduplicated verslagen data
        """
        print(f"Fetching plenaire verslagen from the last {days_back} days...")
        
        try:
            # Simple API call without any filter parameters
            verslagen = self.api.get_verslagen(max_items=max_items * 3)  # Get more to account for filtering
            
            # Calculate date range for client-side filtering
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days_back)
            
            # Filter and process the data
            plenaire_verslagen = []
            
            for verslag in verslagen:
                # Apply date filtering client-side
                if hasattr(verslag, 'datum') and verslag.datum:
                    # Handle both datetime and date objects
                    verslag_date = verslag.datum
                    if hasattr(verslag_date, 'date'):
                        verslag_date = verslag_date.date()
                    
                    if verslag_date < start_date.date() or verslag_date > end_date.date():
                        continue
                
                # Apply client-side filtering
                if not self._should_include_verslag(verslag):
                    continue
                
                # Check if this is a plenary meeting
                vergadering = verslag.vergadering if hasattr(verslag, 'vergadering') else None
                
                if vergadering and hasattr(vergadering, 'soort') and 'plenair' in str(vergadering.soort).lower():
                    verslag_data = {
                        'id': verslag.id,
                        'titel': verslag.titel if hasattr(verslag, 'titel') else None,
                        'datum': verslag.datum.isoformat() if hasattr(verslag, 'datum') and verslag.datum else None,
                        'vergadering_id': vergadering.id if vergadering else None,
                        'vergadering_titel': vergadering.titel if vergadering and hasattr(vergadering, 'titel') else None,
                        'status': str(verslag.status) if hasattr(verslag, 'status') else None,
                        'soort': str(verslag.soort) if hasattr(verslag, 'soort') else None,
                        'document_url': verslag.document_url if hasattr(verslag, 'document_url') else None,
                        'retrieved_at': datetime.now().isoformat()
                    }
                    plenaire_verslagen.append(verslag_data)
            
            # Deduplicate based on vergadering_id
            deduplicated_verslagen = self._deduplicate_verslagen(plenaire_verslagen)
            
            print(f"✓ Found {len(deduplicated_verslagen)} unique plenaire verslagen")
            
            return deduplicated_verslagen
            
        except Exception as e:
            print(f"Error fetching verslagen: {e}")
            return []
    
    def get_all_recent_verslagen(self, days_back: int = 30, max_items: int = 100) -> List[Dict]:
        """
        Get all recent verslagen with simple API calls
        
        Args:
            days_back: Number of days to look back
            max_items: Maximum number of items to retrieve (before filtering)
            
        Returns:
            List of filtered and deduplicated verslagen data
        """
        print(f"Fetching all verslagen from the last {days_back} days...")
        
        try:
            # Simple API call without any filter parameters - get more items
            print("⚠ Using client-side filtering only")
            verslagen = self.api.get_verslagen(max_items=max_items * 5)  # Get much more to account for filtering
            
            # Calculate date range for client-side filtering
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days_back)
            
            print(f"Looking for verslagen between {start_date.date()} and {end_date.date()}")
            
            processed_verslagen = []
            date_filtered_count = 0
            type_filtered_count = 0
            
            for verslag in verslagen:
                # Debug: Print first few verslag dates to understand the data
                if len(processed_verslagen) < 5:
                    vergadering = verslag.vergadering if hasattr(verslag, 'vergadering') else None
                    verg_datum = vergadering.datum if vergadering and hasattr(vergadering, 'datum') else None
                    print(f"Debug - Verslag {verslag.id}: verslag_datum={getattr(verslag, 'datum', None)}, vergadering_datum={verg_datum}, soort={getattr(verslag, 'soort', None)}")
                
                vergadering = verslag.vergadering if hasattr(verslag, 'vergadering') else None
                
                # Apply date filtering client-side - prioritize vergadering datum since verslag datum is often None
                date_to_check = None
                
                if hasattr(verslag, 'datum') and verslag.datum:
                    date_to_check = verslag.datum
                elif vergadering and hasattr(vergadering, 'datum') and vergadering.datum:
                    date_to_check = vergadering.datum
                
                if date_to_check:
                    # Handle both datetime and date objects
                    if hasattr(date_to_check, 'date'):
                        date_to_check = date_to_check.date()
                    
                    if date_to_check < start_date.date() or date_to_check > end_date.date():
                        date_filtered_count += 1
                        if len(processed_verslagen) < 3:  # Debug first few
                            print(f"Date filtered: {date_to_check} not in range {start_date.date()} to {end_date.date()}")
                        continue
                else:
                    # No date info available - include it anyway for now
                    print(f"Warning: No date info for verslag {verslag.id}, including anyway")
                
                # Apply client-side filtering
                if not self._should_include_verslag(verslag):
                    type_filtered_count += 1
                    if len(processed_verslagen) < 3:  # Debug first few
                        print(f"Type filtered: soort={getattr(verslag, 'soort', None)}, status={getattr(verslag, 'status', None)}")
                    continue
                
                # Use vergadering datum if verslag datum is missing
                datum_to_use = None
                if hasattr(verslag, 'datum') and verslag.datum:
                    datum_to_use = verslag.datum.isoformat()
                elif vergadering and hasattr(vergadering, 'datum') and vergadering.datum:
                    datum_to_use = vergadering.datum.isoformat()
                
                verslag_data = {
                    'id': verslag.id,
                    'titel': verslag.titel if hasattr(verslag, 'titel') else None,
                    'datum': datum_to_use,
                    'vergadering_id': vergadering.id if vergadering else None,
                    'vergadering_titel': vergadering.titel if vergadering and hasattr(vergadering, 'titel') else None,
                    'vergadering_soort': str(vergadering.soort) if vergadering and hasattr(vergadering, 'soort') else None,
                    'vergadering_datum': vergadering.datum.isoformat() if vergadering and hasattr(vergadering, 'datum') and vergadering.datum else None,
                    'status': str(verslag.status) if hasattr(verslag, 'status') else None,
                    'soort': str(verslag.soort) if hasattr(verslag, 'soort') else None,
                    'document_url': verslag.document_url if hasattr(verslag, 'document_url') else None,
                    'retrieved_at': datetime.now().isoformat()
                }
                processed_verslagen.append(verslag_data)
            
            # Deduplicate
            deduplicated_verslagen = self._deduplicate_verslagen(processed_verslagen)
            
            print(f"Found {len(verslagen)} total verslagen")
            print(f"Filtered out {date_filtered_count} verslagen due to date range")
            print(f"Filtered out {type_filtered_count} verslagen due to type/status")
            print(f"After filtering: {len(processed_verslagen)} verslagen")
            print(f"After deduplication: {len(deduplicated_verslagen)} unique verslagen")
            
            return deduplicated_verslagen
            
        except Exception as e:
            print(f"Error fetching verslagen: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def download_verslag_document(self, verslag_data: Dict, download_dir: str = "documents") -> Optional[str]:
        """
        Download the actual document file for a verslag
        
        Args:
            verslag_data: Dictionary containing verslag information
            download_dir: Directory to save documents
            
        Returns:
            Path to downloaded file, or None if failed
        """
        if not verslag_data.get('document_url'):
            print(f"No document URL for verslag {verslag_data.get('id')}")
            return None
        
        # Create download directory
        Path(download_dir).mkdir(exist_ok=True)
        
        try:
            response = self.session.get(verslag_data['document_url'])
            response.raise_for_status()
            
            # Determine file extension from content type or URL
            content_type = response.headers.get('content-type', '')
            if 'pdf' in content_type:
                ext = '.pdf'
            elif 'word' in content_type or 'msword' in content_type:
                ext = '.doc'
            elif 'wordprocessingml' in content_type:
                ext = '.docx'
            else:
                ext = '.txt'  # fallback
            
            # Create filename
            filename = f"{verslag_data['id']}{ext}"
            filepath = Path(download_dir) / filename
            
            # Save file
            with open(filepath, 'wb') as f:
                f.write(response.content)
            
            print(f"Downloaded: {filepath}")
            return str(filepath)
            
        except Exception as e:
            print(f"Error downloading document for {verslag_data.get('id')}: {e}")
            return None
    
    def get_vergaderingen_info(self, days_back: int = 90) -> List[Dict]:
        """
        Get information about recent vergaderingen (meetings)
        
        Args:
            days_back: Number of days to look back
            
        Returns:
            List of meeting information
        """
        print(f"Fetching vergaderingen from the last {days_back} days...")
        
        try:
            # Get all vergaderingen and filter client-side
            vergaderingen = self.api.get_vergaderingen(max_items=200)
            
            # Calculate date range for client-side filtering
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days_back)
            
            vergaderingen_data = []
            
            for vergadering in vergaderingen:
                # Apply date filtering client-side
                if hasattr(vergadering, 'datum') and vergadering.datum:
                    # Handle both datetime and date objects
                    vergadering_date = vergadering.datum
                    if hasattr(vergadering_date, 'date'):
                        vergadering_date = vergadering_date.date()
                    
                    if vergadering_date < start_date.date() or vergadering_date > end_date.date():
                        continue
                
                vergadering_data = {
                    'id': vergadering.id,
                    'titel': vergadering.titel if hasattr(vergadering, 'titel') else None,
                    'datum': vergadering.datum.isoformat() if hasattr(vergadering, 'datum') and vergadering.datum else None,
                    'soort': str(vergadering.soort) if hasattr(vergadering, 'soort') else None,
                    'aanvangstijd': str(vergadering.aanvangstijd) if hasattr(vergadering, 'aanvangstijd') else None,
                    'eindtijd': str(vergadering.eindtijd) if hasattr(vergadering, 'eindtijd') else None,
                    'retrieved_at': datetime.now().isoformat()
                }
                vergaderingen_data.append(vergadering_data)
            
            print(f"✓ Found {len(vergaderingen_data)} recent vergaderingen")
            return vergaderingen_data
            
        except Exception as e:
            print(f"Error fetching vergaderingen: {e}")
            return []

def safe_serialize(obj):
    """
    Safely serialize objects that might contain enums or other non-JSON types
    """
    if hasattr(obj, '__str__'):
        return str(obj)
    return obj

def save_to_json(data: List[Dict], filename: str):
    """
    Save data to a JSON file with proper formatting
    
    Args:
        data: List of dictionaries to save
        filename: Output filename
    """
    # Convert any enum objects to strings
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

def explore_api():
    """
    Explore what methods are available in the tkapi
    """
    api = tkapi.TKApi()
    print("=== Exploring tkapi methods ===")
    
    # Print all available methods
    methods = [method for method in dir(api) if not method.startswith('_')]
    print("Available methods:")
    for method in methods:
        print(f"  - {method}")
    print()
    
    # Try to get some basic data to understand the structure
    try:
        print("1. Getting personen (people)...")
        personen = api.get_personen(max_items=5)
        print(f"Found {len(personen)} personen")
        if personen:
            persoon = personen[0]
            print(f"Sample persoon attributes: {[attr for attr in dir(persoon) if not attr.startswith('_')]}")
        print()
    except Exception as e:
        print(f"Error getting personen: {e}")
    
    # Try verslagen without date filters
    try:
        print("2. Getting verslagen (reports)...")
        verslagen = api.get_verslagen(max_items=5)
        print(f"Found {len(verslagen)} verslagen")
        if verslagen:
            verslag = verslagen[0]
            print(f"Sample verslag attributes: {[attr for attr in dir(verslag) if not attr.startswith('_')]}")
            print(f"Sample verslag data:")
            print(f"  ID: {getattr(verslag, 'id', 'N/A')}")
            print(f"  Titel: {getattr(verslag, 'titel', 'N/A')}")
            print(f"  Datum: {getattr(verslag, 'datum', 'N/A')}")
            print(f"  Status: {getattr(verslag, 'status', 'N/A')}")
            print(f"  Soort: {getattr(verslag, 'soort', 'N/A')}")
        print()
    except Exception as e:
        print(f"Error getting verslagen: {e}")
    
    # Try vergaderingen
    try:
        print("3. Getting vergaderingen (meetings)...")
        vergaderingen = api.get_vergaderingen(max_items=5)
        print(f"Found {len(vergaderingen)} vergaderingen")
        if vergaderingen:
            vergadering = vergaderingen[0]
            print(f"Sample vergadering attributes: {[attr for attr in dir(vergadering) if not attr.startswith('_')]}")
            print(f"Sample vergadering data:")
            print(f"  ID: {getattr(vergadering, 'id', 'N/A')}")
            print(f"  Titel: {getattr(vergadering, 'titel', 'N/A')}")
            print(f"  Datum: {getattr(vergadering, 'datum', 'N/A')}")
            print(f"  Soort: {getattr(vergadering, 'soort', 'N/A')}")
        print()
    except Exception as e:
        print(f"Error getting vergaderingen: {e}")

def main():
    """
    Main function to demonstrate the usage with filtering and deduplication
    """
    print("=== Tweede Kamer Data Retriever (Filtered & Deduplicated) ===")
    print()
    
    # Initialize the retriever
    retriever = TweedeKamerDataRetriever()
    
    try:
        print("1. Fetching recent verslagen with filtering and deduplication...")
        verslagen = retriever.get_all_recent_verslagen(days_back=90, max_items=100)
        
        if verslagen:
            # Save all verslagen
            save_to_json(verslagen, "recent_verslagen.json")
            
            # Filter for plenaire
            plenaire = [v for v in verslagen if v.get('vergadering_soort') and 'plenair' in v['vergadering_soort'].lower()]
            if plenaire:
                save_to_json(plenaire, "plenaire_verslagen.json")
                print(f"Found {len(plenaire)} unique plenaire verslagen")
                print("Sample plenaire verslag:")
                print(json.dumps(plenaire[0], indent=2, ensure_ascii=False))
            else:
                print("No plenaire verslagen found in the recent data")
                print("Available vergadering types:")
                soorten = set(v.get('vergadering_soort', '') for v in verslagen if v.get('vergadering_soort'))
                for soort in sorted(soorten):
                    print(f"  - {soort}")
            
            # Show status and soort distribution
            print("\nStatus distribution:")
            status_counts = {}
            soort_counts = {}
            
            for v in verslagen:
                status = v.get('status', 'Unknown')
                soort = v.get('soort', 'Unknown')
                
                status_counts[status] = status_counts.get(status, 0) + 1
                soort_counts[soort] = soort_counts.get(soort, 0) + 1
            
            for status, count in status_counts.items():
                print(f"  {status}: {count}")
            
            print("\nSoort distribution:")
            for soort, count in soort_counts.items():
                print(f"  {soort}: {count}")
        else:
            print("❌ No verslagen found after filtering!")
            
            # Simple fallback debug - just show what's available
            debug_verslagen = retriever.api.get_verslagen(max_items=5)
            print(f"Note: {len(debug_verslagen)} verslagen available in API")
            
            if debug_verslagen:
                sample = debug_verslagen[0]
                vergadering = sample.vergadering if hasattr(sample, 'vergadering') else None
                print(f"Sample: {getattr(sample, 'soort', 'Unknown')} from {getattr(vergadering, 'datum', 'Unknown date') if vergadering else 'No meeting'}")
        
        print("\n2. Fetching recent vergaderingen...")
        vergaderingen = retriever.get_vergaderingen_info(days_back=90)
        
        if vergaderingen:
            save_to_json(vergaderingen, "recent_vergaderingen.json")
            print("Sample vergadering:")
            print(json.dumps(vergaderingen[0], indent=2, ensure_ascii=False))
    
    except Exception as e:
        print(f"Error in main execution: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n=== Basic Setup Complete! ===")
    print("You now have:")
    print("- recent_vergaderingen.json: List of recent meetings")
    print("- recent_verslagen.json: List of all recent meeting reports") 
    print("- plenaire_verslagen.json: List of plenary meeting reports (if any found)")
    print("\nFiltering applied:")
    print("- Prefers EINDPUBLICATIE, accepts TUSSENPUBLICATIE for recent meetings")
    print("- Accepts both ONGECORRIGEERD and GECORRIGEERD status")
    print("- Deduplicates based on vergadering_id, preferring EINDPUBLICATIE > TUSSENPUBLICATIE, GECORRIGEERD > ONGECORRIGEERD")

if __name__ == "__main__":
    # First install tkapi: pip install tkapi
    main()