# Agentic RAG Platform 🚧 *(Work in Progress)*

An enterprise-grade, agentic Retrieval-Augmented Generation (RAG) platform with classical ML routing, production telemetry, multi-backend secret management, Model Context Protocol (MCP) server support, and automated cloud CI/CD evaluation pipelines.

---

## 🚀 Implemented Phases

### Phase 1: Model Context Protocol (MCP) Server
- Integrated Model Context Protocol (MCP) server exposed via `FastMCP` mounted directly on the FastAPI app (`/mcp`).
- Exposes retrieval, ML query routing, and corpus statistics tools for external MCP clients (Claude Desktop, Cursor, n8n).

### Phase 2: Extensible Secret Management
- Abstract `SecretProvider` strategy pattern (`src/secrets.py`) decoupling secrets access from system code.
- Supports local OS Keychain (`KeyringSecretProvider`), environment variables (`EnvSecretProvider`), and cloud secret vaults without touching caller code.

### Phase 3: Production Monitoring & Evaluation
- **Groundedness Checking**: Cosine similarity evaluation between answer embeddings and retrieved context embeddings.
- **Router Confidence Scoring**: Probability-based classical routing confidence scoring.
- **Drift Monitoring**: Population Stability Index (PSI) tracking query distribution drift.
- **Live Evaluator**: HTTP-based evaluation engine running test suites against deployed endpoints.

### Phase 4: Azure Cloud Deployment & Automated CI/CD
- **Infrastructure-as-Code**: Declarative Bicep templates (`infra/azure/main.bicep`) provisioning Azure Container Apps, Azure Container Registry (ACR), Azure Key Vault, Application Insights, and User-Assigned Managed Identity.
- **Cloud Secrets Integration**: `AzureKeyVaultSecretProvider` fetching secrets using Managed Identity (`DefaultAzureCredential`).
- **OIDC Passwordless Authentication**: GitHub Actions OIDC federation for passwordless deployment.
- **Automated CI/CD Pipeline**: GitHub Actions workflow (`.github/workflows/deploy.yml`) executing image build -> push -> deployment -> post-deployment live evaluation quality gate.

---

## 🛠 Local Setup & Running

```bash
# Activate virtual environment
.venv/scripts/activate.ps1

# Run unit test suite
python -m pytest tests/ -v

# Run local REST API server
python -m src.app serve --host 0.0.0.0 --port 8000
```
