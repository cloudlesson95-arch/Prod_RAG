import os
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from src.logging_config import setup_logging
from src.config import MAIN_LLM_MODEL
from src.core.utils import create_llm
from src.core.vectorstore import create_or_get_vectorstore
from src.core.rag_agent import setup_router, answer_question
from src.core.mcp_server import mcp
from src.monitoring.telemetry import configure_telemetry

load_dotenv()
logger = setup_logging(__name__)

configure_telemetry()

app = FastAPI(
    title = "Simple RAG API",
    description = "REST API for Simple RAG pipeline integrated with N8N",
    version = "1.0.0"
)

app.mount("/mcp", mcp.streamable_http_app())

router = None
vectorstore = None
answer_llm = None

@app.on_event("startup")
def startup_event():
    global router, vectorstore, answer_llm
    logger.info("Initializing RAG components for API...")
    router = setup_router()
    vectorstore = create_or_get_vectorstore()
    answer_llm = create_llm(MAIN_LLM_MODEL)
    logger.info("RAG components initialized successfully.")

class QueryRequest(BaseModel):
    question: str = Field(..., example="What is a group of cats called?")

class QueryResponse(BaseModel):
    question: str
    answer: str

@app.get("/health")
def health_check():
    return {"status": "ok", "model": MAIN_LLM_MODEL}

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
