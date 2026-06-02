#!/bin/bash
set -e

# Ensure data subdirectories exist on the PVC
mkdir -p /app/data/conversations /app/data/chroma_db

# JIRA sync is handled by the jira-sync CronJob (midnight UTC daily).
# ChromaDB is persisted on PVC so data survives restarts.
# To manually sync: python jira_sync_to_chroma.py

echo "Starting Slack bot..."
exec python main.py slack
