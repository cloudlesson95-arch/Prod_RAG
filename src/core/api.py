import math
import os
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from src.logging_config import setup_logging
from src.config import (
    MAIN_LLM_MODEL, DEMO_MAX_FILE_BYTES, DEMO_MAX_TEXT_CHARS, DEMO_TTL_SECONDS, DEMO_RATE_LIMIT_PER_MINUTE,
)
from src.core.utils import create_llm
from src.core.vectorstore import create_or_get_vectorstore
from src.core.rag_agent import setup_router, answer_question
from src.core.mcp_server import mcp
from src.monitoring.telemetry import configure_telemetry
from src.storage.state_sync import initialize_state, read_local_version, read_only_reason
from src.core.rate_limit import RateLimiter
from src.ingestion.demo import DemoStore, answer_from_document
from src.ingestion.errors import IngestError
from src.ingestion.extract import extract_upload_text, safe_upload_name


load_dotenv()
logger = setup_logging(__name__)

configure_telemetry()

router = None
vectorstore = None
answer_llm = None
demo_store = None
demo_upload_limiter = RateLimiter(DEMO_RATE_LIMIT_PER_MINUTE)


def startup_event():
    global router, vectorstore, answer_llm, demo_store
    logger.info("Initializing RAG components for API...")
    initialize_state()  # must run before anything opens Chroma
    router = setup_router()
    vectorstore = create_or_get_vectorstore()
    demo_store = DemoStore(vectorstore.embeddings)  # reuses the loaded embedding model
    answer_llm = create_llm(MAIN_LLM_MODEL)
    logger.info("RAG components initialized successfully.")

@asynccontextmanager
async def lifespan(app: FastAPI):
    startup_event()
    async with mcp.session_manager.run():
        yield

app = FastAPI(
    title = "Simple RAG API",
    description = "REST API for Simple RAG pipeline integrated with N8N",
    version = "1.0.0",
    lifespan = lifespan
)

class QueryRequest(BaseModel):
    question: str = Field(..., examples=["What is a group of cats called?"])

class QueryResponse(BaseModel):
    question: str
    answer: str

@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "model": MAIN_LLM_MODEL,
        "state_version": read_local_version(),
        "read_only": read_only_reason() is not None,
    }

@app.post("/query", response_model = QueryResponse)
def query_rag(request: QueryRequest):
    if not request.question.strip():
        raise HTTPException(status_code = 400, detail="Question cannot be empty")

    try:
        answer = answer_question(request.question, router, vectorstore, answer_llm)
        return QueryResponse(question=request.question, answer=answer)
    except Exception as e:
        logger.error(f"Error processing query: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error processing query")

class DemoUploadResponse(BaseModel):
    doc_id: str
    filename: str
    chunks: int
    expires_in: int = Field(..., description="Seconds without use before the document is dropped")

class DemoQueryRequest(BaseModel):
    question: str = Field(..., max_length=2000, examples=["What is this document about?"])

class DemoQueryResponse(BaseModel):
    question: str
    answer: str
    groundedness_score: float | None

@app.post("/demo/documents", response_model=DemoUploadResponse)
def upload_demo_document(file: UploadFile = File(...)):
    """Upload one .txt, .md or .pdf for single-document Q&A. Held in memory only, never added to the corpus."""
    retry_after = demo_upload_limiter.acquire()
    if retry_after:
        raise HTTPException(status_code=429, detail="Too many demo uploads, try again shortly",
                            headers={"Retry-After": str(math.ceil(retry_after))})

    try:
        filename = safe_upload_name(file.filename or "")
        data = file.file.read(DEMO_MAX_FILE_BYTES + 1)
        if len(data) > DEMO_MAX_FILE_BYTES:
            raise IngestError(f"File is larger than {DEMO_MAX_FILE_BYTES // (1024 * 1024)} MB", 413)
        text = extract_upload_text(file.filename, data, max_chars=DEMO_MAX_TEXT_CHARS)
    except IngestError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))

    try:
        doc = demo_store.add(filename, text)
    except Exception as e:
        logger.error(f"Error storing demo document: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error storing the document")

    return DemoUploadResponse(doc_id=doc.doc_id, filename=doc.filename, chunks=doc.chunks,
                              expires_in=DEMO_TTL_SECONDS)

@app.post("/demo/documents/{doc_id}/query", response_model=DemoQueryResponse)
def query_demo_document(doc_id: str, request: DemoQueryRequest):
    """Ask a question about one uploaded demo document."""
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    not_found = HTTPException(status_code=404, detail="Demo document not found or expired; upload it again")
    doc = demo_store.get(doc_id)
    if doc is None:
        raise not_found

    try:
        result = answer_from_document(doc, request.question, answer_llm)
    except Exception as e:
        if demo_store.get(doc_id) is None:  # evicted while answering
            raise not_found
        logger.error(f"Error answering demo query: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error processing query")
    return DemoQueryResponse(question=request.question, **result)


# MCP over HTTP at /mcp (the SDK's own route inside this sub-app). Mounted at the root, which matches
# every path, so it must stay the LAST route: anything registered after it would be unreachable.
app.mount("/", mcp.streamable_http_app())
