import os
from contextlib import asynccontextmanager
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
from src.storage.state_sync import initialize_state, read_local_version, read_only_reason

load_dotenv()
logger = setup_logging(__name__)

configure_telemetry()

router = None
vectorstore = None
answer_llm = None

def startup_event():
    global router, vectorstore, answer_llm
    logger.info("Initializing RAG components for API...")
    initialize_state()  # must run before anything opens Chroma
    router = setup_router()
    vectorstore = create_or_get_vectorstore()
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

# MCP over HTTP at /mcp (the SDK's own route inside this sub-app). Mounted at the root, which matches
# every path, so it must stay the LAST route: anything registered after it would be unreachable.
app.mount("/", mcp.streamable_http_app())
