from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from schemas.extraction_schema import ExtractedStatement, Scheme, Realm, CardType, Presence, Region
from typing import Optional, Dict, Any
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
    Handles all mappings from various PDF formats to our canonical schema.
    """
    
    # Complete mapping dictionaries for reference
    SCHEME_MAPPINGS = {
        "visa": Scheme.VISA,
        "mastercard": Scheme.MASTERCARD,
        "master card": Scheme.MASTERCARD,
        "mc": Scheme.MASTERCARD,
        "american express": Scheme.AMEX,
        "amex": Scheme.AMEX,
        "maestro": Scheme.MAESTRO,
        "diners": Scheme.DINERS,
        "diners club": Scheme.DINERS,
        "discover": Scheme.DISCOVER,
        "jcb": Scheme.JCB,
        "japanese credit bureau": Scheme.JCB,
        # ASSUMPTION: V Pay is actually Visa (it is a visa product)
        "v pay": Scheme.VISA,
        "vpay": Scheme.VISA,
    }
    
    REALM_MAPPINGS = {
        # Consumer mappings
        "personal": Realm.CONSUMER,
        "private": Realm.CONSUMER,
        "consumer": Realm.CONSUMER,
        "": Realm.CONSUMER,  # Default/blank
        # Commercial mappings
        "business": Realm.COMMERCIAL,
        "corporate": Realm.COMMERCIAL,
        "purchasing": Realm.COMMERCIAL,
        "fleet": Realm.COMMERCIAL,
        "commercial": Realm.COMMERCIAL,
    }
    
    REGION_MAPPINGS = {
        # UK/Domestic
        "": Region.UK,  # Default/blank
        "uk": Region.UK,
        "gb": Region.UK,
        "domestic": Region.UK,
        "united kingdom": Region.UK,
        # EEA
        "eea": Region.EEA,
        "eu": Region.EEA,
        "europe": Region.EEA,
        "european": Region.EEA,
        # International
        "international": Region.INTERNATIONAL,
        "intl": Region.INTERNATIONAL,
        "non-qualifying": Region.INTERNATIONAL,
        "non qualifying": Region.INTERNATIONAL,
        "non-eea": Region.INTERNATIONAL,
    }
    
    PRESENCE_MAPPINGS = {
        # In Person
        "": Presence.IN_PERSON,  # Default
        "terminal": Presence.IN_PERSON,
        "chip": Presence.IN_PERSON,
        "chip & pin": Presence.IN_PERSON,
        "face to face": Presence.IN_PERSON,
        "in person": Presence.IN_PERSON,
        "card machine": Presence.IN_PERSON,
        # Online
        "cnp": Presence.ONLINE,
        "card not present": Presence.ONLINE,
        "web": Presence.ONLINE,
        "online": Presence.ONLINE,
        "phone": Presence.ONLINE,
        "moto": Presence.ONLINE,
        "ecom": Presence.ONLINE,
        "e-commerce": Presence.ONLINE,
    }
    
    CARD_TYPE_MAPPINGS = {
        "debit": CardType.DEBIT,
        "prepaid": CardType.DEBIT,
        "credit": CardType.CREDIT,
        "charge": CardType.CREDIT,
    }
    
    def __init__(self, model: str = "gpt-4-turbo-preview", temperature: float = 0):
        """
        Initialize the extractor.
        
        Args:
            model: OpenAI model to use (gpt-4-turbo-preview recommended for accuracy)
            temperature: 0 for deterministic extraction
        """
        self.model = model
        self.temperature = temperature
        
        # Initialize LLM with structured output
        self.llm = ChatOpenAI(
            model=self.model,
            temperature=self.temperature,
            api_key=os.getenv("OPENAI_API_KEY")
        ).with_structured_output(ExtractedStatement)
        
        # Create the extraction prompt with all mappings
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", self._get_system_prompt()),
            ("human", "Extract all payment transaction data from this merchant statement:\n\n{statement_text}")
        ])
        
        # Also set up a parser for error handling
        self.parser = PydanticOutputParser(pydantic_object=ExtractedStatement)
    
    def _get_system_prompt(self) -> str:
        """Build the comprehensive system prompt with all mapping rules."""
        return """You are a specialist in extracting structured data from merchant payment statements.
        
Your task is to extract transaction charge data into a canonical format, normalizing inconsistent terminology.

CRITICAL EXTRACTION RULES:

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
   - "Credit", "Charge Card" → "credit"

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
- The "reasoning" field should briefly explain your categorization logic
- Capture charge rates exactly as shown (e.g., "1.53% + £0.03")
- Include currency symbols in monetary values (e.g., "£1,234.56")
- Use YYYY-MM-DD format for dates
- For authorisation_fee, look for "Authorisation Fee" or "Auth Fee" in the statement
- statement_period should capture the date range (e.g., "01 May to 31 May 2024")

VALIDATION FIELDS:
- total_value: Extract the statement's total transaction value if shown (for validation)
- total_charges: Extract the statement's total charges if shown (for validation)

Remember: If you encounter an unrecognized payment scheme, set scheme to "other" and MUST provide the actual scheme name in scheme_other_description."""
    
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
            
        Raises:
            Exception if extraction fails after retries
        """
        try:
            logger.info(f"Extracting data using {self.model}")
            
            # Create the chain
            chain = self.prompt | self.llm
            
            # Invoke with the statement text
            result = chain.invoke({
                "statement_text": statement_text[:50000]  # Limit to ~12k tokens
            })
            
            logger.info(f"Successfully extracted {len(result.transaction_charges)} transaction charges")
            
            # Validate the extraction
            self._validate_extraction(result)
            
            return result
            
        except Exception as e:
            logger.error(f"Extraction failed: {str(e)}")
            raise
    
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
        try:
            with open(pdf_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                num_pages = len(pdf_reader.pages)
                logger.info(f"PDF has {num_pages} pages")
                
                for i, page in enumerate(pdf_reader.pages):
                    page_text = page.extract_text()
                    text += page_text
                    logger.debug(f"Page {i+1}: extracted {len(page_text)} characters")
                    
        except Exception as e:
            logger.error(f"Failed to read PDF: {e}")
            raise
            
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
        other_schemes = [
            t for t in result.transaction_charges 
            if t.charge_type.scheme == Scheme.OTHER
        ]
        if other_schemes:
            for t in other_schemes:
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