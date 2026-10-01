# Agentic RAG Platform

[![Eval Loop](https://github.com/cloudlesson95-arch/Prod_RAG/actions/workflows/evaluate.yml/badge.svg)](https://github.com/cloudlesson95-arch/Prod_RAG/actions/workflows/evaluate.yml)
[![Deploy](https://github.com/cloudlesson95-arch/Prod_RAG/actions/workflows/deploy.yml/badge.svg)](https://github.com/cloudlesson95-arch/Prod_RAG/actions/workflows/deploy.yml)

A production-oriented continuation of [Simple_RAG](https://github.com/cloudlesson95-arch/Simple_RAG). The core pipeline (hybrid search, cross-encoder re-ranking, multi-hop agent, classical ML routing, semantic cache, LLM-as-judge evaluation) is documented in the [Simple_RAG README](https://github.com/cloudlesson95-arch/Simple_RAG#readme). This repository adds an MCP server, pluggable secrets, monitoring, persistent state, and automated deployment of one Docker image to **Azure Container Apps** and **AWS Lambda**.

> 🚧 Work in progress: Phases 1–5 are done, Phases 6–8 are planned.

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
            ├── state:   Blob snapshot (versioned) ├── state:   S3 snapshot (versioned)
            ├── logs:    Application Insights      ├── logs:    CloudWatch
            └── scales to zero, 1 replica          └── scales to zero, Function URL

Same image in both clouds: FastAPI (/health, /query, /docs) + MCP server (/mcp)
```

## Features by phase

| Phase | Status | What it adds |
|---|---|---|
| 1. MCP server | ✅ Done | RAG tools (`search_documents`, `route_query`, `get_corpus_stats`, `multi_hop_search`) over MCP: streamable HTTP at `/mcp` on the same API, or stdio for local clients such as Claude Desktop |
| 2. Secret management | ✅ Done | `SECRET_BACKEND` selects the OS keyring, env vars, Azure Key Vault or AWS Secrets Manager; code only calls `get_secret()` |
| 3. Monitoring & evaluation | ✅ Done | Groundedness score, router confidence, PSI drift, `live-eval` against a deployed URL, Azure Monitor telemetry |
| 4. Multi-cloud deployment | ✅ Done | One image to Azure and AWS through GitHub Actions with OIDC; setup and teardown scripts; a live evaluation gate after every deploy |
| 5. Persistent storage | ✅ Done | Corpus, index, document registry and router models live in a versioned snapshot (Azure Blob / S3), restored at startup and published after every write |
| 6. On-demand ingestion | Planned | `POST /ingest/url` and `/ingest/file` with re-indexing |
| 7. Scheduled data pipeline | Planned | Daily job ingesting GitHub release notes |
| 8. Web frontend | Planned | Next.js chat, ingestion and dashboard pages |

**Design notes**

- **One image, two runtimes.** Lambda runs the container as a non-root user on a read-only filesystem. The models are baked into the image at build time and all writable state lives under `/tmp/state`, so the same image runs unchanged in both clouds.
- **Persistent state.** Each instance restores the latest snapshot to local disk at startup; on the very first boot it publishes the image's seed corpus and prebuilt index as snapshot #1. A write publishes a new snapshot only if nobody else published first (ETag conditional writes), so a stale instance can never overwrite newer state. If the store is unreachable at startup, the app serves the seed read-only instead of failing. Snapshots rather than a mounted volume keep queries on local disk (SQLite is unreliable on network filesystems) and need no VPC or NAT gateway on Lambda. The semantic cache is deliberately not persisted, so every deploy's evaluation gate tests the real pipeline. Old versions are kept 30 days for rollback.
- **Evaluation gates.** `evaluate.yml` runs the offline benchmark inside the image on every push and pull request. `deploy.yml` deploys to both clouds, waits for `/health`, then runs `live-eval` against each deployment. Both fail below 80% Precision@k.

## Local setup

Python 3.10 matches the Docker image, and `requirements.txt` is pinned for it. On a newer Python, install `requirements_clean.txt` instead.

```powershell
python -m venv .venv; .venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m src.app set-secret GROQ_API_KEY       # stored in the OS keyring; or put the keys in .env
python -m src.app set-secret GOOGLE_API_KEY
python -m src.app index                          # builds the index and the router models
python -m src.app serve                          # http://localhost:8000/docs
```

Other commands: `query "<question>"`, `evaluate`, `history`, `live-eval --target-url <url>`, `state status`, `state pull`, `get-secret <name>`.

### Test

```powershell
python -m pytest tests/ -v
```

The Azure Blob tests also run when `AZURITE_CONNECTION_STRING` points at a running [Azurite](https://learn.microsoft.com/azure/storage/common/storage-use-azurite) emulator, and the S3 tests when `moto[s3]` is installed; otherwise they are skipped.

To run the image the way Lambda does (read-only filesystem, non-root user; `.env` holds the API keys):

```powershell
docker build -t rag-api:dbg .
docker run --rm -p 8000:8000 --read-only --tmpfs /tmp:rw,size=512m --user 993:990 --memory 2g -e SECRET_BACKEND=env -e LOCAL_DIR=/tmp/state/.local -e DATA_DIR=/tmp/state/data -e HOME=/tmp -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 --env-file .env rag-api:dbg
```

### Configuration

Every setting has a working local default, and the cloud values are set by `infra/azure/main.bicep` and `deploy.yml`. The full list is in [`src/config.py`](src/config.py) and [`.env.example`](.env.example). The ones you are most likely to change:

| Variable | Default | Purpose |
|---|---|---|
| `SECRET_BACKEND` | `keyring` | `keyring`, `env`, `azure_keyvault` or `aws_secretsmanager` |
| `STATE_BACKEND` | `local` | `local`, `azure_blob` (with `AZURE_STORAGE_ACCOUNT_URL`) or `s3` (with `S3_STATE_BUCKET`) |
| `LOCAL_DIR`, `DATA_DIR` | `<repo>/.local`, `<repo>/data` | Working copy of the index and databases, and of the corpus |
| `MCP_DNS_REBINDING_PROTECTION` | `true` | Set to `false` when `/mcp` is served behind a public hostname |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | – | Enables Azure Monitor telemetry |

## Deploy to Azure and AWS

Prerequisites: PowerShell, the Azure CLI signed in (`az login`) with permission to create role assignments and app registrations, the AWS CLI with an admin profile, and your own GitHub copy of this repository (pass `-GitHubRepo <owner>/<repo>` to both setup scripts).

1. Run `.\infra\azure\setup.ps1`, then `$env:AWS_PROFILE = "<admin-profile>"; .\infra\aws\setup.ps1`. Both ask for the Groq and Google API keys and print the values for the next step.
2. Add those values in GitHub → Settings → Secrets and variables → Actions:

   | Secrets | Variables |
   |---|---|
   | `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID` | `RESOURCE_GROUP`, `ACR_NAME`, `CONTAINER_APP_NAME`, `DEPLOYED_APP_URL` |
   | `AWS_ROLE_TO_ASSUME` | `AWS_REGION`, `AWS_ECR_REPO`, `AWS_LAMBDA_ROLE_ARN`, `AWS_STATE_BUCKET` |
   | `GROQ_API_KEY`, `GOOGLE_API_KEY` (used by the evaluation gates) | |

3. Push to `main`, or run the Deploy workflow manually (targeting `azure`, `aws` or `both`). The first AWS run creates the Lambda function and its Function URL.

Re-running the Azure `setup.ps1` later resets the Container App to a placeholder image until the next deploy, so run the Deploy workflow right after it.

### Check a deployment

```powershell
$AZ_URL  = "https://" + (az containerapp list -g rg-ragprod --query "[0].properties.configuration.ingress.fqdn" -o tsv)
$AWS_URL = (aws lambda get-function-url-config --function-name ragprod-api --region us-east-1 --query FunctionUrl --output text).TrimEnd('/')

curl.exe "$AZ_URL/health"                                              # status, state_version, read_only
Invoke-RestMethod -Method Post -Uri "$AWS_URL/query" -ContentType 'application/json' -Body '{"question":"What is a group of cats called?"}' -TimeoutSec 300
python -m src.app live-eval --target-url $AZ_URL --revision manual     # benchmark against the deployment
```

API docs are at `<url>/docs`, and MCP clients connect to `<url>/mcp`. Logs: `az containerapp logs show -n <app> -g rg-ragprod --follow` and `aws logs tail /aws/lambda/ragprod-api --follow --region us-east-1`.

### Add documents (until Phase 6)

From your machine: set `STATE_BACKEND` together with `AZURE_STORAGE_ACCOUNT_URL` or `S3_STATE_BUCKET`, and point `LOCAL_DIR`/`DATA_DIR` at empty scratch folders. Run `state pull`, copy the files into `DATA_DIR/ingested/`, run `index` (it publishes a new snapshot), then restart the app. Don't run `index` inside a running container.

### Teardown

Disable the Deploy workflow first (otherwise the next push re-creates the Lambda function), then run `.\infra\azure\teardown.ps1` and `.\infra\aws\teardown.ps1`. They list everything the setup scripts and deploys created, including all state snapshots, ask for confirmation, delete it, and are safe to re-run. Add `-DeleteOidcProvider` to the AWS script if no other repository in the account uses GitHub OIDC. To deploy again, repeat the steps above; only `AZURE_CLIENT_ID` and `DEPLOYED_APP_URL` change.

## Known limitations

- The endpoints, including `/mcp`, are public and unauthenticated: anyone with the URL can read the corpus and use your LLM quota.
- Both clouds scale to zero, so the first request after an idle period can take a minute or more.
- On Lambda, a warm instance can serve an older snapshot for a while after a write made elsewhere.
- Editing the seed files in `data/` doesn't change an existing snapshot; add or update documents as described above.
- The semantic cache is per instance and starts empty after every deploy (by design).
- `live-eval` stores its results in the `rag.db` of the machine that runs it, not in the deployed state.
- Every deploy pushes a multi-GB image to both registries; delete old tags periodically.

## License

MIT
