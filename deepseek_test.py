import requests
import json
import os

def test_deepseek_api():
    """Simple test to verify DeepSeek API is working"""
    
    api_key = os.getenv('DEEPSEEK_API_KEY')
    if not api_key:
        print("❌ DEEPSEEK_API_KEY not set")
        return False
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    # Simple test message with no Unicode issues
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {
                "role": "user", 
                "content": "Hello! Can you summarize this simple text: 'The meeting discussed taxes. Party A supported higher taxes. Party B opposed them.' Please respond with a JSON object containing a summary."
            }
        ],
        "max_tokens": 500,
        "temperature": 0.1
    }
    
    try:
        print("Testing DeepSeek API...")
        response = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=30
        )
        
        print(f"Response status: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            content = result['choices'][0]['message']['content']
            print(f"✅ API working! Response: {content[:200]}...")
            return True
        else:
            print(f"❌ API Error: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Request failed: {e}")
        return False

def check_generated_summary():
    """Check what was actually saved in the summary file"""
    
    try:
        with open('deepseek_summary_84d94edd-499f-4d88-9e06-c5c0cd71b1c4.json', 'r', encoding='utf-8') as f:
            summary = json.load(f)
        
        print("\n=== Generated Summary Content ===")
        print(f"Keys in summary: {list(summary.keys())}")
        
        if 'error' in summary:
            print(f"Error in summary: {summary['error']}")
        
        if 'executive_summary' in summary:
            print(f"Executive summary: {summary['executive_summary'][:200]}...")
        
        if 'main_topics' in summary:
            print(f"Number of topics: {len(summary['main_topics'])}")
            
        if 'raw_chunk_summaries' in summary:
            chunk_summaries = summary['raw_chunk_summaries']
            print(f"Number of chunk summaries: {len(chunk_summaries)}")
            
            # Check if any chunks were processed successfully
            successful_chunks = [c for c in chunk_summaries if 'error' not in c]
            error_chunks = [c for c in chunk_summaries if 'error' in c]
            
            print(f"Successful chunks: {len(successful_chunks)}")
            print(f"Error chunks: {len(error_chunks)}")
            
            if error_chunks:
                print(f"Sample error: {error_chunks[0].get('error', 'Unknown')}")
    
    except FileNotFoundError:
        print("Summary file not found")
    except Exception as e:
        print(f"Error reading summary: {e}")

if __name__ == "__main__":
    print("=== DeepSeek Diagnostics ===")
    
    # Test 1: Basic API connectivity
    api_works = test_deepseek_api()
    
    # Test 2: Check what was generated
    check_generated_summary()
    
    if api_works:
        print("\n✅ DeepSeek API is working!")
        print("The issue is likely in the text processing, not the API itself.")
        print("We should create a version that works around the Unicode issues.")
    else:
        print("\n❌ DeepSeek API has issues. Check your API key and credits.")
