FROM python:3.10-slim

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

CMD ["python", "-m", "src.app", "evaluate"]
