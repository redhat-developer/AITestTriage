# AITestTriage

AI-powered agent that analyzes Playwright/E2E test failures from OpenShift CI (Prow). It fetches artifacts from GCS, performs root cause analysis with Gemini AI (including visual screenshot analysis), finds similar JIRA issues, and can auto-create bugs.

## Quick Start

**Prerequisites**: Python 3.11+, [uv](https://docs.astral.sh/uv/), a Google AI API key.

```bash
git clone https://github.com/redhat-developer/AITestTriage
cd AITestTriage
uv sync

export GOOGLE_API_KEY=<your-key>

# Interactive CLI — paste a Prow or gcsweb link when prompted
uv run python main.py cli
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GOOGLE_API_KEY` | Yes | — | Google AI API key (Gemini + embeddings) |
| `JIRA_USER_EMAIL` | For JIRA | — | JIRA Cloud user email |
| `JIRA_API_TOKEN` | For JIRA | — | JIRA Cloud API token |
| `SLACK_BOT_TOKEN` | For Slack | — | Slack bot OAuth token |
| `SLACK_SIGNING_SECRET` | For Slack | — | Slack app signing secret |
| `GEMINI_MODEL_NAME` | No | `gemini-2.5-pro` | Gemini model for analysis |
| `EMBEDDING_MODEL` | No | `gemini-embedding-001` | Embedding model for JIRA search |
| `CHROMA_DB_DIR` | No | `./chroma_db` | ChromaDB persistence directory |

## How It Works

```
Prow/gcsweb URL
      │
      ▼
Prompt Builder        discovers GCS artifact layout, builds analysis strategy
      │
      ▼
Gemini Agent  ──────► Tools: read build log → parse JUnit → analyze screenshots
      │                       → search similar JIRA issues → create bug
      ▼
Slack / CLI output
```

The agent always reads the main build log first, then decides whether failures are at the CI orchestration level (pod/step issues) or test level (Playwright failures), and follows the appropriate path.

## Running Modes

```bash
# CLI — interactive, streams tool calls and response
uv run python main.py cli

# Slack bot — mention the bot with a Prow link in any channel
uv run python main.py slack

# Sync JIRA issues to ChromaDB (needed for similar-issue search)
uv run python jira_sync_to_chroma.py
```

## JIRA Similarity Search

The `search_similar_jira_issues` tool uses ChromaDB backed by `gemini-embedding-001` embeddings to find existing JIRA bugs similar to a new failure. Populate it before running:

```bash
export JIRA_USER_EMAIL=<email>
export JIRA_API_TOKEN=<token>
uv run python jira_sync_to_chroma.py
```

If you change the embedding model, delete the DB and re-sync:
```bash
rm -rf ./chroma_db && uv run python jira_sync_to_chroma.py
```

## Container Build

```bash
podman build --platform linux/amd64 -t quay.io/skhileri/test-triage:latest .
podman push quay.io/skhileri/test-triage:latest
```

Deployment manifests live in the `test-triage-infra` repo.
