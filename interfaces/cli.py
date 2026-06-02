import os
import logging
from typing import List
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage

from agents.nodes import agent
from prompt_builder.test_analysis import get_e2e_test_analysis_prompt
from utils.url_parser import extract_base_dir
from config.settings import settings

# Suppress noisy HTTP request and SDK logs
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("google_genai").setLevel(logging.WARNING)

class CLIInterface:
    """Command Line Interface for the test analysis agent."""
    
    def __init__(self):
        self.app = agent
        self.conversation_history: List[BaseMessage] = []
    
    def start_conversation(self):
        """Start an interactive conversation with the agent."""
        print("Starting chat with the AI test analysis expert. Type 'exit' to end.")
        
        is_first_turn = True
        try:
            while True:
                if is_first_turn:
                    user_link = input("Enter the prow or gcsweb link: ")

                    base_dir = extract_base_dir(user_link)
                    if base_dir is None:
                        print("No valid prow or gcsweb link found")
                        return
                    user_input_text = get_e2e_test_analysis_prompt(
                        base_dir=base_dir
                    )
                    # Display a truncated version for console
                    print(f"\nYOU (Initial Setup & Query): {user_input_text.splitlines()[1][:100]}...")
                    is_first_turn = False
                else:
                    self._save_conversation_log()
                    user_input_text = input("\nYOU: ")
                    if user_input_text.lower() == "exit":
                        print("Exiting chat.")
                        break

                # Add user message to history
                current_user_message = HumanMessage(content=user_input_text)
                self.conversation_history.append(current_user_message)
                
                inputs = {"messages": self.conversation_history}

                print("\nAI: ", end="", flush=True)

                full_response_content = ""
                tool_calls_made = []
                # Track how many messages existed before this turn so we only
                # process new messages and don't re-display old responses.
                prev_message_count = len(self.conversation_history)
                last_seen_count = prev_message_count

                # Stream the response
                for event in self.app.stream(inputs, stream_mode="values", config={"recursion_limit": settings.recursion_limit}):
                    messages_from_event = event["messages"]

                    # Only process messages added since the last event
                    new_messages = messages_from_event[last_seen_count:]
                    last_seen_count = len(messages_from_event)

                    for msg in new_messages:
                        if isinstance(msg, AIMessage):
                            if msg.tool_calls:
                                tool_calls_made = msg.tool_calls
                                for tc in msg.tool_calls:
                                    print(f"\n  → Calling {tc['name']}...", flush=True)

                            if msg.content:
                                # Gemini models may return content as a list of dicts with 'type', 'text',
                                # and 'extras' (containing signature blobs). Extract only the text parts.
                                if isinstance(msg.content, list):
                                    text_content = "\n".join(
                                        block["text"] for block in msg.content
                                        if isinstance(block, dict) and block.get("type") == "text"
                                    )
                                else:
                                    text_content = msg.content
                                if text_content and text_content not in full_response_content:
                                    new_content = text_content.replace(full_response_content, "", 1)
                                    print(new_content, end="", flush=True)
                                    full_response_content += new_content

                        elif isinstance(msg, ToolMessage):
                            tool_name = getattr(msg, 'name', None) or 'tool'
                            print(f"  ✓ {tool_name}", flush=True)

                    # Update conversation history
                    self.conversation_history = messages_from_event

                print()  # Newline after AI response

                # Handle cases where no textual output was produced
                final_ai_message_for_turn = self.conversation_history[-1]
                if isinstance(final_ai_message_for_turn, AIMessage):
                    if not final_ai_message_for_turn.content and not tool_calls_made:
                        if not full_response_content:
                            print("(AI produced no textual output for this turn.)")
                    elif tool_calls_made and not final_ai_message_for_turn.content:
                        if not full_response_content:
                            print(f"(AI initiated tool calls: {[tc['name'] for tc in tool_calls_made]})")

            # Save conversation log
            self._save_conversation_log()
        except Exception as e:
            print(f"Error: {e}")
            self._save_conversation_log()
            return

    def _save_conversation_log(self):
        """Save the full conversation to a log file."""
        if self.conversation_history:
            with open("full_conversation_log.txt", "w") as f:
                f.write("--- Full Conversation History ---\n")
                for i, msg in enumerate(self.conversation_history):
                    f.write(f"--- Message {i}: {type(msg).__name__} ---\n")
                    if hasattr(msg, 'content') and msg.content is not None:
                        # Gemini models may return content as a list of dicts with 'type', 'text',
                        # and 'extras' (containing signature blobs). Extract only the text parts.
                        if isinstance(msg.content, list):
                            text_content = "\n".join(
                                block["text"] for block in msg.content
                                if isinstance(block, dict) and block.get("type") == "text"
                            )
                        else:
                            text_content = msg.content
                        f.write(f"Content: {text_content}\n")
                    
                    if isinstance(msg, AIMessage) and msg.tool_calls:
                        f.write(f"Tool Calls: {msg.tool_calls}\n")
                    
                    if isinstance(msg, ToolMessage):
                        f.write(f"Tool Call ID: {msg.tool_call_id}\n")
                        if hasattr(msg, 'name') and msg.name:
                            f.write(f"Tool Name: {msg.name}\n")
                    f.write("\n")
            print("\nFull conversation saved to full_conversation_log.txt")
        else:
            print("\nNo conversation to save.")

def start_cli():
    """Entry point for CLI interface."""
    cli = CLIInterface()
    cli.start_conversation() 