import os
from dotenv import load_dotenv
load_dotenv()

# Text chunking parameters
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50

# Retrieval parameters
K_RETRIEVAL = 4
K_EVALUATION = 10

# Agent parameters
MAX_RETRIES = 2

# Model used
EMBEDDING_MODEL = "models/gemini-embedding-001"
EMBEDDING_LOCAL_MODEL = "all-MiniLM-L6-v2"
MAIN_LLM_MODEL = "groq" # or gemini
EVAL_LLM_MODEL = "groq" # or gemini

# Database & Runtime Storage paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCAL_DIR = os.path.join(BASE_DIR, ".local")
CHROMA_PERSIST_DIR = os.path.join(LOCAL_DIR, "chroma_db")
DATA_DIR = os.path.join(BASE_DIR, "data")

# Logging configuration
LOG_LEVEL = "INFO"  # DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_TO_CONSOLE = True 
LOG_TO_FILE = True 
LOG_FILE_PATH = os.path.join("logs", "app.log")
LOG_FORMAT = '%(message)s'
LOG_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'
CAPTURE_EXTERNAL_LOGS = False  # Capture logs from external libraries

ROUTING_METHOD = os.getenv("ROUTING_METHOD", "classical")  # "llm", "classical"
GENERATE_VISUALIZATION = True
CLUSTERS_DIR = os.path.join(LOCAL_DIR, "clusters")
CLASSIFIER_MODEL_PATH = os.path.join(CLUSTERS_DIR, "retrieval_classifier.joblib")

ENABLE_SEMANTIC_CACHE = True
CACHE_SIMILARITY_THRESHOLD = 0.95
SEMANTIC_CACHE_DIR = os.path.join(LOCAL_DIR, "s_cache")

# Preferred models per provider (tried in order, first available wins)
PREFERRED_MODELS = {
    "groq": ["openai/gpt-oss-20b", "qwen/qwen3.6-27b"],
    "gemini": ["gemini-2.5-flash", "gemini-3.5-flash"],
}

# Baseline configuration
EVAL_QUESTIONS_PATH = "baseline/questions.json"

DB_PATH = os.path.join(LOCAL_DIR, "rag.db")

# Hybrid Search configuration
ENABLE_HYBRID_SEARCH = True
K_CANDIDATES = K_RETRIEVAL * 3

# Re-Ranker configuration
ENABLE_RERANKER = True
RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

# Multi-Hop Agent configuration
ENABLE_MULTI_HOP = True
MAX_HOPS = 2
