# schemas/output_schema.py
from pydantic import BaseModel, Field
from typing import Dict, Optional
from decimal import Decimal

class MoneyType(BaseModel):
    """Represents money in the specific format required"""
    type_field: str = Field(alias="___type", default="Currency")
    constructed_type: str = Field(alias="#constructedType", default="pounds")
    decimal_value: str = Field(alias="#decimal")
    
    @classmethod
    def from_decimal(cls, amount: Decimal):
        return cls(decimal_value=str(amount))

class PercentageType(BaseModel):
    """Represents percentage in the specific format required"""
    type_field: str = Field(alias="___type", default="Percentage")
    decimal_value: str = Field(alias="#decimal")
    
    @classmethod
    def from_decimal(cls, amount: Decimal):
        return cls(decimal_value=str(amount))

class FeeStructure(BaseModel):
    """Fee structure with fixed and percentage components"""
    fixed: MoneyType
    percentage: PercentageType

class BreakdownItem(BaseModel):
    """Individual breakdown bucket"""
    percentageSplit: PercentageType
    fees: FeeStructure

class NewMerchantStatement(BaseModel):
    """Output format for the transformed statement"""
    merchantStatementUploadId: str
    merchantName: str
    merchantId: Optional[str]
    paymentProvider: str
    statementDate: str
    statementPeriod: Optional[str]
    
    monthlyRevenue: MoneyType
    monthlyCharges: MoneyType
    averageTransactionAmount: MoneyType
    
    breakdown: Dict[str, BreakdownItem]
    
    authorisationFee: Optional[MoneyType]
    registeredCompany: Optional[bool]
    merchantCategoryCode: Optional[str]
    
    # Metadata for tracking
    extractionMetadata: Optional[Dict] = Field(default_factory=dict)