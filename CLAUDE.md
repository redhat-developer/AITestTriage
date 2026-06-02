# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

## Project Overview

AITestTriage is an AI-powered agent that analyzes Playwright/E2E test failures from OpenShift CI (Prow). It fetches artifacts from Google Cloud Storage, performs root cause analysis using Gemini AI (with visual screenshot analysis), searches for similar JIRA issues via ChromaDB, and optionally creates JIRA bugs.

## Commands

```bash
# Install dependencies
uv sync

# Run CLI interface
uv run python main.py cli

# Run Slack bot
uv run python main.py slack

# Sync JIRA issues to ChromaDB
uv run python jira_sync_to_chroma.py

# Add a dependency
uv add <package-name>

# Build container image (linux/amd64 on Apple Silicon)
podman build --platform linux/amd64 -t quay.io/skhileri/test-triage:latest .
podman push quay.io/skhileri/test-triage:latest
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GOOGLE_API_KEY` | Yes | — | Google AI API key for Gemini |
| `JIRA_USER_EMAIL` | For JIRA | — | JIRA Cloud user email |
| `JIRA_API_TOKEN` | For JIRA | — | JIRA Cloud API token |
| `SLACK_BOT_TOKEN` | For Slack | — | Slack bot OAuth token |
| `SLACK_SIGNING_SECRET` | For Slack | — | Slack app signing secret |
| `GEMINI_MODEL_NAME` | No | `gemini-2.5-pro` | Gemini model for analysis |
| `EMBEDDING_MODEL` | No | `gemini-embedding-001` | Google embedding model |
| `CHROMA_DB_DIR` | No | `./chroma_db` | ChromaDB persistence directory |

## Architecture

### LangGraph Agent Workflow

```
User Input → test_triage node → (conditional) → tools node → test_triage → ... → END
```

- **test_triage node**: Main Gemini LLM call with bound tools (`agents/nodes.py`)
- **tools node**: `ToolNode` executes tool calls; errors are returned as strings, never raised
- **Routing**: `should_continue()` checks for `tool_calls` on the last message
- **Retry**: Exponential backoff on Gemini 429 errors (5s start, 2× factor, 60s max, 5 attempts)

### Key Data Flow

1. CLI/Slack extracts `base_dir` from prow/gcsweb URLs (`utils/url_parser.py`)
2. `E2ETestAnalysisBuilder` (`prompt_builder/test_analysis.py`) discovers GCS artifact layout and builds a strategic prompt — two paths:
   - **Step registry failure**: CI never reached tests — analyze build logs only
   - **Test execution failure**: Full path — JUnit → screenshots → pod logs → JIRA search
3. Agent calls tools in a loop, always reading the main build log first
4. Conversation history: in-memory for CLI, per-thread JSON files for Slack

### Adding New Tools

1. Add `@tool` decorated function in `tools/test_analysis_tools.py`
2. Append to the `TOOLS` list at the bottom of that file
3. Tools are auto-bound via `model.bind_tools(TOOLS)` in `agents/nodes.py`

Key tools:
- `parse_junit_failures` — Parses JUnit XML, strips system-out noise
- `analyze_screenshot` — Vision model RCA (1-2 sentence output)
- `read_file` / `read_log_files` / `list_directories` / `list_files` / `file_exists` — GCS navigation
- `search_similar_jira_issues` — ChromaDB cosine similarity with open-issue boost
- `create_jira_bug` / `update_jira_bug` — JIRA Cloud API (basic auth)

### GCS Path Convention

All artifact paths are relative to the `test-platform-results` bucket:
- `logs/<job-name>/<job-id>` (periodic jobs)
- `pr-logs/pull/<repo>/<pr>/<job-name>/<job-id>` (PR jobs)

### Gemini Response Format

Gemini returns `AIMessage.content` as a list of dicts (`{"type": "text", "text": "...", "extras": {...}}`). Both interfaces filter for `text` blocks — see the `isinstance(content, list)` blocks in `interfaces/cli.py` and `interfaces/slack_bot.py`.

## ChromaDB for JIRA Search

`search_similar_jira_issues` uses ChromaDB with `gemini-embedding-001` (3072 dimensions). The `jira_issues` collection stores RHDHBUGS issues populated by `jira_sync_to_chroma.py`.

If the embedding model changes, delete and re-sync:
```bash
rm -rf ./chroma_db && uv run python jira_sync_to_chroma.py
```
