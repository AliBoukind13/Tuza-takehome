from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from typing import Optional
import tempfile
import os
import logging
from extract_llm import extract_statement
from transformer import StatementTransformer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Merchant Statement Processor")

# Enable CORS for frontend (future work for now)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TO DO: specify frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/extract")
async def extract_statement_endpoint(
    file: Optional[UploadFile] = File(None, description="PDF statement file"),
    statementText: Optional[str] = Form(None, description="Raw statement text"),
    merchantStatementUploadId: str = Form(..., description="Unique upload ID")
):
    """
    Extract and transform a merchant statement from PDF or raw text.
    
    Endpoint: POST /extract
    
    Accepts (one of):
    - file: PDF statement (multipart/form-data)
    - statementText: Raw statement text (form data)
    Plus:
    - merchantStatementUploadId: identifier for this upload
    
    Returns:
    - Structured JSON in internal format (NewMerchantStatement)
    """
    
    # Validate input - must have either file OR text, not both
    if file and statementText:
        raise HTTPException(
            status_code=400, 
            detail="Provide either file or statementText, not both"
        )
    
    if not file and not statementText:
        raise HTTPException(
            status_code=400,
            detail="Must provide either file or statementText"
        )
    
    try:
        # Extract based on input type
        if file:
            # PDF file path
            if not file.filename.endswith('.pdf'):
                raise HTTPException(status_code=400, detail="File must be a PDF")
            
            # Create temp file
            with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp:
                content = await file.read()
                tmp.write(content)
                tmp_path = tmp.name
            
            try:
                logger.info(f"Extracting from PDF: {file.filename}")
                extracted = extract_statement(tmp_path,"gpt-5")
            finally:
                # Cleanup temp file
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
        else:
            # Raw text
            logger.info(f"Extracting from raw text ({len(statementText)} chars)")
            extracted = extract_statement(statementText,"gpt-5", is_pdf=False)
        
        # Transform to internal format
        logger.info(f"Transforming for upload ID: {merchantStatementUploadId}")
        transformer = StatementTransformer()
        result = transformer.transform(extracted, upload_id=merchantStatementUploadId)
        
        return JSONResponse(
            content=result.model_dump(by_alias=True),
            status_code=200
        )
        
    except Exception as e:
        logger.error(f"Error processing: {str(e)}")
        logger.exception("Full traceback:")
        raise HTTPException(
            status_code=500,
            detail=f"Error processing statement: {str(e)}"
        )

@app.get("/")
async def root():
    """Health check endpoint"""
    return {"status": "healthy", "service": "Merchant Statement Processor"}