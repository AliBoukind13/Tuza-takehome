from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import tempfile
import os
import traceback
from extract_llm import extract_statement
from transformer import StatementTransformer

app = FastAPI(title="Merchant Statement Processor")

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TO DO: specify frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/extract")
async def extract_statement_endpoint(
    file: UploadFile = File(..., description="PDF statement file"),
    merchantStatementUploadId: str = Form(..., description="Unique upload ID")
):
    """
    Extract and transform a merchant statement PDF.
    
    Endpoint: POST /extract
    
    Accepts:
    - file: PDF statement (multipart/form-data)
    - merchantStatementUploadId: Unique identifier for this upload
    
    Returns:
    - Structured JSON in internal format with transaction breakdowns
    """
    
    # Validate file type
    if not file.filename.endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")
    
    # Create temp file
    with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name
    
    try:
        print(f"Extracting from {file.filename}")
        extracted = extract_statement(tmp_path,"gpt-5")

        print(f"Transforming for upload ID: {merchantStatementUploadId}")
        transformer = StatementTransformer()
        result = transformer.transform(extracted, upload_id=merchantStatementUploadId)
        
        return JSONResponse(
            content=result.model_dump(by_alias=True),
            status_code=200
        )
        
    except Exception as e:
        print(f"Error processing: {str(e)}")
        traceback.print_exc()
        raise HTTPException(
            status_code=500, 
            detail=f"Error processing statement: {str(e)}"
        )
    
    finally:
        # Cleanup temp file
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

@app.get("/")
async def root():
    """Health check endpoint"""
    return {"status": "healthy", "service": "Merchant Statement Processor"}