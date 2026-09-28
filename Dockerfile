FROM python:3.10-slim

# AWS Lambda Web Adapter
COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:0.8.4 /lambda-adapter /opt/extensions/lambda-adapter
# Inform AWS Lambda Web Adapter that FastAPI listens on port 8000
ENV PORT=8000

WORKDIR /app

# Ensure Python output is UTF-8 encoded
ENV PYTHONIOENCODING=utf-8

# Cache HuggingFace models inside the image (not /root) so non-root runtimes like AWS Lambda can read them
ENV HF_HOME=/app/.cache/huggingface

COPY requirements.txt .
# Install CPU-only PyTorch (avoids downloading ~6GB of CUDA binaries)
RUN pip install --no-cache-dir torch --extra-index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt

COPY src/ ./src/
COPY data/ ./data/
COPY baseline/ ./baseline/

# Build the index during the image build process
RUN python -m src.app index

# Pre-download the reranker model (otherwise loaded lazily on the first query)
RUN python -c "from sentence_transformers import CrossEncoder; from src.config import RERANKER_MODEL; CrossEncoder(RERANKER_MODEL)"

EXPOSE 8000

# Health check against the /health endpoint using Python stdlib 
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]

# Run API server. If LOCAL_DIR is set (AWS Lambda: /tmp/.local), copy the bundled .local there first,
# because the image filesystem is read-only on Lambda. Without LOCAL_DIR, it starts exactly as before.
CMD ["sh", "-c", "if [ -n \"$LOCAL_DIR\" ] && [ ! -d \"$LOCAL_DIR\" ]; then cp -r /app/.local \"$LOCAL_DIR\"; fi; exec python -m src.app serve --host 0.0.0.0 --port 8000"]
