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

# Seed state baked into the image at build time (read-only on AWS Lambda)
SEED_DATA_DIR = os.path.join(BASE_DIR, "data")
SEED_LOCAL_DIR = os.path.join(BASE_DIR, ".local")

# Working copy the app reads and writes. Defaults to the seed dirs locally
LOCAL_DIR = os.path.abspath(os.getenv("LOCAL_DIR", SEED_LOCAL_DIR))
DATA_DIR = os.path.abspath(os.getenv("DATA_DIR", SEED_DATA_DIR))
INGESTED_DATA_DIR = os.path.join(DATA_DIR, "ingested")
CHROMA_PERSIST_DIR = os.path.join(LOCAL_DIR, "chroma_db")

# Logging configuration
LOG_LEVEL = "INFO"  # DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_TO_CONSOLE = os.getenv("LOG_TO_CONSOLE", "true").lower() in ("1", "true", "yes")
LOG_TO_FILE = os.getenv("LOG_TO_FILE", "true").lower() in ("1", "true", "yes")
LOG_FILE_PATH = os.getenv("LOG_FILE_PATH", os.path.join("logs", "app.log"))
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

# Secret Provider configuration
SECRET_BACKEND = os.getenv("SECRET_BACKEND", "keyring")  # "keyring", "env", "azure_keyvault", "aws_secretsmanager"
KEYRING_SERVICE_NAME = os.getenv("KEYRING_SERVICE_NAME", "agentic-rag-platform")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

# Groundedness Check threshold
GROUNDEDNESS_THRESHOLD = float(os.getenv("GROUNDEDNESS_THRESHOLD", "0.5"))

# Azure Application Insights Telemetry
APPLICATIONINSIGHTS_CONNECTION_STRING = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "")

# Azure Key Vault configuration
AZURE_KEYVAULT_URL = os.getenv("AZURE_KEYVAULT_URL", "")

# Persistent state snapshots
STATE_BACKEND = os.getenv("STATE_BACKEND", "local")  # "local", "azure_blob", "s3"
STATE_SNAPSHOT_NAME = os.getenv("STATE_SNAPSHOT_NAME", "state.tar.gz")
AZURE_STORAGE_ACCOUNT_URL = os.getenv("AZURE_STORAGE_ACCOUNT_URL", "")
AZURE_STATE_CONTAINER = os.getenv("AZURE_STATE_CONTAINER", "rag-state")
AZURE_STORAGE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "")  # local Azurite testing only
S3_STATE_BUCKET = os.getenv("S3_STATE_BUCKET", "")

# MCP server (HTTP transport). The SDK's DNS rebinding protection only accepts localhost Host headers,
# which is right for a local server; public deployments set this to false (main.bicep, deploy.yml).
MCP_DNS_REBINDING_PROTECTION = os.getenv("MCP_DNS_REBINDING_PROTECTION", "true").lower() in ("1", "true", "yes")
