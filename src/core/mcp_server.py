import os
from typing import Dict, Any, List
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from src.logging_config import setup_logging
from src.config import MAIN_LLM_MODEL
from src.core.utils import create_llm
from src.core.vectorstore import create_or_get_vectorstore
from src.core.rag_agent import retrieve_chunks
from src.storage.doc_registry import get_registered_documents
from src.retrieval.multi_hop import execute_multi_hop_pipeline

load_dotenv()
logger = setup_logging(__name__)

# Initialize FastMCP Server
mcp = FastMCP(
    "rag-retrieval",
    instructions="Agentic RAG tools for searching documents, routing queries, checking corpus statistics, and executing multi-hop searches."
)

# Global lazily-initialized RAG singletons
_vectorstore = None
_answer_llm = None

def get_vectorstore():
    global _vectorstore
    if _vectorstore is None:
        _vectorstore = create_or_get_vectorstore()
    return _vectorstore

def get_answer_llm():
    global _answer_llm
    if _answer_llm is None:
        _answer_llm = create_llm(MAIN_LLM_MODEL)
    return _answer_llm

@mcp.tool()
def search_documents(query: str, source_filter: str = "none", k: int = 4) -> List[Dict[str, Any]]:
    """Search vector database for relevant document chunks matching the query.
    
    Args:
        query: The search query text.
        source_filter: Filter by source document name (e.g. 'cat-facts.txt', 'fictional_text.txt') or 'none'.
        k: Maximum number of candidate chunks to retrieve.
    """
    vs = get_vectorstore()
    results = retrieve_chunks(query=query, source_filter=source_filter, vectorstore=vs)
    
    return [
        {
            "content": doc.page_content,
            "source": doc.metadata.get("source", "unknown"),
            "metadata": doc.metadata
        }
        for doc in results[:k]
    ]

@mcp.tool()
def route_query(query: str) -> Dict[str, Any]:
    """Determine whether a query requires document retrieval and predict the target source file.
    
    Args:
        query: The user query to evaluate.
    """
    from src.routing.classifier import predict_needs_retrieval
    from src.routing.clustering import predict_source

    vs = get_vectorstore()
    query_embedding = vs._embedding_function.embed_query(query)
    
    predicted_source = "none"
    needs_retrieval = predict_needs_retrieval(query_embedding)
    if needs_retrieval:
        predicted_source = predict_source(query_embedding)
        
    return {
        "needs_retrieval": needs_retrieval,
        "predicted_source": predicted_source
    }

@mcp.tool()
def get_corpus_stats() -> Dict[str, Dict[str, Any]]:
    """Get metadata statistics for all ingested documents in the corpus."""
    return get_registered_documents()

@mcp.tool()
def multi_hop_search(question: str, initial_source: str = "none") -> Dict[str, Any]:
    """Execute a multi-hop retrieval pipeline for complex queries spanning multiple information sources.
    
    Args:
        question: The complex user question.
        initial_source: Initial source filter override or 'none'.
    """
    vs = get_vectorstore()
    llm = get_answer_llm()
    
    answer = execute_multi_hop_pipeline(
        question=question,
        initial_source=initial_source,
        vectorstore=vs,
        answer_llm=llm,
        retrieve_fn=lambda q, s: retrieve_chunks(q, s, vs)
    )
    
    return {
        "question": question,
        "answer": answer
    }

if __name__ == "__main__":
    mcp.run()
