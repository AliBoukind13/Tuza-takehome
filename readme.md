# Merchant Statement Processor

A service that extracts and transforms merchant payment statements (PDF or raw text) into structured JSON format (`NewMerchantStatement`)using LLM-powered extraction.

## Features
- Process PDF statements and raw text input
- Automatic fee calculation and transaction categorization
- REST API with single `/extract` endpoint
- Web interface

## Prerequisites (Important)

You can run the project either with Docker (recommended) or directly with Python.

- **Option A: Docker**
  - Docker & Docker Desktop installed

- **Option B: Local Python**
  - Python 3.11 or higher
  - pip package manager

- **Both options**
  - OpenAI API key with GPT-5 access

## Installation & Setup

1. **Clone the repository**
```bash
git clone https://github.com/AliBoukind13/Tuza-takehome.git
cd Tuza-takehome
```

2. **Set up environment variables**
```bash
echo "OPENAI_API_KEY=sk-your-api-key-here" > .env
```

### Option A:  Docker Setup (Recommended)
3. **Start the application**
```bash
docker-compose up -d --build
```

4. **Access the application**
- Web Interface: http://localhost:3000
- API Documentation: http://localhost:8000/docs

5. **WHEN FINISHED: Stop the application**
```bash
docker-compose down

# To remove everything including images:
docker-compose down --rmi all
```

### Option B: Local Python Setup

3. **Create virtual environment**
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

4. **Install dependencies**
```bash
pip install -r requirements.txt
```
5. **Start the services (requires 2 terminals)**

Terminal 1 - API Server:
```bash
python -m uvicorn api:app --reload
# Runs on http://localhost:8000
```

Terminal 2 - Frontend Server:
```bash
python -m http.server 3000
# Runs on http://localhost:3000
```

6. **Access the application**
- Web Interface: http://localhost:3000
- API Documentation: http://localhost:8000/docs

7. **Stop the application**
- Press `Ctrl+C` in both terminals

## Usage

### Web Interface
1. Navigate to http://localhost:3000
2. Choose input method:
   - **Upload PDF**: Drag & drop or click to browse
   - **Paste Text**: Switch to text mode and paste statement content
3. Enter a unique Upload ID (e.g., MERCHANT-001)
4. Click "Process Statement"
5. View results and download JSON

### API Endpoint
```bash
# With PDF file
curl -X POST "http://localhost:8000/extract" \
  -F "file=@statement.pdf" \
  -F "merchantStatementUploadId=MERCHANT-001"

# With raw text
curl -X POST "http://localhost:8000/extract" \
  -F "statementText=Your statement text here..." \
  -F "merchantStatementUploadId=MERCHANT-001"
```

### Port Conflicts
If ports 3000 or 8000 are in use:
```bash
# Find process using port
lsof -i :3000  # Mac/Linux
netstat -ano | findstr :3000  # Windows

# Kill process or change ports in docker-compose.yml
```

### API Key Issues
- Ensure your `.env` file contains: `OPENAI_API_KEY=sk-...`

## Project Structure
```
Tuza-takehome/
├── api.py                 # FastAPI application
├── extract_llm.py         # LLM extraction logic
├── transformer.py         # Data transformation from LLM output to  NewMerchantStatement
├── index.html          # Web interface
├── docker-compose.yml     # Docker configuration
├── Dockerfile            # Container definition
├── requirements.txt      # Python dependencies
├── .env                  # Environment variables (create this)
└── schemas/
    ├── extraction_schema.py
    └── output_schema.py
```

### End-to-end data flow

The codebase is structured around a clear separation of responsibilities:

1. Extraction (LLM)  
2. Transformation (deterministic Python)  
3. API orchestration  
4. Frontend UX

In practice, a request flows like this:

1. A merchant statement (PDF or raw text) is sent to the API or uploaded via the frontend.
2. The LLM converts the unstructured statement into a normalized `ExtractedStatement`.
3. The transformer converts `ExtractedStatement` into the final `NewMerchantStatement` expected by the spec.
4. The API returns `NewMerchantStatement` as JSON to the caller, and the frontend renders it nicely with a download option.

More concretely:

#### 1. LLM extraction: `extract_llm.py` + `schemas/extraction_schema.py`

- `extract_llm.py` implements the `StatementExtractor` class.
- It:
  - Reads PDFs (PyPDF2 with pdfplumber fallback) or accepts raw text.
  - Calls the OpenAI model with a structured-output schema.
  - Validates the response into an `ExtractedStatement` Pydantic model (from `schemas/extraction_schema.py`).

An example of the raw LLM extraction output (after validation) can be found in:

- `tests/tests_outputs/llm_extraction_output.json`

This JSON is exactly what `StatementTransformer` expects as input.

#### 2. Transformation: `transformer.py` + `schemas/output_schema.py`

- `transformer.py` contains the `StatementTransformer` class.
- It takes an `ExtractedStatement` and produces a `NewMerchantStatement` defined in `schemas/output_schema.py`.

Key responsibilities:

- Aggregate rows into canonical buckets (for example, `visaInPersonUkConsumerDebit`).
- Compute:
  - `monthlyRevenue`
  - `monthlyCharges`
  - `averageTransactionAmount`
- Build the breakdown (per-bucket percentage split and fee structures).
- Attach `extractionMetadata` (warnings, reconciliation totals, etc.).

An example of the final transformed output is available in:

- `tests/tests_outputs/transformation_output.json`

This file shows the exact shape of the JSON returned to API callers.

#### 3. API orchestration: `api.py`

- `api.py` exposes a single `/extract` endpoint using FastAPI.
- It:
  - Accepts either:
    - `file` (PDF upload), or
    - `statementText` (raw pasted text),
    - plus `merchantStatementUploadId`.
  - Chooses the right extraction path:
    - PDF → `StatementExtractor.extract_from_pdf(...)`
    - Text → `StatementExtractor.extract_from_text(...)`
  - Passes the resulting `ExtractedStatement` into `StatementTransformer.transform(...)`.
  - Returns the resulting `NewMerchantStatement` as JSON.

In other words, the API is just the orchestrator wiring together:

`raw input → ExtractedStatement → NewMerchantStatement → HTTP JSON response`.

#### 4. Frontend: `index.html`

- `index.html` is a simple static HTML/JS frontend served by `python -m http.server 3000`.
- It allows a user to:
  - Upload a PDF or paste raw statement text,
  - Enter a `merchantStatementUploadId`,
  - Call the `/extract` API,
  - View the resulting JSON,
  - Download the JSON result to a file.

Functionally, the frontend is just a thin UI over the same `/extract` endpoint described above.

This layout keeps the architecture simple and testable:

- Extraction logic and schema validation are isolated in `extract_llm.py` and `schemas/extraction_schema.py`.
- Transformation logic and financial calculations are isolated in `transformer.py` and `schemas/output_schema.py`.
- `api.py` wires everything together for programmatic use.
- `index.html` provides a human-friendly way to run the same pipeline.


## Extraction Schema Design Choices

Our extraction schema (ExtractedStatement) is built using Pydantic to ensure strict type validation and structure. While based on the example JSON provided in the challenge, we introduced several architectural deviations to improve reliability, auditability, and data integrity.

### 1. Explicit Entity Separation (merchant_name vs payment_provider)
The raw PDF contains information for two distinct entities: the Payment Processor (e.g., Lloyds, Dojo) and the Merchant (the client).
- Change: We renamed generic fields like businessName to merchant_name and added a specific payment_provider field.
- Reasoning: This prevents the LLM from confusing the bank's address with the merchant's address.
- Addition: We added merchant_id as an optional field. This serves as a critical secondary identifier if the merchant name is generic or missing.

### 2. "Chain of Thought" Extraction
We inject a mandatory reasoning field into every transaction row.
- Implementation: The LLM must explain its classification logic before selecting an Enum (e.g., "Found 'Corporate' in description -> Mapping to Realm.COMMERCIAL").
- Benefit: This technique significantly reduces hallucination rates and provides an audit trail for why a transaction was categorized a certain way.

### 3. Robust Categorization & Future-Proofing
We use strict Enums for categorization to normalize inconsistent terminology (e.g., mapping "GB", "Domestic", "United Kingdom" -> Region.UK).
- The OTHER Trapdoor: To prevent the extraction from crashing on novel payment schemes (e.g., UnionPay), we included a Scheme.OTHER option coupled with a mandatory scheme_other_description field.
- IFR-Aligned Regions: We derived three specific regional buckets (UK, EEA, and INTERNATIONAL) to align with Interchange Fee Regulations (IFR), rather than using a generic string field.

### 4. Handling Monetary Precision
- Design Choice: All monetary values (chargeTotal, transactionsValue) and rates (chargeRate) are extracted as Strings, not Floats.
- Reasoning:
  1. Floating Point Safety: Prevents standard floating-point math errors.
  2. Parsing Complexity: Charge rates often appear as complex strings (e.g., "1.53% + 0.03"). Extracting them as strings allows our Python transformer to handle the parsing logic deterministically.

### 5. Self-Validation Fields
We extract header-level totals (total_value, total_charges) in addition to the individual rows.
- Usage: These fields are used for a "Sanity Check" validation step.
- Logic: If Sum(transaction_rows) != total_value (within a 1% tolerance), the system logs a warning, indicating that the LLM may have missed a page or hallucinated a row.
- more details in `extract_llm.py`


## NewMerchantStatement & Transformation Logic

Our system separates the concern of **extraction** (LLM) from **transformation** (Python). While the LLM focuses on normalizing raw text into a flat list of transaction charges, the `StatementTransformer` class handles the complex logic of mapping these rows into the specific `NewMerchantStatement` format required by the specification.

### 1. Canonical Bucket Generation
To match the internal breakdown format (e.g., `"visaInPersonUkConsumerDebit"`), we generate composite keys by concatenating the normalized enum values from the extraction step:
`{scheme}{presence}{region}{realm}{cardType}`

This ensures consistency regardless of how the row was labeled in the original PDF (e.g., mapping both "Visa Debit" and "Visa Debit Secure" to the same canonical bucket).

### 2. Handling Rate Variance (Why `fees` is a list)
In the `NewMerchantStatement` schema, we defined the `fees` field as a list rather than a single object.
- **Reasoning:** While rare, it is possible for two different transaction rows (e.g., "Mastercard Business" and "Mastercard Corporate") to map to the **same** canonical bucket (e.g., `mastercardInPersonUkCommercialCredit`) but carry **different** rates.
- **Solution:** Instead of averaging the rates or overwriting them, we append all unique fee structures found for that bucket into the list. This ensures no granular pricing data is lost during aggregation. Post tasks can look at all the fees and decide to handle them the way they prefer (Please note, again, that this would be very rare: most payment types that fit in the same bucket should have very similar rates)

### 3. Observability & Metadata
To aid in debugging and data quality assurance, we injected an `extractionMetadata` object into the final response. This allows downstream systems to validate the integrity of the transformation without parsing the whole file again.

**Metadata includes:**
- `totalTransactionRows`: The count of raw rows extracted by the LLM.
- `uniqueBuckets`: The number of aggregated keys in the breakdown (helps identify high-collision aggregations).
- `extractedTotals`: The raw header totals from the PDF, used to validate calculated sums.
- `errors/warnings`: A collection of parsing issues (e.g., unparseable rates).

```json
"extractionMetadata": {
    "totalTransactionRows": 12,
    "uniqueBuckets": 11,
    "errors": [],
    "warnings": [],
    "extractedTotals": {
      "value": "£11,389.62",
      "charges": "£198.99"
    }
}
```

## Additional Assumptions, Caveats and Best Practices

This service makes several reasoned assumptions and tradeoffs to simplify the parsing of complex, inconsistent merchant statements while maintaining a strong commitment to correctness and auditability.

### I. LLM Categorization and Risk

| Assumption/Decision | Reasoning and Impact | Source/Code Reference |
| :--- | :--- | :--- |
| **Default Card Type (Risk Asymmetry)** | If the card type (Debit/Credit) is ambiguous, the system defaults to **Credit**. **Tradeoff:** Credit products generally have higher capped Interchange Fees. Defaulting to Credit creates a *conservative estimate* of the merchant's cost, preventing potential underestimation of their effective rate. | `extract_llm.py` |
| **Secure Fees Exclusion** | We explicitly instruct the LLM to **ignore secure transaction fees** (e.g., 3D Secure charges) in the extraction, as these are often not part of the core fee analysis. | `extract_llm.py` |
| **CanonicalChargeType Defaults** | Any implicit default assumptions (e.g., defaulting **Realm** to `consumer` or **Presence** to `inPerson` when no information is found) are explicitly documented within the system prompt to guide the LLM. | `extract_llm.py` |

### II. Data Fidelity and Calculation

| Assumption/Decision | Reasoning and Impact | Source/Code Reference |
| :--- | :--- | :--- |
| **Monetary Values (String Extraction)** | We extract all monetary values and rates as **Strings** (e.g., `"1.53% + 2p"`). This is based on patterns observed in provided statement examples. This avoids floating-point errors and delegates complex parsing to deterministic Python code. | `extraction_schema.py` |
| **Statement Period & Currency** | We currently assume statements cover **monthly** periods and that the primary currency is **Pound Sterling (GBP)**. Extending to multi-currency or non-monthly periods would require pro-rating logic in the transformer. | `transformer.py` |
| **Validation Logic Tolerance** | The self-validation check for `Sum(rows) != header total` uses a **1% tolerance**. This allows for minor rounding differences inherent in statement reporting while still catching significant extraction failures (e.g., missed pages). | `extract_llm.py` |

### III. Architectural Context

| Assumption/Decision | Reasoning and Impact | Source/Code Reference |
| :--- | :--- | :--- |
| **API Design** | The service is designed as a standalone **microservice** exposing a single `/extract` endpoint. This is suitable for easy integration via a lightweight API gateway or direct communication by other engineering teams. | `api.py` |
| **Rounding** | The transformation performs final output rounding using **ROUND\_HALF\_UP** (standard commercial rounding) after all calculations are performed using high-precision `Decimal` types. | `transformer.py` |

More details can be found in the docstrings/comments



### Important Note on PDF Parsing (i.e, Lloyds Statements)

Some merchant statements—especially **Lloyds Cardnet PDFs**—are difficult to parse reliably using standard PDF text extraction libraries.

As a result, attempting automatic PDF extraction may not work.

To handle this, the system provides a **raw text extraction mode** that bypasses PDF parsing entirely.

Raw text mode has been **explicitly tested on Lloyds statements** and consistently produces correct extraction results.

#### Using raw text mode via the API

You can switch to raw text extraction by using the `statementText` parameter:

```bash
curl -X POST "http://localhost:8000/extract" \
  -F "statementText=$(cat lloyds_raw.txt)" \
  -F "merchantStatementUploadId=MERCHANT-001"
```

Or by using the ''`Paste Text`''  button in the front end application.


## Integration into a Larger Platform

This service is designed as a standalone, stateless microservice that can be easily integrated into a broader merchant insights or pricing platform.

### 1. API-Based Integration (Primary Path)

The primary integration path is via the unified `/extract` API endpoint. This endpoint returns a fully structured `NewMerchantStatement` object, allowing consuming systems to rely on a consistent, versioned output contract.

**Platform Flow:**
1.  A consuming service sends a PDF or raw statement text to the API.
2.  The API orchestrator (`api.py`) runs the LLM extraction and deterministic transformation logic.
3.  The API returns the final `NewMerchantStatement` JSON.

This architecture enables downstream services to immediately:
-   Persist the structured data into a database.
-   Feed the data into pricing/underwriting models.
-   Populate customer dashboards and analytics pipelines.

### 2. Frontend and Robustness

The included frontend (`index.html`) serves as a lightweight UI wrapper for testing and internal operational workflows.

## Frontend Images

This section shows screenshots of the web interface (`index.html`).

### Web Interface Screenshot 1

![Screenshot of the primary input area for the web interface](assets/imageA.png)

### Web Interface Screenshot 2

![Screenshot of the JSON output and download area](assets/imageB.png)