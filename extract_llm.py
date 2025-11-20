from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from schemas.extraction_schema import ExtractedStatement
import os
from dotenv import load_dotenv
import PyPDF2
from tenacity import retry, stop_after_attempt, wait_exponential
import logging

load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class StatementExtractor:
    """
    Statement extractor class:
    Extracts transaction data from PDF statements into canonical format.
    """
    
    def __init__(self, model: str = "gpt-4-turbo-preview", temperature: float = 0):
        """
        Initialize the extractor.
        
        Args:
            model: OpenAI model to use
            temperature: default and recommended: 0 for deterministic extraction
        """
        self.model = model
        self.temperature = temperature
        
        self.llm = ChatOpenAI(
            model=self.model,
            temperature=self.temperature,
            api_key=os.getenv("OPENAI_API_KEY")
        ).with_structured_output(ExtractedStatement, method="function_calling")
        
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", self._get_system_prompt()),
            ("human", "Extract all payment transaction data from this merchant statement:\n\n{statement_text}")
        ])
    
    def _get_system_prompt(self) -> str:
        """Build the comprehensive system prompt."""
        return """You are a specialist in extracting structured data from merchant payment statements.

Your task is to extract transaction charge data into a canonical format, normalizing inconsistent terminology.

CRITICAL EXTRACTION RULES FOR BUSINESS IDENTIFICATION:

1. PAYMENT PROVIDER (who issued the statement):
   - Usually found in header/footer or company branding
   - This is the company processing the payments
   - Examples: Dojo/Worldpay/Lloyd

NOTE: FOR 2-6: By "BUSINESS" we mean the merchant who accepts card payments and receives this statement, 
NOT the payment processing company.

2. BUSINESS NAME:
   - The business being charged the fees
   - Look for: "Statement for:", "Merchant:", "Trading as:"
   - NOT the payment processor's name
   - If cannot determine, use "Unknown"

3. BUSINESS ID:
   - The unique identifier assigned by the payment processor
   - Look for: "Merchant ID:", "Merchant Number:", "MID:", "Merchant No:"
   - Often near business name or in statement header
   - If not found, leave as null

4. BUSINESS ADDRESS:
   - The merchant's business address, NOT the processor's office
   - Often near the merchant name at top of statement
   - If not found, leave as null

5. REGISTERED COMPANY STATUS:
   - Look for: "Limited", "Ltd", "PLC", "LLP" in the business name
   - True if any of these suffixes are present
   - False if explicitly stated as "Sole Trader" or "Partnership"
   - Null if cannot determine from the statement
   - Do NOT guess: only set to True/False if explicitly evident

6. MERCHANT CATEGORY CODE (MCC):
   - Look for: 4-digit code or "MCC" label
   - Often shown as "MCC: XXXX" or "Category: XXXX"
   - Common codes: 5812 (Restaurants), 5411 (Grocery), 7230 (Beauty/Barber)
   - If not present in statement, leave as null

7. STATEMENT DATE:
   - The date the statement was issued/generated
   - NOT the period covered (that's statement_period)
   - Format as YYYY-MM-DD

8. STATEMENT PERIOD:
   - The date range the statement covers
   - Look for: "Period:", "From...to", date ranges
   - Format example: "25 Oct to 24 Nov 2023"
   - Different from statement_date

9. AUTHORISATION FEE:
   - Look for: "Authorisation Fee", "Auth Fee", "Authorization Fee"
   - Include currency symbol (e.g., "£0.02")
   - This is usually a per-transaction fee
   - If not present, leave as null

10. TOTAL VALUE & TOTAL CHARGES:
   - total_value: Sum of all transaction values shown in statement summary
   - total_charges: Sum of all fees/charges shown in statement summary
   - Look for: "Total", "Sum", "Grand Total" sections
   - Include currency symbols
   - These are for validation only

MAPPING RULES:

1. SCHEME MAPPINGS (payment network):
   - "Visa", "V Pay" -> "visa"
   - "Mastercard", "Master Card", "MC" -> "mastercard"
   - "American Express", "Amex" -> "amex"
   - "Maestro" -> "maestro"
   - "Diners", "Diners Club" -> "diners"
   - "Discover" -> "discover"
   - "JCB", "Japanese Credit Bureau" -> "jcb"
   - Any unknown scheme -> "other" (MUST provide scheme_other_description)

2. REALM MAPPINGS (personal vs business):
   - DEFAULT/BLANK -> "consumer"
   - "Personal", "Private" -> "consumer"
   - "Business", "Corporate", "Purchasing", "Fleet" -> "commercial"
   
3. CARD TYPE MAPPINGS:
   - DEFAULT/BLANK -> "credit"
   - "Debit", "Prepaid" -> "debit"
   - "Credit", "Charge Card", "Corporate", "Purchasing" -> "credit"

4. PRESENCE MAPPINGS (how card was used):
   - DEFAULT/BLANK -> "inPerson"
   - "Terminal", "Chip", "Chip & Pin", "Face to Face" -> "inPerson"
   - "CNP", "Card Not Present", "Web", "Phone", "MOTO", "E-com" -> "online"

5. REGION MAPPINGS (geographic):
   - DEFAULT/BLANK -> "uk"
   - "GB", "Domestic", "United Kingdom" -> "uk"
   - "EEA", "EU", "Europe" -> "eea"
   - "International", "Intl", "Non-Qualifying", "Non-EEA" -> "international"

REASONING REQUIREMENTS:

The "reasoning" field is MANDATORY and must explain your decision process for EACH of the following classifications:

1. SCHEME: How did you identify the payment network?
   Example: "Found 'Mastercard' in description -> mastercard"
   Example: "Unknown scheme 'UnionPay' -> other"

2. REALM: Why consumer vs commercial?
   Example: "Contains 'Corporate' -> commercial"

3. CARD TYPE: How did you determine debit vs credit?
   Example: "Contains 'Debit' keyword -> debit"
   Example: "American Express is always credit -> credit"

4. PRESENCE: Why in-person vs online?
   Example: "Found 'CNP' -> online"

5. REGION: How did you determine the geographic region?
   Example: "Found 'Non-Qualifying' -> international"
   Example: "Found 'EEA' -> eea"

Include any ASSUMPTIONS made.

Format: complete explanation covering all 5 dimensions and any assumptions.
Example: "Scheme: 'Visa' keyword -> visa. Realm: No business terms -> consumer. Card type: 'Debit (inc. prepaid)' -> debit. Presence: No CNP terms -> inPerson (assumed). Region: 'Non-qualifying' maps to international)"

ADDITIONAL EXTRACTION GUIDELINES:
- Extract EVERY transaction charge row from the statement
- Capture charge rates exactly as shown (e.g., "1.53% + £0.03")
- Include currency symbols in monetary values (e.g., "£1,234.56")
- Use YYYY-MM-DD format for dates
- Ignore secure transaction fees (do NOT include it in total_charges and do not count it as a transaction)
""" 
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    def extract_from_text(self, statement_text: str) -> ExtractedStatement:
        """
        Extract structured data from statement text with retry logic.
        
        Args:
            statement_text: Raw text from PDF statement
            
        Returns:
            Validated ExtractedStatement object
        """
        logger.info(f"Extracting data using {self.model}")
        
        chain = self.prompt | self.llm
        
        result = chain.invoke({
            "statement_text": statement_text
        })
        
        logger.info(f"Successfully extracted {len(result.transaction_charges)} transaction charges")

        self._validate_extraction(result)
        
        return result
    
    def extract_from_pdf(self, pdf_path: str) -> ExtractedStatement:
        """
        Extract structured data from a PDF file.
        
        Args:
            pdf_path: Path to the PDF file
            
        Returns:
            Validated ExtractedStatement object
        """
        logger.info(f"Reading PDF: {pdf_path}")
        
        text = self._read_pdf(pdf_path)
        
        if not text:
            raise ValueError(f"Could not extract a text from {pdf_path}")
        
        return self.extract_from_text(text)
    
    def _read_pdf(self, pdf_path: str) -> str:
        """Read and extract text from PDF."""
        text = ""
        with open(pdf_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            num_pages = len(pdf_reader.pages)
            logger.info(f"PDF has {num_pages} pages")
            
            for i, page in enumerate(pdf_reader.pages):
                page_text = page.extract_text()
                text += page_text
                    
        return text
    
    def _validate_extraction(self, result: ExtractedStatement) -> None:
        """
        Validate that all transactions were captured by reconciling totals.
        
        This validation serves as a critical quality check to detect incomplete 
        extractions.
        
        The validation process:
        1. Sums all extracted transaction values and charges
        2. Compares against statement-provided totals (if available)
        3. Logs warnings if discrepancy exceeds 1% threshold
        
        Why 1% tolerance?
        - Exact matches are rare due to rounding differences
        - 1% catches material extraction failures while allowing minor variations
        
        Important notes:
        - Validation ONLY logs warnings, never fails the extraction
        - Statements with zero transactions are valid (inactive merchants)
        - Some statements don't provide totals (validation skipped)
        - Discrepancies might be legitimate (e.g., partial statement period)
        
        Args:
            result: The extracted statement to validate against itself
        """
        if not result.transaction_charges:
            logger.warning("No transaction charges found: statement may be for inactive period, or something is wrong")
            # here we don't raise an Exception because there's a small chance that the statement is about a period where the merchant was closed
        else:
            logger.info(f"Extracted {len(result.transaction_charges)} transaction charges")
    
        # Validate totals ONLY if total values and total charges provided
        if result.total_value and result.total_charges:
            try:
                # Calculate sum from transaction charges (for now we assume pounds currency only)
                calculated_value = sum(
                    float(t.transactions_value.replace('£', '').replace(',', ''))
                    for t in result.transaction_charges
                )
                calculated_charges = sum(
                    float(t.charge_total.replace('£', '').replace(',', ''))
                    for t in result.transaction_charges
                )
                
                # Parse extracted totals
                extracted_value = float(result.total_value.replace('£', '').replace(',', ''))
                extracted_charges = float(result.total_charges.replace('£', '').replace(',', ''))
                
                # Check for discrepancies (>1% difference) (in the future, we can pass the threshold as an argument)
                if abs(calculated_value - extracted_value) / extracted_value > 0.01:
                    logger.warning(
                        f"Value discrepancy: calculated £{calculated_value:.2f} "
                        f"vs extracted £{extracted_value:.2f}"
                    )
                    
                if abs(calculated_charges - extracted_charges) / extracted_charges > 0.01:
                    logger.warning(
                        f"Charges discrepancy: calculated £{calculated_charges:.2f} "
                        f"vs extracted £{extracted_charges:.2f}"
                    )
                    
            except (ValueError, AttributeError) as e:
                logger.warning(f"Could not validate totals: {e}")


def extract_statement(pdf_path: str, model: str = "gpt-4-turbo-preview") -> ExtractedStatement:
    """
    Extract structured transaction data from a merchant payment statement PDF.
    
    This is the primary entry point for the extraction pipeline. It handles the 
    complete workflow: PDF reading -> text extraction -> LLM processing -> validation.
    
    Args:
        pdf_path: Path to the merchant statement PDF file
        model: OpenAI model to use for extraction (default: gpt-4-turbo-preview)
        
    Returns:
        ExtractedStatement: Validated, structured data containing all transaction 
                           charges and merchant information
        
    Raises:
        ValueError: If PDF is unreadable or contains no transaction data
        ValidationError: If LLM output doesn't match expected schema
    """
    extractor = StatementExtractor(model=model)
    return extractor.extract_from_pdf(pdf_path)