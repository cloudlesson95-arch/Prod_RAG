# Agentic RAG Platform 🚧 *(Work in Progress)*

An enterprise-grade, agentic Retrieval-Augmented Generation (RAG) platform with classical ML routing, production telemetry, multi-backend secret management, Model Context Protocol (MCP) server support, and automated multi-cloud CI/CD evaluation pipelines.

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

### Phase 4: Multi-Cloud Deployment (Azure & AWS) & Automated CI/CD
- **Multi-Cloud Infrastructure**: Dual cloud provisioners for Microsoft Azure (Container Apps) and Amazon Web Services (App Runner).
  - **Azure**: Declarative Bicep templates (`infra/azure/main.bicep`) provisioning Container Apps, Container Registry (ACR), Key Vault, Application Insights, and User-Assigned Managed Identity.
  - **AWS**: Automated PowerShell script (`infra/aws/setup.ps1`) provisioning ECR (`rag-api`), Secrets Manager, IAM Roles (`AppRunnerECRAccessRole`, `AppRunnerInstanceRole`), and GitHub OIDC role.
- **Cloud Secrets Strategy**: Integrated `AzureKeyVaultSecretProvider` and `AWSSecretProvider` (`boto3`) dynamically loaded via `SECRET_BACKEND` env variable.
- **Passwordless OIDC Auth**: Federated OpenID Connect (OIDC) identity for passwordless GitHub Actions deployments across both Azure and AWS.
- **Unified Multi-Cloud CI/CD Pipeline**: GitHub Actions workflow (`.github/workflows/deploy.yml`) supporting matrix/targeted deployments (`azure`, `aws`, or `both`) with container image building, pushing, service updating, and post-deployment live evaluation quality gates.

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
