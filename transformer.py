from typing import Dict, List, Optional, Tuple, Any
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
        
        monthly_revenue = self._calculate_monthly_revenue(extracted.transaction_charges)
        monthly_charges = self._calculate_monthly_charges(extracted.transaction_charges)
        avg_transaction = self._calculate_average_transaction(extracted.transaction_charges)
        

        breakdown, bucket_count = self._create_breakdown(extracted.transaction_charges, monthly_revenue)
        

        auth_fee = None
        if extracted.authorisation_fee:
            auth_fee = self._parse_money_to_type(extracted.authorisation_fee)
        
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
                "totalTransactionRows": len(extracted.transaction_charges),  # Original rows
                "uniqueBuckets": bucket_count,  # After aggregation (because note: some rows may end up in the same bucket, more info in  _create_breakdown())
                "errors": self.errors,
                "warnings": self.warnings,
                "extractedTotals": {
                    "value": extracted.total_value,
                    "charges": extracted.total_charges
                }
            }
        )
        
        logger.info(f"Transformation complete: {len(extracted.transaction_charges)} rows -> {bucket_count} unique buckets")
        return result
    
    def _calculate_monthly_revenue(self, charges: List[TransactionCharge]) -> Decimal:
        """Calculate total transaction value across all charges"""
        total = Decimal(0)
        for charge in charges:
            value = self._parse_money(charge.transactions_value)
            total += value
        return total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    
    def _calculate_monthly_charges(self, charges: List[TransactionCharge]) -> Decimal:
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
    ) -> Tuple[Dict[str, BreakdownItem], int]:
        """
        Create breakdown buckets with percentage splits and fee structures.
        IMPORTANT: Aggregates duplicate buckets when different descriptions map to the same key.
        
        Example aggregation from our data:
        - "Mastercard Business" (£98.55, 2.22% rate)
        - "Mastercard Corporate and Purchasing" (£62.05, 2.22% rate)
        Both map to -> "mastercardInPersonUkCommercialCredit"
        Combined value: £160.60 (1.41% of total)
        
        Returns:
            Tuple of (breakdown dict, count of unique buckets)
            e.g., (12 transaction rows -> 11 unique buckets)
        """
        # First pass: aggregate by bucket key
        bucket_aggregates = {}
        
        for charge in charges:
            bucket_key = self._generate_bucket_key(charge)
            
            if bucket_key not in bucket_aggregates:
                bucket_aggregates[bucket_key] = {
                    'total_value': Decimal(0),
                    'total_charges': Decimal(0),
                    'transaction_count': 0,
                    'charges': [],
                    'rates': set()  # Track unique rates
                }
            
            # Aggregate values
            charge_value = self._parse_money(charge.transactions_value)
            charge_total = self._parse_money(charge.charge_total)
            
            bucket_aggregates[bucket_key]['total_value'] += charge_value
            bucket_aggregates[bucket_key]['total_charges'] += charge_total
            bucket_aggregates[bucket_key]['transaction_count'] += charge.number_of_transactions
            bucket_aggregates[bucket_key]['charges'].append(charge)
            bucket_aggregates[bucket_key]['rates'].add(charge.charge_rate)
        
        # Second pass: create breakdown items
        breakdown = {}
        
        for bucket_key, aggregate in bucket_aggregates.items():
            percentage_split = Decimal(0)
            if total_revenue > 0:
                percentage_split = (aggregate['total_value'] / total_revenue)
                percentage_split = percentage_split.quantize(
                    Decimal('0.00000001'), rounding=ROUND_HALF_UP
                )
            
            # Create a FeeStructure for each unique rate
            fee_structures = []
            for rate_str in sorted(aggregate['rates']):  # Sort for consistent output
                percentage_fee, fixed_fee = self._parse_rate_structure(rate_str)
                fee_structures.append(
                    FeeStructure(
                        fixed=MoneyType.from_decimal(fixed_fee),
                        percentage=PercentageType.from_decimal(percentage_fee)
                    )
                )
            
            # Log if we found multiple rates
            if len(aggregate['rates']) > 1:
                logger.info(
                    f"Bucket {bucket_key} has {len(aggregate['rates'])} different rates: "
                    f"{sorted(aggregate['rates'])}"
                )
            
            breakdown[bucket_key] = BreakdownItem(
                percentageSplit=PercentageType.from_decimal(percentage_split),
                fees=fee_structures
            )
            
            # Log aggregated buckets
            if len(aggregate['charges']) > 1:
                descriptions = [c.charge_type_description for c in aggregate['charges']]
                logger.info(
                    f"Bucket {bucket_key}: aggregated {len(aggregate['charges'])} rows: {descriptions}"
                )
        
        return breakdown, len(breakdown)
    
    def _generate_bucket_key(self, charge: TransactionCharge) -> str:
        """Generate bucket key: schemePresenceRegionRealmCardType"""
        ct = charge.charge_type
        
        # Handle "other" scheme
        scheme = ct.scheme.value
        if scheme == "other" and ct.scheme_other_description:
            scheme = ct.scheme_other_description.lower().replace(" ", "")
        
        # Special case for inPerson (needs camelCase preserved)
        presence = "InPerson" if ct.presence.value == "inPerson" else ct.presence.value.capitalize()
        
        # Everything else uses capitalize() perfectly
        region = ct.region.value.capitalize()
        realm = ct.realm.value.capitalize() 
        card_type = ct.cardType.value.capitalize()

        return f"{scheme}{presence}{region}{realm}{card_type}"
    
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

