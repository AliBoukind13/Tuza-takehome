# tests/test_api.py
# To run: python -m tests.test_api
import sys
import os
import json
import requests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
def test_api_endpoint():
    """Test the /extract API endpoint with a real PDF"""
    
    # Make sure the API is running first
    base_url = "http://localhost:8000"
    
    # Check if API is running
    try:
        response = requests.get(base_url)
        print(f"API Status: {response.json()}")
    except requests.exceptions.ConnectionError:
        print("ERROR: API is not running!")
        print("Start it with: uvicorn api:app --reload")
        return
    
    # Test the /extract endpoint
    print("\nTesting /extract endpoint")
    print("-" * 50)
    
    # Prepare the test data
    pdf_path = "statements/DojoRedacted1.pdf"
    upload_id = "API-TEST-123"
    
    with open(pdf_path, 'rb') as f:
        files = {'file': ('DojoRedacted1.pdf', f, 'application/pdf')}
        data = {'merchantStatementUploadId': upload_id}
        
        print(f"Sending PDF: {pdf_path}")
        print(f"Upload ID: {upload_id}")
        
        # Make the request
        response = requests.post(
            f"{base_url}/extract",
            files=files,
            data=data
        )
    
    # Check response
    if response.status_code == 200:
        print("\n[PASS] Success! Status: 200")
        
        # Parse JSON response
        result = response.json()
        
        # Save output
        with open("tests/tests_outputs/api_test_output.json", "w") as f:
            json.dump(result, f, indent=2)
        
        # Print summary
        print(f"\nExtraction Results:")
        print(f"  Merchant: {result.get('merchantName')}")
        print(f"  Provider: {result.get('paymentProvider')}")
        print(f"  Upload ID: {result.get('merchantStatementUploadId')}")
        
        # Check breakdown
        breakdown = result.get('breakdown', {})
        print(f"  Buckets: {len(breakdown)}")
        
        # Verify weird format
        if 'monthlyRevenue' in result:
            revenue = result['monthlyRevenue']
            if '___type' in revenue and '#decimal' in revenue:
                print(f"  [OK] Correct format with ___type and #decimal")
            else:
                print(f"  [FAIL] Wrong format - missing special fields")
        
        print(f"\nFull output saved to: tests/tests_outputs/api_test_output.json")
        
    else:
        print(f"\n[FAIL] Failed! Status: {response.status_code}")
        print(f"Error: {response.text}")
def test_invalid_file():
    """Test with invalid file type"""
    print("\n\nTesting with invalid file type...")
    print("-" * 50)
    
    base_url = "http://localhost:8000"
    
    # Try to send a .txt file
    files = {'file': ('test.txt', b'This is not a PDF', 'text/plain')}
    data = {'merchantStatementUploadId': 'INVALID-TEST'}
    
    response = requests.post(f"{base_url}/extract", files=files, data=data)
    
    if response.status_code == 400:
        print("[OK] Correctly rejected non-PDF file")
        print(f"Error message: {response.json().get('detail')}")
    else:
        print(f"[FAIL] Should have rejected but got status: {response.status_code}")
if __name__ == "__main__":
    # Make sure you have requests installed
    print("API Integration Tests")
    print("=" * 50)
    
    test_api_endpoint()
    test_invalid_file()