import logging
from typing import Annotated, Sequence, TypedDict
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langgraph.types import RetryPolicy
from langchain_google_genai import ChatGoogleGenerativeAI
from config.settings import settings
from tools.test_analysis_tools import TOOLS

logger = logging.getLogger(__name__)


class AgentState(TypedDict):
    """State definition for the test analysis agent."""
    messages: Annotated[Sequence[BaseMessage], add_messages]

# Initialize the model with tools
model = ChatGoogleGenerativeAI(
    model=settings.gemini_model_name,
    api_key=settings.google_api_key,
    temperature=settings.llm_temperature,
)
llm_with_tools = model.bind_tools(TOOLS)

# Create tool node
tool_node = ToolNode(tools=TOOLS, handle_tool_errors=True)

def model_call(state: AgentState) -> AgentState:
    """Main model call node that processes messages and generates responses."""
    current_messages = state["messages"]
    response = llm_with_tools.invoke(current_messages)
    return {"messages": [response]}

def should_continue(state: AgentState) -> str:
    """Determine whether to continue with tool calls or end the conversation."""
    messages = state["messages"]
    last_message = messages[-1]
    if not last_message.tool_calls:
        return "end"
    else:
        return "continue"

# Retry policy for rate-limit (429) errors from the Gemini API.
# The per-minute token quota resets quickly, so start with a 5s wait
# and back off up to 60s, trying up to 5 times before giving up.
rate_limit_retry = RetryPolicy(
    initial_interval=5.0,
    backoff_factor=2.0,
    max_interval=60.0,
    max_attempts=5,
    jitter=True,
    retry_on=lambda exc: "RESOURCE_EXHAUSTED" in str(exc) or "429" in str(exc),
)

# Build and compile the agent graph
graph = StateGraph(AgentState)
graph.add_node("test_triage", model_call, retry_policy=rate_limit_retry)
graph.add_node("tools", tool_node)
graph.set_entry_point("test_triage")
graph.add_conditional_edges(
    "test_triage",
    should_continue,
    {"continue": "tools", "end": END},
)
graph.add_edge("tools", "test_triage")
agent = graph.compile()
