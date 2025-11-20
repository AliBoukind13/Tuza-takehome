# transformer.py
from typing import Dict, List, Optional, Tuple
from decimal import Decimal, ROUND_HALF_UP
from schemas.extraction_schema import ExtractedStatement, TransactionCharge
from schemas.output_schema import (
    NewMerchantStatement, MoneyType, PercentageType, 
    FeeStructure, BreakdownItem
)
import re
import logging

logger = logging.getLogger(__name__)

class StatementTransformer:
    """
    Transforms extracted statement data into NewMerchantStatement format.
    Handles all the complex calculation logic and edge cases.
    """
    
    def __init__(self):
        self.errors = []
        self.warnings = []
    
    def transform(
        self, 
        extracted: ExtractedStatement,
        upload_id: str
    ) -> NewMerchantStatement:
        """
        Main transformation method.
        
        Args:
            extracted: The extracted statement from LLM
            upload_id: The merchant statement upload ID
            
        Returns:
            NewMerchantStatement with all calculations
        """
        logger.info(f"Starting transformation for {extracted.merchant_name}")
        
        # Reset error tracking
        self.errors = []
        self.warnings = []
        
        # Calculate aggregates
        monthly_revenue = self._calculate_total_revenue(extracted.transaction_charges)
        monthly_charges = self._calculate_total_charges(extracted.transaction_charges)
        avg_transaction = self._calculate_average_transaction(extracted.transaction_charges)
        
        # Create breakdown buckets
        breakdown = self._create_breakdown(extracted.transaction_charges, monthly_revenue)
        
        # Parse auth fee if present
        auth_fee = None
        if extracted.authorisation_fee:
            auth_fee = self._parse_money_to_type(extracted.authorisation_fee)
        
        # Build the output
        result = NewMerchantStatement(
            merchantStatementUploadId=upload_id,
            merchantName=extracted.merchant_name,
            merchantId=extracted.merchant_id,
            paymentProvider=extracted.payment_provider,
            statementDate=extracted.statement_date,
            statementPeriod=extracted.statement_period,
            monthlyRevenue=MoneyType.from_decimal(monthly_revenue),
            monthlyCharges=MoneyType.from_decimal(monthly_charges),
            averageTransactionAmount=MoneyType.from_decimal(avg_transaction),
            breakdown=breakdown,
            authorisationFee=auth_fee,
            registeredCompany=extracted.registered_company,
            merchantCategoryCode=extracted.merchant_category_code,
            extractionMetadata={
                "totalTransactionTypes": len(extracted.transaction_charges),
                "errors": self.errors,
                "warnings": self.warnings,
                "extractedTotals": {
                    "value": extracted.total_value,
                    "charges": extracted.total_charges
                }
            }
        )
        
        logger.info(f"Transformation complete with {len(breakdown)} breakdown buckets")
        return result
    
    def _calculate_total_revenue(self, charges: List[TransactionCharge]) -> Decimal:
        """Calculate total transaction value across all charges"""
        total = Decimal(0)
        for charge in charges:
            value = self._parse_money(charge.transactions_value)
            total += value
        return total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    
    def _calculate_total_charges(self, charges: List[TransactionCharge]) -> Decimal:
        """Calculate total fees charged"""
        total = Decimal(0)
        for charge in charges:
            value = self._parse_money(charge.charge_total)
            total += value
        return total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    
    def _calculate_average_transaction(self, charges: List[TransactionCharge]) -> Decimal:
        """Calculate average transaction amount"""
        total_value = Decimal(0)
        total_count = 0
        
        for charge in charges:
            value = self._parse_money(charge.transactions_value)
            count = charge.number_of_transactions
            total_value += value
            total_count += count
        
        if total_count == 0:
            return Decimal(0)
        
        avg = total_value / total_count
        return avg.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    
    def _create_breakdown(
        self, 
        charges: List[TransactionCharge],
        total_revenue: Decimal
    ) -> Dict[str, BreakdownItem]:
        """
        Create breakdown buckets with percentage splits and fee structures.
        """
        breakdown = {}
        
        for charge in charges:
            # Generate bucket key
            bucket_key = self._generate_bucket_key(charge)
            
            # Calculate percentage of total
            charge_value = self._parse_money(charge.transactions_value)
            percentage_split = Decimal(0)
            if total_revenue > 0:
                percentage_split = (charge_value / total_revenue)
                # Keep more precision for percentages
                percentage_split = percentage_split.quantize(
                    Decimal('0.00000001'), rounding=ROUND_HALF_UP
                )
            
            # Parse fee structure from charge_rate
            percentage_fee, fixed_fee = self._parse_rate_structure(charge.charge_rate)
            
            # Create breakdown item
            breakdown[bucket_key] = BreakdownItem(
                percentageSplit=PercentageType.from_decimal(percentage_split),
                fees=FeeStructure(
                    fixed=MoneyType.from_decimal(fixed_fee),
                    percentage=PercentageType.from_decimal(percentage_fee)
                )
            )
            
            logger.debug(f"Created bucket: {bucket_key} with {percentage_split:.4%} split")
        
        return breakdown
    
    def _generate_bucket_key(self, charge: TransactionCharge) -> str:
        """
        Generate the bucket key from charge type.
        Example: visaInPersonUkConsumerDebit
        """
        ct = charge.charge_type
        
        # Special handling for OTHER scheme
        scheme = ct.scheme.value
        if scheme == "other" and ct.scheme_other_description:
            # Use the actual scheme name if available
            scheme = ct.scheme_other_description.lower().replace(" ", "")
        
        # Proper capitalization for each part
        # Presence: inPerson -> InPerson, online -> Online
        if ct.presence.value == "inPerson":
            presence = "InPerson"
        elif ct.presence.value == "online":
            presence = "Online"
        else:
            presence = ct.presence.value.capitalize()
        
        # Region: uk -> Uk, eea -> Eea, international -> International
        if ct.region.value == "uk":
            region = "Uk"
        elif ct.region.value == "eea":
            region = "Eea"
        elif ct.region.value == "international":
            region = "International"
        else:
            region = ct.region.value.capitalize()
        
        # Realm and CardType: just capitalize
        realm = ct.realm.value.capitalize()
        card_type = ct.cardType.value.capitalize()
        
        key = f"{scheme}{presence}{region}{realm}{card_type}"
        return key
    
    def _parse_rate_structure(self, rate_str: str) -> Tuple[Decimal, Decimal]:
        """
        Parse rate string like '1.53% + £0.03' into (percentage, fixed).
        
        Examples:
        - "1.53%" -> (0.0153, 0)
        - "1.53% + £0.03" -> (0.0153, 0.03)
        - "£0.03" -> (0, 0.03)
        """
        percentage = Decimal(0)
        fixed = Decimal(0)
        
        try:
            # Extract percentage (looking for X% or X.XX%)
            percent_match = re.search(r'([\d.]+)\s*%', rate_str)
            if percent_match:
                percentage = Decimal(percent_match.group(1)) / 100
            
            # Extract fixed amount (looking for £X or £X.XX)
            pound_match = re.search(r'£\s*([\d.]+)', rate_str)
            if pound_match:
                fixed = Decimal(pound_match.group(1))
            else:
                # Try pence format (e.g., "3p" or "0.03p")
                pence_match = re.search(r'([\d.]+)\s*p(?:ence)?', rate_str, re.IGNORECASE)
                if pence_match:
                    fixed = Decimal(pence_match.group(1)) / 100
        
        except Exception as e:
            self.warnings.append(f"Could not parse rate '{rate_str}': {e}")
            logger.warning(f"Rate parsing error for '{rate_str}': {e}")
        
        return percentage, fixed
    
    def _parse_money(self, value: str) -> Decimal:
        """Parse money string to Decimal, handling various formats"""
        if not value:
            return Decimal(0)
        
        try:
            # Remove currency symbols, commas, and whitespace
            cleaned = re.sub(r'[£$€\s,]', '', value)
            return Decimal(cleaned)
        except Exception as e:
            self.warnings.append(f"Could not parse money value '{value}': {e}")
            return Decimal(0)
    
    def _parse_money_to_type(self, value: str) -> Optional[MoneyType]:
        """Parse money string directly to MoneyType"""
        amount = self._parse_money(value)
        return MoneyType.from_decimal(amount) if amount > 0 else None


# Test function to verify transformer works
def test_transformer():
    """Test the transformer with sample data"""
    import json
    from schemas.extraction_schema import ExtractedStatement
    
    # Load the extracted data from your test
    with open("tests/tests_outputs/llm_extraction_output.json", "r") as f:
        data = json.load(f)
    
    # Convert to Pydantic model
    extracted = ExtractedStatement(**data)
    
    # Transform
    transformer = StatementTransformer()
    result = transformer.transform(extracted, upload_id="TEST-123")
    
    # Output the result
    output = result.model_dump(by_alias=True)
    
    print(json.dumps(output, indent=2))
    
    # Save to file
    with open("tests/tests_outputs/transformed_output.json", "w") as f:
        json.dump(output, f, indent=2)
    
    print(f"\nTransformed {len(result.breakdown)} transaction types")
    print(f"Monthly Revenue: {result.monthlyRevenue.decimal}")
    print(f"Monthly Charges: {result.monthlyCharges.decimal}")
    print(f"Average Transaction: {result.averageTransactionAmount.decimal}")


if __name__ == "__main__":
    test_transformer()