from datetime import date
from decimal import Decimal
from typing import Dict, Optional, Any, List

from pydantic import BaseModel, Field, ConfigDict


class MoneyType(BaseModel):
    """Represents money in the specific format required."""
    # Allow using field names (decimal=...) as well as aliases ("#decimal")
    model_config = ConfigDict(populate_by_name=True)

    type_: str = Field("Currency", alias="___type")
    constructedType: str = Field("pounds", alias="#constructedType")
    decimal: str = Field(alias="#decimal")

    @classmethod
    def from_decimal(cls, amount: Decimal) -> "MoneyType":
        # Because populate_by_name=True, this works: decimal=...
        return cls(decimal=str(amount))


class PercentageType(BaseModel):
    """Represents a percentage in the specific format required."""
    # Same trick here
    model_config = ConfigDict(populate_by_name=True)

    type_: str = Field("Percentage", alias="___type")
    decimal: str = Field(alias="#decimal")

    @classmethod
    def from_decimal(cls, amount: Decimal) -> "PercentageType":
        return cls(decimal=str(amount))


class FeeStructure(BaseModel):
    """Fee structure with fixed and percentage components."""
    fixed: MoneyType
    percentage: PercentageType

class BreakdownItem(BaseModel):
    """Individual breakdown bucket (e.g. visa / consumer / debit / inPerson / uk)."""
    percentageSplit: PercentageType
    fees: List[FeeStructure]  # We show all the Fee structures we may encounter for one bucket

class NewMerchantStatement(BaseModel):
    """Output format for the transformed merchant statement."""
    merchantStatementUploadId: str
    merchantName: str
    merchantId: Optional[str]
    paymentProvider: str

    statementDate: str  # or `date` if you prefer
    statementPeriod: Optional[str]

    monthlyRevenue: MoneyType
    monthlyCharges: MoneyType
    averageTransactionAmount: MoneyType

    breakdown: Dict[str, BreakdownItem] = Field(
        description=(
                "Mapping from canonical bucket key to its split and fee structures. "
                "Note: fees is a list as aggregated buckets may have multiple rates."
            )
        )

    authorisationFee: Optional[MoneyType]
    registeredCompany: Optional[bool]
    merchantCategoryCode: Optional[str]

    # Metadata for tracking / debugging extraction and transformation
    extractionMetadata: Dict[str, Any] = Field(default_factory=dict)
