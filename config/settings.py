import getpass
import os
from typing import Optional

from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Configuration settings for the test analysis agent."""

    # Models
    gemini_model_name: str = "gemini-2.5-pro"
    screenshot_model_name: Optional[str] = "gemini-2.5-pro"
    embedding_model: str = "gemini-embedding-001"

    # LLM
    llm_temperature: float = 0.3
    recursion_limit: int = 100

    # Google Cloud Storage
    gcs_bucket_name: str = "test-platform-results"

    # JIRA (Atlassian Cloud)
    jira_server_url: str = "https://redhat.atlassian.net"
    jira_project_key: str = "RHDHBUGS"
    jira_affects_version: str = "1.9.0"
    jira_labels: str = "ci-fail,AITestTriage"
    jira_create_enabled: bool = True
    jira_update_enabled: bool = False
    jira_user_email: Optional[str] = None
    jira_api_token: Optional[str] = None

    # API Keys
    google_api_key: Optional[str] = None

    # Slack
    slack_bot_token: Optional[str] = None
    slack_signing_secret: Optional[str] = None
    slack_app_token: Optional[str] = None

    # Server
    port: int = 3000

    # Storage
    chroma_db_dir: str = "./chroma_db"
    conversation_data_dir: str = ""

    model_config = {
        "populate_by_name": True,
    }

    @model_validator(mode="after")
    def _resolve_defaults(self):
        # screenshot_model_name falls back to gemini_model_name
        if self.screenshot_model_name is None:
            self.screenshot_model_name = self.gemini_model_name

        # Prompt for Google API key in CLI mode if not set
        if not self.google_api_key:
            if os.environ.get("GOOGLE_API_KEY"):
                self.google_api_key = os.environ["GOOGLE_API_KEY"]
            else:
                self.google_api_key = getpass.getpass("Enter your Google AI API key: ")
                os.environ["GOOGLE_API_KEY"] = self.google_api_key

        return self


# Global settings instance
settings = Settings()
