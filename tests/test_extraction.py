import sys
import os
import json
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extract_llm import StatementExtractor
from schemas.extraction_schema import ExtractedStatement

def test_single_extraction():
    """Test extraction on a single PDF."""
    print("Testing Statement Extraction")
    print("-" * 50)
    
    extractor = StatementExtractor(model="gpt-5")
    
    pdf_path = "statements/DojoRedacted1.pdf"
    print(f"\nExtracting from: {pdf_path}")
    
    try:
        result = extractor.extract_from_pdf(pdf_path)
        
        print(f"\nExtraction successful")
        print(f"Business Name: {result.business_name}")
        print(f"Statement Date: {result.statement_date}")
        print(f"Total Transaction Types: {len(result.transaction_charges)}")
        
        print("\nTransaction Charges:")
        for i, charge in enumerate(result.transaction_charges, 1):
            print(f"\n{i}. {charge.charge_type_description}")
            print(f"   Scheme: {charge.charge_type.scheme}")
            print(f"   Realm: {charge.charge_type.realm}")
            print(f"   Region: {charge.charge_type.region}")
            print(f"   Presence: {charge.charge_type.presence}")
            print(f"   Rate: {charge.charge_rate}")
            print(f"   Total: {charge.charge_total}")
            if charge.reasoning:
                print(f"   Reasoning: {charge.reasoning}")
            if charge.charge_type.scheme == "other":
                print(f"   Other Scheme: {charge.charge_type.scheme_other_description}")
        
        output_path = "tests/test_output.json"
        with open(output_path, "w") as f:
            json.dump(result.model_dump(), f, indent=2)
        print(f"\nFull output saved to: {output_path}")
        
        print("\nValidation Checks:")
        print("-" * 50)
        
        assert result.business_name, "Missing business name"
        assert result.statement_date, "Missing statement date"
        assert len(result.transaction_charges) > 0, "No transaction charges extracted"
        
        for charge in result.transaction_charges:
            assert charge.charge_type_description, "Missing charge description"
            assert charge.charge_type.scheme, "Missing scheme"
            assert charge.number_of_transactions >= 0, "Invalid transaction count"
            
            if charge.charge_type.scheme == "other":
                assert charge.charge_type.scheme_other_description, "OTHER scheme missing description"
        
        print("All validation checks passed")
        
        if result.total_value and result.total_charges:
            print(f"\nExtracted Totals (for validation):")
            print(f"  Total Value: {result.total_value}")
            print(f"  Total Charges: {result.total_charges}")
            
            calc_value = sum(
                float(t.transactions_value.replace('£', '').replace(',', ''))
                for t in result.transaction_charges
            )
            calc_charges = sum(
                float(t.charge_total.replace('£', '').replace(',', ''))
                for t in result.transaction_charges
            )
            
            print(f"\nCalculated from rows:")
            print(f"  Total Value: £{calc_value:,.2f}")
            print(f"  Total Charges: £{calc_charges:,.2f}")
        
        return result
        
    except Exception as e:
        print(f"\nError during extraction: {str(e)}")
        import traceback
        traceback.print_exc()
        raise

def test_all_pdfs():
    """Test extraction on all PDFs in statements folder."""
    print("\nTesting All PDFs")
    print("-" * 50)
    
    extractor = StatementExtractor(model="gpt-4-turbo-preview")
    
    pdf_files = [
        "statements/DojoRedacted1.pdf",
        "statements/DojoRedacted2.pdf",
        "statements/DojoRedacted3.pdf",
        "statements/DojoRedacted4.pdf",
        "statements/DojoRedacted5.pdf",
        "statements/DojoRedacted6.pdf",
        "statements/LloydsRedacted1.pdf",
        "statements/WorldpayRedacted1.pdf",
        "statements/WorldpayRedacted2.pdf",
    ]
    
    results = {}
    for pdf_path in pdf_files:
        print(f"\nProcessing: {pdf_path}")
        try:
            result = extractor.extract_from_pdf(pdf_path)
            results[pdf_path] = {
                "success": True,
                "business_name": result.business_name,
                "charges_count": len(result.transaction_charges)
            }
            print(f"  Success - {len(result.transaction_charges)} charges extracted")
        except Exception as e:
            results[pdf_path] = {
                "success": False,
                "error": str(e)
            }
            print(f"  Failed: {e}")
    
    print("\nSummary:")
    successful = sum(1 for r in results.values() if r["success"])
    print(f"Successful: {successful}/{len(pdf_files)}")
    
    return results

if __name__ == "__main__":
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("Error: Please set OPENAI_API_KEY in your .env file")
        exit(1)
    
    test_single_extraction()