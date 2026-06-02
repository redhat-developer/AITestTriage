import os
import json
import logging
import threading
from typing import List
from concurrent.futures import ThreadPoolExecutor
from slack_bolt import App
from langchain_core.messages import BaseMessage, HumanMessage, messages_to_dict, messages_from_dict

from agents.nodes import agent
from prompt_builder.test_analysis import get_e2e_test_analysis_prompt
from utils.url_parser import extract_base_dir
from config.settings import settings

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Only allow 1 agent run at a time — each analysis takes 3-5 minutes
# and makes many Gemini API calls. Concurrent runs blow through quota.
MAX_CONCURRENT_ANALYSES = 1

class SlackBot:
    """Slack bot interface for the test analysis agent."""

    def __init__(self):
        self.app = agent
        self.slack_app = App(
            token=settings.slack_bot_token,
            signing_secret=settings.slack_signing_secret,
            process_before_response=False  # Process events after responding to Slack
        )
        # Thread pool with 1 worker — analyses run sequentially to avoid
        # blowing through Gemini API quota. Additional requests queue up.
        self.executor = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_ANALYSES, thread_name_prefix="slack-handler")

        # Register event handlers
        self._register_handlers()
    
    def _process_mention(self, event, client):
        """Process app mention in background thread."""
        thread_ts = event.get('thread_ts') or event.get('ts')

        try:
            conversation_dir = settings.conversation_data_dir
            conversation_file = f"{conversation_dir}conversation_{thread_ts}.json"

            logger.info(f"Processing app mention in channel: \n {event}")

            # Load or initialize conversation history
            if os.path.exists(conversation_file):
                with open(conversation_file, 'r') as f:
                    conversation_history_messages = messages_from_dict(json.load(f))
            else:
                conversation_history_messages = []

            is_first_turn = len(conversation_history_messages) == 0

            if is_first_turn:
                base_dir = extract_base_dir(event['text'])
                if base_dir is None:
                    client.chat_postMessage(
                        channel=event['channel'],
                        text="No valid prow or gcsweb link found",
                        thread_ts=thread_ts,
                        unfurl_links=False,
                        unfurl_media=False
                    )
                    return

                user_input_text = get_e2e_test_analysis_prompt(base_dir=base_dir)
            else:
                user_input_text = event['text']

            # Add user message to history
            current_user_message = HumanMessage(content=user_input_text)
            conversation_history_messages.append(current_user_message)

            inputs = {"messages": conversation_history_messages}

            # Process with agent
            result = self.app.invoke(inputs, config={"recursion_limit": settings.recursion_limit})
            conversation_history_messages = result["messages"]

            # Send response
            # Gemini models may return content as a list of dicts with 'type', 'text',
            # and 'extras' (containing signature blobs). Extract only the text parts.
            raw_content = conversation_history_messages[-1].content
            if isinstance(raw_content, list):
                response_text = "\n".join(
                    block["text"] for block in raw_content
                    if isinstance(block, dict) and block.get("type") == "text"
                )
            else:
                response_text = raw_content
            if not response_text or not response_text.strip():
                response_text = "No response generated"

            client.chat_postMessage(
                channel=event['channel'],
                text=response_text,
                thread_ts=thread_ts,
                unfurl_links=False,
                unfurl_media=False
            )

            # Save conversation history
            with open(conversation_file, 'w') as f:
                json.dump(messages_to_dict(conversation_history_messages), f)
            logger.info(f"Conversation history saved to {conversation_file}")

            logger.info(f"Response sent successfully to channel {event['channel']}")

        except Exception as e:
            logger.error(f"Error processing app mention: {e}", exc_info=True)
            error_name = type(e).__name__
            error_msg = str(e)
            # Truncate long error messages for Slack
            if len(error_msg) > 300:
                error_msg = error_msg[:300] + "..."
            try:
                client.chat_postMessage(
                    channel=event['channel'],
                    text=f"Something went wrong: `{error_name}: {error_msg}`",
                    thread_ts=thread_ts,
                    unfurl_links=False,
                    unfurl_media=False
                )
            except Exception as send_error:
                logger.error(f"Failed to send error message: {send_error}")

    def _register_handlers(self):
        """Register Slack event handlers."""
        @self.slack_app.event("app_mention")
        def handle_app_mention(event, say, client, request):
            """Handle app mention events - acknowledges immediately and processes in background."""
            # Quick validation and immediate return
            if 'text' not in event:
                return

            # Ignore Slack retries — the original request is already being processed
            # in the thread pool. Without this, retries cause duplicate Gemini API calls
            # that blow through the per-minute token quota.
            retry_num = request.headers.get("x-slack-retry-num")
            if retry_num:
                logger.info(f"Ignoring Slack retry #{retry_num} for ts={event.get('ts')}")
                return

            # Submit to thread pool and return immediately
            self.executor.submit(self._process_mention, event, client)
            logger.info(f"Queued app mention for processing: channel={event.get('channel')}, ts={event.get('ts')}")
        
    def start_http_mode(self):
        logger.info("Starting app in HTTP Mode...")
        try:
            self.slack_app.start(port=settings.port)
        finally:
            logger.info("Shutting down thread pool...")
            self.executor.shutdown(wait=True)

if __name__ == "__main__":
    bot = SlackBot()
    bot.start_http_mode()