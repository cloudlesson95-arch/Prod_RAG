FROM python:3.10-slim

# AWS Lambda Web Adapter
COPY --from=public.ecr.aws/lambda/adapter:0.8.4 /lambda-adapter /opt/extensions/lambda-adapter

WORKDIR /app

# Ensure Python output is UTF-8 encoded
ENV PYTHONIOENCODING=utf-8

COPY requirements.txt .
# Install CPU-only PyTorch (avoids downloading ~6GB of CUDA binaries)
RUN pip install --no-cache-dir torch --extra-index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt

COPY src/ ./src/
COPY data/ ./data/
COPY baseline/ ./baseline/

# Build the index during the image build process
RUN python -m src.app index

EXPOSE 8000

# Health check against the /health endpoint using Python stdlib 
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]

# Run API server 
CMD ["python", "-m", "src.app", "serve", "--host", "0.0.0.0", "--port", "8000"]
