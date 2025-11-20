from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from schemas.extraction_schema import ExtractedStatement, Scheme
from typing import Optional
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
    Production-ready statement extractor using OpenAI GPT-4.
    Extracts transaction data from PDF statements into canonical format.
    """
    
    def __init__(self, model: str = "gpt-4-turbo-preview", temperature: float = 0):
        """
        Initialize the extractor.
        
        Args:
            model: OpenAI model to use
            temperature: 0 for deterministic extraction
        """
        self.model = model
        self.temperature = temperature
        
        # Initialize LLM with structured output
        self.llm = ChatOpenAI(
            model=self.model,
            temperature=self.temperature,
            api_key=os.getenv("OPENAI_API_KEY")
        ).with_structured_output(ExtractedStatement, method="function_calling")
        
        # Create the extraction prompt
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", self._get_system_prompt()),
            ("human", "Extract all payment transaction data from this merchant statement:\n\n{statement_text}")
        ])
    
    def _get_system_prompt(self) -> str:
        """Build the comprehensive system prompt with all mapping rules."""
        return """You are a specialist in extracting structured data from merchant payment statements.

Your task is to extract transaction charge data into a canonical format, normalizing inconsistent terminology.

CRITICAL EXTRACTION RULES FOR BUSINESS IDENTIFICATION:

1. PAYMENT PROVIDER (who issued the statement):
   - Look for: Dojo, Paymentsense, Worldpay, Lloyds, or other processor names
   - Usually found in header/footer or company branding
   - This is the company processing the payments
   - Examples: Dojo/Worldpay/Lloyd

NOTE: FOR 2. AND 3.: By "BUSINESS" we mean the merchant who accepts card payments and receives this statement, 
NOT the payment processing company (Dojo/Worldpay/Lloyds).

2. BUSINESS NAME:
   - The business being charged the fees
   - Look for: "Statement for:", "Merchant:", "Trading as:"
   - NOT the payment processor's name
   - If cannot determine, use "Unknown"

3. BUSINESS ADDRESS:
   - The merchant's business address, NOT the processor's office
   - Often near the merchant name at top of statement
   - If not found, leave as null

MAPPING RULES:

1. SCHEME MAPPINGS (payment network):
   - "Visa", "V Pay" → "visa"
   - "Mastercard", "Master Card", "MC" → "mastercard"
   - "American Express", "Amex" → "amex"
   - "Maestro" → "maestro"
   - "Diners", "Diners Club" → "diners"
   - "Discover" → "discover"
   - "JCB", "Japanese Credit Bureau" → "jcb"
   - Any unknown scheme → "other" (MUST provide scheme_other_description)

2. REALM MAPPINGS (personal vs business):
   - DEFAULT/BLANK → "consumer"
   - "Personal", "Private" → "consumer"
   - "Business", "Corporate", "Purchasing", "Fleet" → "commercial"
   
3. CARD TYPE MAPPINGS:
   - "Debit", "Prepaid" → "debit"
   - "Credit", "Charge Card", "Corporate", "Purchasing" → "credit"

4. PRESENCE MAPPINGS (how card was used):
   - DEFAULT/BLANK → "inPerson"
   - "Terminal", "Chip", "Chip & Pin", "Face to Face" → "inPerson"
   - "CNP", "Card Not Present", "Web", "Phone", "MOTO", "E-com" → "online"

5. REGION MAPPINGS (geographic):
   - DEFAULT/BLANK → "uk"
   - "GB", "Domestic", "United Kingdom" → "uk"
   - "EEA", "EU", "Europe" → "eea"
   - "International", "Intl", "Non-Qualifying", "Non-EEA" → "international"

EXTRACTION GUIDELINES:
- Extract EVERY transaction charge row from the statement
- The "reasoning" field MUST explain your categorization logic for each row
- Capture charge rates exactly as shown (e.g., "1.53% + £0.03")
- Include currency symbols in monetary values (e.g., "£1,234.56")
- Use YYYY-MM-DD format for dates
- For authorisation_fee, look for "Authorisation Fee" or "Auth Fee" in the statement
- statement_period should capture the date range (e.g., "01 May to 31 May 2024")
- total_value and total_charges: Extract statement totals if shown (for validation).
- Ignore secure transaction fees (do NOT include total_charges and do not count it as a transaction)
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
        
        # Create the chain
        chain = self.prompt | self.llm
        
        # Invoke with the statement text (limit to prevent token overflow)
        result = chain.invoke({
            "statement_text": statement_text[:50000]
        })
        
        logger.info(f"Successfully extracted {len(result.transaction_charges)} transaction charges")
        
        # Validate the extraction
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
        
        # Extract text from PDF
        text = self._read_pdf(pdf_path)
        
        if not text or len(text.strip()) < 100:
            raise ValueError(f"Could not extract sufficient text from {pdf_path}")
        
        logger.info(f"Extracted {len(text)} characters from PDF")
        
        # Extract structured data
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
                logger.debug(f"Page {i+1}: extracted {len(page_text)} characters")
                    
        return text
    
    def _validate_extraction(self, result: ExtractedStatement) -> None:
        """
        Perform additional validation on the extraction.
        
        Args:
            result: The extracted statement to validate
        """
        # Check if we have transaction charges
        if not result.transaction_charges:
            raise ValueError("No transaction charges extracted")
        
        # Validate totals if provided
        if result.total_value and result.total_charges:
            try:
                # Calculate sum from transaction charges
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
                
                # Check for major discrepancies (>5% difference)
                if abs(calculated_value - extracted_value) / extracted_value > 0.05:
                    logger.warning(
                        f"Value discrepancy: calculated £{calculated_value:.2f} "
                        f"vs extracted £{extracted_value:.2f}"
                    )
                    
                if abs(calculated_charges - extracted_charges) / extracted_charges > 0.05:
                    logger.warning(
                        f"Charges discrepancy: calculated £{calculated_charges:.2f} "
                        f"vs extracted £{extracted_charges:.2f}"
                    )
                    
            except (ValueError, AttributeError) as e:
                logger.warning(f"Could not validate totals: {e}")
        
        # Log scheme distribution
        schemes = [t.charge_type.scheme for t in result.transaction_charges]
        scheme_counts = {s: schemes.count(s) for s in set(schemes)}
        logger.info(f"Scheme distribution: {scheme_counts}")
        
        # Check for OTHER schemes
        for t in result.transaction_charges:
            if t.charge_type.scheme == Scheme.OTHER:
                if not t.charge_type.scheme_other_description:
                    raise ValueError(f"OTHER scheme without description: {t.charge_type_description}")
                logger.info(f"Found OTHER scheme: {t.charge_type.scheme_other_description}")


# Convenience function
def extract_statement(pdf_path: str, model: str = "gpt-4-turbo-preview") -> ExtractedStatement:
    """
    Quick extraction function.
    
    Args:
        pdf_path: Path to PDF file
        model: OpenAI model to use
        
    Returns:
        ExtractedStatement object
    """
    extractor = StatementExtractor(model=model)
    return extractor.extract_from_pdf(pdf_path)