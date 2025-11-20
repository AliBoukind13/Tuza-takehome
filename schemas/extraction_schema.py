from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field, model_validator
from typing import Self

# Enums:
# Forces the LLM to normalize inconsistent PDF terms (like "GB" vs "UK")
# into a single "Canonical" format
# 
# Note: Most enums below are straightforward and directly derived from the spec example
# (e.g., Scheme, CardType, Realm, Presence all had clear examples).
# The only enum requiring investigation was Region. The spec only showed "uk," so we had to
# analyze the examples and do some research to infer the other categories. More details can be found
# in the Region's docstring 


class Scheme(str, Enum):
    """
    The payment network brand.
    
    Rationale:
    We capture the specific schemes listed in the provided Lloyds and Worldpay summary tables.
    
    Examples from files:
    - MAESTRO: Legacy debit network, found in DojoRedacted5.pdf ("Maestro (inc. prepaid)").
    - DINERS / DISCOVER: Niche schemes listed in WorldpayRedacted2.pdf under "Payment brands accepted".
    - VISA / MASTERCARD: The standard majority.

    Design Choice - OTHER:
    We include an "OTHER" category as a fallback for:
    1. Future-proofing against new payment networks
    2. Regional schemes we haven't encountered
    3. Preventing LLM errors when encountering unexpected schemes
    Without this catch-all, the LLM might hallucinate or force incorrect categorization.
    """
    VISA = "visa"
    MASTERCARD = "mastercard"
    AMEX = "amex"
    MAESTRO = "maestro"
    DINERS = "diners"
    DISCOVER = "discover"
    JCB = "jcb"
    OTHER = "other"

class Realm(str, Enum):
    """
    Distinguishes between Personal and Business cards, which carry different interchange fee caps.
    
    Rationale:
    Merchants pay significantly higher fees for business cards.
    
    Mapping Examples:
    - CONSUMER: Maps from "Personal", "Private", or default rows without labels.
      (e.g. "Visa Debit" in DojoRedacted1 implies Consumer).
      
    - COMMERCIAL: Maps from "Business", "Corporate", "Purchasing", "Fleet".
      (e.g. "Mastercard Corporate and Purchasing" in DojoRedacted2.pdf).
      (e.g. "Business Debit" in LloydsRedacted1.pdf).
    """
    CONSUMER = "consumer"     # Maps "Personal", "Private"
    COMMERCIAL = "commercial" # Maps "Business", "Corporate", "Purchasing"

class CardType(str, Enum):
    """
    The funding mechanism, which dictates the fee floor.
    
    Mapping Examples:
    - DEBIT: Maps from "Debit", "Prepaid", "V Pay", "Maestro".
      (e.g. "Visa Debit (inc. prepaid)" in DojoRedacted6.pdf).
      
    - CREDIT: Maps from "Credit" or "Charge Card".
      (e.g. "Mastercard Credit" in WorldpayRedacted1.pdf).
    """
    DEBIT = "debit"           # Maps "Prepaid", "Debit"
    CREDIT = "credit"         # Maps "Credit"

class Presence(str, Enum):
    """
    The capture method, distinguishing Card Present (CP) from Cardholder Not Present (CNP).
    
    Rationale:
    CNP transactions carry higher fraud risk and thus higher fees.
    
    Mapping Examples:
    - IN_PERSON: Maps from "Terminal", "Chip & Pin", "Magstripe", "Face to Face".
      (e.g. "In person" column in WorldpayRedacted2.pdf).
      
    - ONLINE: Maps from "CNP", "Web", "E-com", "Phone", "MOTO".
      (e.g. "Online/phone" row in LloydsRedacted1.pdf).
      (e.g. "Visa: Debit: CNP" in WorldpayRedacted1.pdf).
    """
    IN_PERSON = "inPerson"    # Maps "Terminal", "Chip", "Card Machine"
    ONLINE = "online"         # Maps "CNP", "Web", "Phone"

class Region(str, Enum):
    """
    Design Choice:
    Based on our analysis of the provided statement examples (Dojo, Worldpay, Lloyds), we investigated and found 
    that transactions can be consistently divided into 3 regional buckets to align with Interchange Fee Regulation (IFR).
    
    This structure allows us to map inconsistent terms into a standardized regulatory framework:
    
    - UK: The baseline for domestic cards. If a line item doesn't specify a region (e.g. just "Visa Debit" in Dojo files), it implies UK/Domestic.
    
    - EEA: Distinct regulatory cap post-Brexit.
      (e.g. "Visa Debit (inc. prepaid), EEA" in DojoRedacted5.pdf).
    
    - INTERNATIONAL: Uncapped/Higher fees.
      (e.g. "Visa Credit, International" in DojoRedacted2.pdf).
      (e.g. "Non-Qualifying" or "Non-EEA" in DojoRedacted5.pdf).
    """

    UK = "uk"                 # Maps "GB", "Domestic", "United Kingdom"
    EEA = "eea"               # Maps "Europe", "EU"
    INTERNATIONAL = "international" # Maps "Intl", "Non-Qualifying"

# regarding the Maps comments, we'll feed these examples in the LLM's prompts to help the model

# Nested components

class BusinessAddress(BaseModel):
    line1: Optional[str] = Field(None, description="Primary street address")
    line2: Optional[str] = Field(None, description="Secondary address line (County/Region)")
    line3: Optional[str] = Field(None, description="Extra address info")
    city: Optional[str] = Field(None, description="City or Town")
    postcode: Optional[str] = Field(None, description="Postal Code")
    country: Optional[str] = Field(None, description="Full Country Name")

class CanonicalChargeType(BaseModel):
    """
    The strict classification object.
    """
    scheme: Scheme
    realm: Realm
    cardType: CardType
    presence: Presence
    region: Region

    # design choice: we add a Field to capture the name if 'OTHER' is selected for Scheme
    scheme_other_description: Optional[str] = Field(
        None, 
        description="If scheme is OTHER, specify name (e.g. 'UnionPay'). Otherwise null."
    )
    @model_validator(mode='after')
    def validate_other(self) -> Self:
        # If the LLM picks OTHER for Scheme, it MUST provide a description
        if self.scheme == Scheme.OTHER and not self.scheme_other_description:
            raise ValueError("Description required for OTHER scheme")
        
        # Cleanup: If it picks VISA/AMEX/etc, force description to None
        if self.scheme != Scheme.OTHER and self.scheme_other_description:
            self.scheme_other_description = None
            
        return self

class TransactionCharge(BaseModel):
    """
    Represents a single row of aggregated fees.
    """
    # CRITICAL FEATURE: Chain of Thought
    # Forces the LLM to explain its choice before committing to an Enum.
    # We added this to make sure we can check the model's logic and adjust if needed
    reasoning: str= Field(
        None, 
        description="Brief reasoning for the classification (e.g. 'Found keyword Corporate -> Commercial')"
    )


    # 
    charge_type_description: str = Field(
        ..., 
        alias="chargeTypeDescription", 
        description="Original row text from PDF (e.g. 'Visa Debit')"
    )
    
    charge_type: CanonicalChargeType = Field(..., alias="chargeType")
    
    # We use strings for Rates to handle complex non-float values like "0.56% + 2p"
    charge_rate: str = Field(
        ..., 
        alias="chargeRate", 
        description="Fee rate as string (e.g. '0.56%' or '1.2% + 5p'). Capture fixed fees if present."
        # We'll make sure to handle both in our json output
    )
    
    number_of_transactions: int = Field(..., alias="numberOfTransactions")
    
    # We use strings for Money to prevent LLM rounding errors.
    # The Transformer logic (in Python) will strip '£' and ',' later.
    charge_total: str = Field(
        ..., 
        alias="chargeTotal", 
        description="Total fee amount (e.g. '£32.66')"
    )
    transactions_value: str = Field(
        ..., 
        alias="transactionsValue", 
        description="Total transaction volume (e.g. '£5831.40')"
    )

# The Root Object

class ExtractedStatement(BaseModel):
    """
    Canonical statement extraction format for LLM output.
    """
    business_name: str = Field(..., alias="businessName")
    business_address: Optional[BusinessAddress] = Field(None, alias="businessAddress")
    
    statement_date: str = Field(
        ..., 
        alias="statementDate", 
        description="Date in YYYY-MM-DD format"
    )
    
    authorisation_fee: Optional[str] = Field(
        None, 
        alias="authorisationFee",
        description="Auth fee with currency symbol (e.g. '£0.02')"
    )
    registered_company: bool = Field(
        True, 
        alias="registeredCompany",
        description="True if Limited/Ltd/PLC" # need to be double checked and adapted
    )
    merchant_category_code: Optional[str] = Field(
        None, 
        alias="merchantCategoryCode"
    )
    
    # The Core Data
    transaction_charges: List[TransactionCharge] = Field(..., alias="transactionCharges")
    
    ## Optional Summary Fields (Good for debugging/validation):

    # For statement_period:
    # Note: The provided examples all have ~30-31 day periods, making monthly calculations straightforward.
    #  This is mainly for future cases where the periods maybe more misaligned with the monthly calculations
    #  In the future, if we encounter non-monthly statements (weekly/quarterly), we need to add logic that
    #  pro-rate the calculations to monthly equivalents
  
    statement_period: Optional[str] = Field(
        None,
        alias="statementPeriod", 
        description="Period covered (e.g. '25 Oct to 24 Nov 2023')"
    )

    ## for total_value and total_charges:
    # We extract these totals from the PDF header/summary for validation purposes only.
    # The final output will recalculate from transaction_charges.

    # These optional fields will be used for validation: If Sum(transaction_charges.transactions_value) != total_value, 
    # we know the LLM likely missed rows (e.g., only extracted page 1 of a multi-page statement).
    # This discrepancy would trigger a warning.
    total_value: Optional[str] = Field(
        None,
        alias="totalValue",
        description="Total value of all transactions with symbol"
    )
    total_charges: Optional[str] = Field(
        None,
        alias="totalCharges",
        description="Total of all charges with symbol"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "businessName": "The Claydon Hair Company Limited",
                "statementDate": "2025-10-22",
                "transactionCharges": [
                    {
                        "reasoning": "Row says 'Visa Debit', implies Consumer/UK/InPerson",
                        "chargeTypeDescription": "Debit cards",
                        "chargeType": {
                            "scheme": "visa",
                            "realm": "consumer",
                            "cardType": "debit",
                            "presence": "inPerson",
                            "region": "uk",
                            "scheme_other_description": None
                        },
                        "chargeRate": "0.56%",
                        "numberOfTransactions": 159,
                        "chargeTotal": "£32.66",
                        "transactionsValue": "£5831.40"
                    },
                    {
                        "reasoning": "Found 'V Pay' which maps to OTHER",
                        "chargeTypeDescription": "V Pay transactions",
                        "chargeType": {
                            "scheme": "other",
                            "realm": "consumer",
                            "cardType": "debit",
                            "presence": "inPerson",
                            "region": "eea",
                            "scheme_other_description": "BMCE" 
                        },
                        "chargeRate": "0.35%",
                        "numberOfTransactions": 5,
                        "chargeTotal": "£1.50",
                        "transactionsValue": "£425.00"
                    }
                ]
            }
        }
