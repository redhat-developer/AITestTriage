# TestTriage

AI-powered Playwright test failure analysis agent for OpenShift CI. Analyzes test artifacts from GCS, performs root cause analysis using Gemini AI with visual screenshot analysis, and integrates with JIRA for bug tracking.

## Features

- **AI-Powered Analysis** — Gemini AI analyzes test failures with contextual understanding
- **Visual Analysis** — Analyzes screenshots from failed tests to identify root causes
- **Strategic Prompt Builder** — Gives the agent an artifact map and analysis strategy, letting it autonomously decide what to investigate
- **Multi-Interface** — Interactive CLI and Slack bot
- **JIRA Integration** — Semantic similarity search, bug creation, and updates
- **ChromaDB Vector Search** — Finds similar existing JIRA issues using `gemini-embedding-001` embeddings

## Quick Start

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- `GOOGLE_API_KEY` — Google AI API key for Gemini

### Installation

```bash
git clone <repository-url>
cd TestTriage
uv sync
```

### Usage

```bash
# CLI interface — paste a prow or gcsweb link
uv run python main.py cli

# Slack bot (requires SLACK_BOT_TOKEN and SLACK_SIGNING_SECRET)
uv run python main.py slack

# Sync JIRA issues to ChromaDB
uv run python jira_sync_to_chroma.py
```

## Architecture

```
User Input → test_triage → tools ↔ test_triage → END
 (CLI/Slack)    (Gemini)    (GCS, JIRA, etc.)
```

Built on [LangGraph](https://github.com/langchain-ai/langgraph) with a tool-calling loop:

1. **Prompt Builder** (`prompt_builder/test_analysis.py`) — Discovers GCS artifact layout, provides the agent with paths and a strategic analysis plan
2. **Agent** (`agents/nodes.py`) — Gemini model with bound tools, decides what to investigate
3. **Tools** (`tools/test_analysis_tools.py`) — GCS file access, JUnit parsing, screenshot analysis, JIRA search/create

### Tools

| Tool | Description |
|------|-------------|
| `parse_junit_failures` | Parse JUnit XML for test failures |
| `analyze_screenshot` | AI visual analysis of failure screenshots |
| `read_file` | Read a file from GCS |
| `read_log_files` | Read all log files from a GCS directory |
| `list_directories` / `list_files` | Navigate GCS directories |
| `file_exists` | Check if a GCS file exists |
| `search_similar_jira_issues` | Semantic search for similar JIRA issues via ChromaDB |
| `create_jira_bug` / `update_jira_bug` | Create or update JIRA issues |

## Environment Variables

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `GOOGLE_API_KEY` | Yes | Google AI API key | — |
| `JIRA_PAT` | For JIRA | JIRA Personal Access Token | — |
| `SLACK_BOT_TOKEN` | For Slack | Slack bot OAuth token | — |
| `SLACK_SIGNING_SECRET` | For Slack | Slack app signing secret | — |
| `GEMINI_MODEL_NAME` | No | Gemini model for analysis | `gemini-3-pro-preview` |
| `EMBEDDING_MODEL` | No | Embedding model for JIRA search | `gemini-embedding-001` |
| `CHROMA_DB_DIR` | No | ChromaDB persistence directory | `./chroma_db` |
| `PORT` | No | HTTP server port (Slack bot) | `3000` |

## JIRA Sync (ChromaDB)

The `search_similar_jira_issues` tool uses ChromaDB for semantic similarity search. The database is populated by `jira_sync_to_chroma.py` which fetches RHDHBUGS issues and generates embeddings.

- **Startup**: `entrypoint.sh` runs the sync before starting the Slack bot
- **Periodic**: A Kubernetes CronJob runs the sync daily at midnight UTC
- **Embedding model**: `gemini-embedding-001` (3072 dimensions)

If the embedding model changes, delete and re-sync:
```bash
rm -rf ./chroma_db && uv run python jira_sync_to_chroma.py
```

## Deployment

### Container Build

```bash
# Build for cluster (linux/amd64) on Apple Silicon
podman build --platform linux/amd64 -t quay.io/skhileri/test-triage:latest .
podman push quay.io/skhileri/test-triage:latest
```

### Kubernetes (Kustomize)

Infrastructure manifests live in a separate repo (`test-triage-infra`):

```
manifests/test-triage/
  base/           # Deployment, PVC, Service, Route, ConfigMap, ImageStream
  cronjobs/       # JIRA sync CronJob (midnight UTC daily)
  overlays/prod/  # Production secrets, combines base + cronjobs
```

Deploy with:
```bash
oc apply -k manifests/test-triage/overlays/prod/
```

Key infrastructure details:
- **Namespace**: `rhdh-sidekick--runtime-ext`
- **PVC**: 5Gi RWO (aws-ebs) at `/app/data` — stores ChromaDB and conversation data
- **Strategy**: `Recreate` (required for RWO PVC)
- **CronJob**: `jira-sync` runs daily at midnight UTC on the same PVC

## Project Structure

```
TestTriage/
  agents/
    nodes.py              # LangGraph agent workflow
  config/
    settings.py           # Environment-based configuration
  interfaces/
    cli.py                # CLI interface with streaming output
    slack_bot.py          # Slack bot with async event handling
  tools/
    test_analysis_tools.py  # All agent tools (@tool decorated)
  utils/
    storage.py            # GCS anonymous client wrapper
  prompt_builder/
    test_analysis.py      # Strategic prompt builder
  jira_sync_to_chroma.py  # JIRA → ChromaDB sync script
  main.py                 # Entry point (cli / slack)
  entrypoint.sh           # Container startup (sync + slack bot)
  Dockerfile              # Multi-stage build with uv
  pyproject.toml          # Dependencies and project metadata
```

## Adding New Tools

1. Add function with `@tool` decorator in `tools/test_analysis_tools.py`
2. Append to the `TOOLS` list at the bottom of that file
3. Tools are automatically bound to the model via `model.bind_tools(TOOLS)` in `agents/nodes.py`
