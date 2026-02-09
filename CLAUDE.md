# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

TestTriage is an AI-powered Playwright test failure analysis agent. It analyzes test artifacts from Google Cloud Storage (prow/gcsweb links), performs root cause analysis using Gemini AI with visual screenshot analysis, and integrates with JIRA for bug tracking.

## Commands

```bash
# Install dependencies
uv sync

# Run CLI interface
uv run python main.py cli

# Run Slack bot
uv run python main.py slack

# Run JIRA sync to ChromaDB
uv run python jira_sync_to_chroma.py

# Add a new dependency
uv add <package-name>

# Update dependencies
uv lock --upgrade
uv sync

# Build container image (linux/amd64 on Apple Silicon)
podman build --platform linux/amd64 -t quay.io/skhileri/test-triage:latest .
podman push quay.io/skhileri/test-triage:latest
```

## Required Environment Variables

- `GOOGLE_API_KEY` — Google AI API key for Gemini model (required)
- `JIRA_PAT` — JIRA Personal Access Token for bug creation/search
- `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET` — For Slack bot mode
- `CHROMA_DB_DIR` — ChromaDB persistence directory (default: `./chroma_db`, in prod: `/app/data/chroma_db`)
- `EMBEDDING_MODEL` — Google embedding model (default: `gemini-embedding-001`)
- `GEMINI_MODEL_NAME` — Gemini model for analysis (default: `gemini-3-pro-preview`)

## Architecture

### LangGraph Agent Workflow

The system uses LangGraph to orchestrate an agent workflow defined in `agents/nodes.py`:

```
User Input → test_triage node → (conditional) → tools node → test_triage → ... → END
```

- **test_triage node**: Main LLM call using Gemini with bound tools
- **tools node**: Executes tool calls (ToolNode from langgraph.prebuilt)
- **Routing**: `should_continue()` checks for `tool_calls` to determine next step

### Key Data Flow

1. CLI/Slack extracts `base_dir` from prow/gcsweb URLs using regex patterns
2. `E2ETestAnalysisBuilder` in `prompt_builder/test_analysis.py` constructs a strategic analysis prompt by:
   - Discovering e2e job directories and project directories in GCS
   - Providing an artifact map (build log path, project paths)
   - Giving the agent an analysis strategy — the agent decides what to investigate
3. The agent autonomously explores artifacts using tools, always reading the build log first
4. Conversation history is maintained (in-memory for CLI, pickle files for Slack)

### Tool Implementation Pattern

Tools are defined in `tools/test_analysis_tools.py` using the `@tool` decorator from `langchain_core.tools`. All tools that access test artifacts use `storage_client` (from `utils/storage.py`) which wraps GCS anonymous client access.

Key tools:
- `parse_junit_failures` — Parses JUnit XML for test failures
- `analyze_screenshot` — Sends failure screenshot + context to Gemini for visual root cause analysis
- `read_file` — Reads a file from GCS
- `read_log_files` — Reads all log files from a GCS directory
- `list_directories` / `list_files` / `file_exists` — GCS directory navigation
- `search_similar_jira_issues` — ChromaDB semantic search using Google embeddings
- `create_jira_bug` / `update_jira_bug` — JIRA API integration

### Adding New Tools

1. Add function with `@tool` decorator in `tools/test_analysis_tools.py`
2. Append to the `TOOLS` list at the bottom of that file
3. Tools are automatically bound to the model via `model.bind_tools(TOOLS)` in `agents/nodes.py`

### Gemini Response Handling

Gemini models return `AIMessage.content` as a list of dicts (`{"type": "text", "text": "...", "extras": {...}}`) instead of a plain string. Both interfaces extract only the `text` parts — see the `isinstance(content, list)` blocks in `interfaces/cli.py` and `interfaces/slack_bot.py`.

### GCS Path Convention

All artifact paths are relative to the `test-platform-results` bucket. The `base_dir` extracted from URLs follows the pattern:
- `logs/<job-name>/<job-id>` (periodic jobs)
- `pr-logs/pull/<repo>/<pr>/<job-name>/<job-id>` (PR jobs)

## ChromaDB for JIRA Search

The `search_similar_jira_issues` tool uses ChromaDB with Google's `gemini-embedding-001` model (3072 dimensions). The collection `jira_issues` stores RHDHBUGS issues.

- **Sync script**: `jira_sync_to_chroma.py` populates/updates the database
- **Startup sync**: `entrypoint.sh` runs the sync before starting the Slack bot
- **Periodic sync**: A Kubernetes CronJob (`jira-sync`) runs the sync daily at midnight UTC
- **Persistence**: ChromaDB is stored on the PVC at `/app/data/chroma_db` in production

If the embedding model changes, delete the existing ChromaDB and re-sync:
```bash
rm -rf ./chroma_db && uv run python jira_sync_to_chroma.py
```

## Infrastructure

Deployment manifests live in a separate repo (`test-triage-infra`):
- `manifests/test-triage/base/` — Deployment, PVC, Service, Route, ConfigMap, ImageStream
- `manifests/test-triage/cronjobs/` — JIRA sync CronJob (midnight UTC daily)
- `manifests/test-triage/overlays/prod/` — Production secrets, combines base + cronjobs
- Namespace: `rhdh-sidekick--runtime-ext`
- PVC: 5Gi RWO (aws-ebs) mounted at `/app/data`
- Strategy: `Recreate` (required for RWO PVC)
