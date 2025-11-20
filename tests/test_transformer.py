# to run: python -m tests.test_transformer 

import json
import sys
import os


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extract_llm import extract_statement
from transformer import StatementTransformer

def test_transformer_full_pipeline():
    """Test the complete extraction -> transformation pipeline"""
    

    print("Extracting from PDF")
    extracted = extract_statement("statements/DojoRedacted1.pdf","gpt-5")
    

    print("Transforming extracted data")
    transformer = StatementTransformer()
    result = transformer.transform(extracted, upload_id="TEST-123")

    output = result.model_dump(by_alias=True)
    
    # Save final output
    with open("tests/tests_outputs/transformation_output.json", "w") as f:
        json.dump(output, f, indent=2)
    
    # Print results
    print(json.dumps(output, indent=2))
    
    # Print summary
    print(f"Pipeline Summary:")
    print(f"Merchant: {result.merchantName}")
    print(f"Provider: {result.paymentProvider}")
    print(f"Extracted {len(extracted.transaction_charges)} transaction rows")
    print(f"Transformed into {len(result.breakdown)} unique buckets")
    print(f"Monthly Revenue: £{result.monthlyRevenue.decimal}")
    print(f"Monthly Charges: £{result.monthlyCharges.decimal}")
    print(f"Average Transaction: £{result.averageTransactionAmount.decimal}")
    
    # Show breakdown
    print(f"\nBreakdown by bucket:")
    print(f"{'-'*50}")

    total_percentage = 0 
    
    for key, item in result.breakdown.items():
        percentage = float(item.percentageSplit.decimal) * 100
        total_percentage += percentage
        print(f"  {key}: {percentage:.2f}%")
    
    print(f"{'-'*50}")
    print(f"  TOTAL: {total_percentage:.2f}%")
    
    # Show any warnings
    if result.extractionMetadata.get('warnings'):
        print(f"\nWarnings:")
        for warning in result.extractionMetadata['warnings']:
            print(f"  WARNING ! : {warning}")

if __name__ == "__main__":
    test_transformer_full_pipeline()