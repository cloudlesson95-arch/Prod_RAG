# Agentic RAG Platform

[![Eval Loop](https://github.com/cloudlesson95-arch/Prod_RAG/actions/workflows/evaluate.yml/badge.svg)](https://github.com/cloudlesson95-arch/Prod_RAG/actions/workflows/evaluate.yml)
[![Deploy](https://github.com/cloudlesson95-arch/Prod_RAG/actions/workflows/deploy.yml/badge.svg)](https://github.com/cloudlesson95-arch/Prod_RAG/actions/workflows/deploy.yml)

A production-oriented continuation of [Simple_RAG](https://github.com/cloudlesson95-arch/Simple_RAG): the same agentic RAG pipeline, extended with an MCP server, pluggable secret management, production monitoring, and automated deployment of one Docker image to **Azure Container Apps** and **AWS Lambda**.

> 🚧 Work in progress: Phases 1–4 are done, Phases 5–8 are planned (see [Roadmap](#roadmap)).

The core pipeline (hybrid search, cross-encoder re-ranking, multi-hop agent, classical ML routing, semantic cache, LLM-as-judge evaluation) is documented in the [Simple_RAG README](https://github.com/cloudlesson95-arch/Simple_RAG#readme) and not repeated here.

## Architecture

```
GitHub Actions (OIDC, no stored cloud credentials)
  ├── evaluate.yml   build image → offline evaluation gate
  └── deploy.yml     build image → push → deploy → /health warmup → live evaluation gate
                          │                                  │
                          ▼                                  ▼
            Azure Container Apps                   AWS Lambda (container image)
            ├── image:   ACR                       ├── image:   ECR
            ├── secrets: Key Vault                 ├── secrets: Secrets Manager
            │            (Managed Identity)        │            (IAM execution role)
            ├── logs:    Application Insights      ├── logs:    CloudWatch
            └── always on, 1–3 replicas            └── scales to zero, Function URL

Same image in both clouds: FastAPI (/health, /query, /docs) + MCP server (/mcp)
```

## Roadmap

Phase numbers refer to this repository; Simple_RAG's own development phases are described in its README.

| Phase | Status | Scope |
|---|---|---|
| 1. MCP server | ✅ Done | RAG tools exposed over MCP on the existing API |
| 2. Secret management | ✅ Done | Pluggable providers: OS keyring, env vars, cloud vaults |
| 3. Monitoring & evaluation | ✅ Done | Groundedness, router confidence, drift (PSI), live evaluator, telemetry |
| 4. Multi-cloud deployment | ✅ Done | Azure + AWS, OIDC CI/CD, live evaluation gates, teardown scripts |
| 5. Persistent storage | Planned | Mounted volume so index and databases survive restarts |
| 6. On-demand ingestion | Planned | `POST /ingest/url` and `/ingest/file` with re-index and router retraining |
| 7. Scheduled data pipeline | Planned | Daily GitHub Actions job ingesting GitHub release notes |
| 8. Web frontend | Planned | Next.js chat, ingestion and dashboard pages |

## Phases 1–3

**Phase 1: MCP server.** [`src/core/mcp_server.py`](src/core/mcp_server.py) wraps existing functions as MCP tools (`search_documents`, `route_query`, `get_corpus_stats`, `multi_hop_search`) for clients such as Claude Desktop, Cursor or n8n. It is mounted on the FastAPI app at `/mcp`, so it ships in the same process and container.

**Phase 2: Secret management.** [`src/secrets.py`](src/secrets.py) defines a `SecretProvider` interface, selected by `SECRET_BACKEND`: `keyring` (local default, falls back to env vars), `env`, `azure_keyvault`, `aws_secretsmanager`. Calling code only uses `get_secret(name)`.

**Phase 3: Monitoring & evaluation.**
- **Groundedness:** cosine similarity between the answer and the retrieved context; logs a warning below `GROUNDEDNESS_THRESHOLD`. A coarse drift signal, not full hallucination detection.
- **Router confidence:** the classical router logs the classifier's `predict_proba` confidence (uncalibrated, given the small training set).
- **Drift:** `population_stability_index()` in [`src/monitoring/drift.py`](src/monitoring/drift.py). Unit-tested; not yet fed with live traffic (planned for Phase 8).
- **Live evaluator:** `live-eval` runs the benchmark against a deployed URL over HTTP and stores results in `rag.db` with `run_type=live`.
- **Telemetry:** Azure Monitor OpenTelemetry when `APPLICATIONINSIGHTS_CONNECTION_STRING` is set; no-op otherwise.

## Phase 4: Multi-cloud deployment

### What gets deployed

| | Azure | AWS |
|---|---|---|
| Compute | Container Apps (1 vCPU, 2 GiB, 1–3 replicas) | Lambda container (3008 MB, 300 s timeout) + Lambda Web Adapter |
| Endpoint | Container Apps HTTPS ingress | Lambda Function URL |
| Registry | ACR (Basic) | ECR repository `rag-api` |
| Secrets | Key Vault via user-assigned Managed Identity | Secrets Manager via Lambda execution role |
| Logs | Log Analytics + Application Insights | CloudWatch Logs |
| Provisioning | Bicep ([`infra/azure/main.bicep`](infra/azure/main.bicep)) via `setup.ps1` | AWS CLI ([`infra/aws/setup.ps1`](infra/aws/setup.ps1)); the function itself is created by the first deploy |
| CI authentication | Entra ID app with federated credential (OIDC) | IAM OIDC provider + role (OIDC) |

Key Vault secret names can't contain `_`, so the Azure provider maps `GROQ_API_KEY` to `GROQ-API-KEY` automatically.

### CI/CD

- **`evaluate.yml`** (every push and PR to `main`): builds the image and runs the offline evaluation inside it; fails below 80% Precision@k.
- **`deploy.yml`** (push to `main`, or a manual run targeting `azure`, `aws` or `both`): builds the image, pushes it to ACR/ECR (tagged with the commit SHA and `latest`), updates the Container App / Lambda, polls `/health` until the app is up, then runs `live-eval` against the deployed URL (fails below 80%).

### One image, two runtimes

Lambda runs containers as a non-root user on a read-only filesystem where only `/tmp` is writable, and allows 10 s for initialization. The same image works in both clouds:

- The embedding and re-ranker models are downloaded at build time into `/app/.cache/huggingface` (`HF_HOME`), so any user can read them.
- `deploy.yml` sets these environment variables on Lambda only: `HF_HUB_OFFLINE=1` (no model downloads), `HOME=/tmp`, and `LOCAL_DIR=/tmp/.local`. With `LOCAL_DIR` set, the container copies the prebuilt index there at startup, so Chroma, the semantic cache and SQLite can write.
- `AWS_LWA_ASYNC_INIT=true` lets the app finish starting after Lambda's 10 s init window instead of being restarted.

Azure runs the image with default settings. To reproduce the Lambda environment locally (`.env` holds the API keys):

```powershell
docker build -t rag-api:dbg .
docker run --rm -p 8000:8000 --read-only --tmpfs /tmp:rw,size=512m --user 993:990 --memory 1g -e SECRET_BACKEND=env -e LOCAL_DIR=/tmp/.local -e HOME=/tmp -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 --env-file .env rag-api:dbg
```

### Deploy from scratch

Prerequisites: PowerShell, Azure CLI signed in (`az login`) with permission to create role assignments and app registrations, AWS CLI with an admin profile, and a GitHub copy of this repository. The scripts default to `cloudlesson95-arch/Prod_RAG`; pass `-GitHubRepo <owner>/<repo>` for a fork.

1. Run `.\infra\azure\setup.ps1` and enter the Groq and Google API keys when prompted.
2. Run `$env:AWS_PROFILE = "<admin-profile>"; .\infra\aws\setup.ps1` and enter the keys again.
3. Copy the values both scripts print into GitHub → Settings → Secrets and variables → Actions:

   | Secrets | Variables |
   |---|---|
   | `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID` | `RESOURCE_GROUP`, `ACR_NAME`, `CONTAINER_APP_NAME`, `DEPLOYED_APP_URL` |
   | `AWS_ROLE_TO_ASSUME` | `AWS_REGION`, `AWS_ECR_REPO`, `AWS_LAMBDA_ROLE_ARN` |
   | `GROQ_API_KEY`, `GOOGLE_API_KEY` (used by the evaluation gates) | |

4. Push to `main`, or run the Deploy workflow manually. The first AWS run creates the Lambda function and its Function URL.

### Using the deployment

```powershell
$AZ_URL  = "https://" + (az containerapp list -g rg-ragprod --query "[0].properties.configuration.ingress.fqdn" -o tsv)
$AWS_URL = (aws lambda get-function-url-config --function-name ragprod-api --region us-east-1 --query FunctionUrl --output text).TrimEnd('/')

curl.exe "$AZ_URL/health"
Invoke-RestMethod -Method Post -Uri "$AWS_URL/query" -ContentType 'application/json' -Body '{"question":"What is a group of cats called?"}' -TimeoutSec 300

# Runs on your machine and sends the benchmark questions to the cloud; results appear in `python -m src.app history`
python -m src.app live-eval --target-url $AZ_URL --revision manual
```

- **Interactive API docs:** `<url>/docs`.
- **Logs:** `az containerapp logs show -n <app> -g rg-ragprod --follow` or `aws logs tail /aws/lambda/ragprod-api --follow --region us-east-1`.
- **Local only:** `index` and the offline `evaluate` run locally. On Azure you can also run them inside the container with `az containerapp exec`; Lambda has no shell access.
- **New documents:** the index is built into the image, so adding documents needs a redeploy (until Phases 5–6).

### Teardown

1. Disable the Deploy workflow in GitHub Actions. Otherwise the next push fails, or re-creates the Lambda function if the AWS role still exists.
2. `.\infra\azure\teardown.ps1` deletes the resource group, purges the soft-deleted Key Vault (so `setup.ps1` can reuse the name), and deletes the GitHub app registration.
3. `.\infra\aws\teardown.ps1` deletes the Lambda function, its log group, the ECR repository with all images, both secrets (without a recovery window), and both IAM roles. Add `-DeleteOidcProvider` if no other repository in the account uses GitHub OIDC.

Both scripts list what they will delete, ask for confirmation, and are safe to re-run. To deploy again, repeat *Deploy from scratch*. Afterwards only `AZURE_CLIENT_ID` and `DEPLOYED_APP_URL` get new values; everything else stays the same.

### Known limitations

- The endpoints are public and unauthenticated: anyone with the URL can use your LLM quota.
- Azure/Lambda scales to zero, so the first request after an idle period can take a minute or more.
- Every deploy pushes a multi-GB image to both registries; delete old tags periodically.
- Runtime state (semantic cache, evaluation runs) is lost on restart in both clouds; Phase 5 addresses this.

## Local development

```powershell
python -m venv .venv; .venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m src.app set-secret GROQ_API_KEY     # stored in the OS keyring (or put keys in .env)
python -m src.app set-secret GOOGLE_API_KEY
python -m src.app index
python -m src.app serve                        # http://localhost:8000/docs
python -m pytest tests/ -v
```

`query`, `evaluate` and `history` work as in Simple_RAG. New commands: `set-secret`, `get-secret`, `live-eval`.

### New configuration

| Variable | Default | Purpose |
|---|---|---|
| `SECRET_BACKEND` | `keyring` | `keyring`, `env`, `azure_keyvault` or `aws_secretsmanager` |
| `KEYRING_SERVICE_NAME` | `agentic-rag-platform` | OS keyring service name |
| `AZURE_KEYVAULT_URL` | – | Key Vault URL (set by Bicep) |
| `AWS_REGION` | `us-east-1` | Secrets Manager region |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | – | Enables Azure Monitor telemetry |
| `GROUNDEDNESS_THRESHOLD` | `0.5` | Groundedness warning threshold |
| `LOCAL_DIR` | `<repo>/.local` | Root for index, caches and `rag.db` (Lambda: `/tmp/.local`) |
| `LOG_TO_CONSOLE`, `LOG_TO_FILE`, `LOG_FILE_PATH` | `true`, `true`, `logs/app.log` | Logging targets |

## Project structure (additions to Simple_RAG)

```
src/
├── secrets.py                    # SecretProvider strategies (Phases 2 and 4)
├── core/mcp_server.py            # MCP tools mounted at /mcp (Phase 1)
├── monitoring/                   # groundedness, drift, telemetry (Phase 3)
└── evaluation/live_evaluator.py  # HTTP evaluation of deployed endpoints (Phase 3)
infra/
├── azure/                        # main.bicep, parameters.json, setup.ps1, teardown.ps1
└── aws/                          # setup.ps1, teardown.ps1
tests/                            # unit tests for Phases 1–3
.github/workflows/
├── evaluate.yml                  # offline evaluation gate
└── deploy.yml                    # multi-cloud build, deploy and live evaluation gate
```

## License

MIT
