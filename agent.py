"""J.A.R.V.I.S agent core.

Builds a LangChain tool-calling agent backed by Groq and exposes a few
practical tools so it can actually carry out tasks (search the web, look
things up on Wikipedia, do math, tell the time/date).
"""

from __future__ import annotations

import ast
import math
import operator as op
from datetime import datetime
from typing import List, Tuple

from langchain_core.messages import BaseMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import tool
from langchain_groq import ChatGroq

# LangChain 1.x moved the classic agent runtime to `langchain_classic`.
# Fall back to `langchain.agents` for older installs.
try:
    from langchain_classic.agents import AgentExecutor, create_tool_calling_agent
except ImportError:  # pragma: no cover
    from langchain.agents import AgentExecutor, create_tool_calling_agent

DEFAULT_MODEL = "llama-3.3-70b-versatile"

SYSTEM_PROMPT = (
    "You are J.A.R.V.I.S. (Just A Rather Very Intelligent System), a highly "
    "capable personal AI assistant in the style of Tony Stark's JARVIS. You are "
    "polite, precise, confident and a little witty, and you address the user as "
    "'Sir' occasionally but never overdo it.\n\n"
    "Your job is to get tasks done. When a task needs up-to-date facts, a "
    "calculation, a definition, or a lookup, ALWAYS use the appropriate tool "
    "instead of guessing. Reason step by step internally, then give a clear, "
    "well-structured final answer. If a request is ambiguous, make a sensible "
    "assumption and state it. Keep answers focused and useful."
)

# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #

# Operators allowed in the safe calculator.
_ALLOWED_OPS = {
    ast.Add: op.add,
    ast.Sub: op.sub,
    ast.Mult: op.mul,
    ast.Div: op.truediv,
    ast.FloorDiv: op.floordiv,
    ast.Mod: op.mod,
    ast.Pow: op.pow,
    ast.USub: op.neg,
    ast.UAdd: op.pos,
}

_ALLOWED_FUNCS = {
    "abs": abs, "round": round, "min": min, "max": max, "sum": sum,
    "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "log": math.log, "log10": math.log10, "exp": math.exp, "pow": math.pow,
    "floor": math.floor, "ceil": math.ceil, "pi": math.pi, "e": math.e,
}


def _eval_node(node: ast.AST):
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_OPS:
        return _ALLOWED_OPS[type(node.op)](_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_OPS:
        return _ALLOWED_OPS[type(node.op)](_eval_node(node.operand))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        fn = _ALLOWED_FUNCS.get(node.func.id)
        if fn is None or not callable(fn):
            raise ValueError(f"function not allowed: {node.func.id}")
        return fn(*[_eval_node(a) for a in node.args])
    if isinstance(node, ast.Name) and node.id in _ALLOWED_FUNCS:
        val = _ALLOWED_FUNCS[node.id]
        if not callable(val):
            return val
        raise ValueError(f"cannot use {node.id} without calling it")
    raise ValueError("unsupported expression")


@tool
def calculator(expression: str) -> str:
    """Evaluate a math expression. Supports + - * / // % **, parentheses and
    the functions sqrt, sin, cos, tan, log, log10, exp, abs, round, min, max,
    sum, floor, ceil, and constants pi and e. Example: 'sqrt(144) + 3*5'."""
    try:
        tree = ast.parse(expression.strip(), mode="eval")
        result = _eval_node(tree)
        return f"{expression} = {result}"
    except Exception as exc:  # noqa: BLE001
        return f"Could not evaluate '{expression}': {exc}"


@tool
def current_datetime() -> str:
    """Return the current local date and time, plus the weekday."""
    now = datetime.now()
    return now.strftime("It is %I:%M %p on %A, %d %B %Y (local time).")


@tool
def web_search(query: str) -> str:
    """Search the web for current information (news, facts, prices, docs).
    Use this whenever the answer may have changed recently or you are unsure."""
    try:
        from langchain_community.tools import DuckDuckGoSearchRun

        return DuckDuckGoSearchRun().run(query)
    except Exception as exc:  # noqa: BLE001
        return f"Web search failed: {exc}"


@tool
def wikipedia_lookup(query: str) -> str:
    """Look up a summary of a topic, person, place or concept on Wikipedia."""
    try:
        from langchain_community.tools import WikipediaQueryRun
        from langchain_community.utilities import WikipediaAPIWrapper

        wiki = WikipediaQueryRun(api_wrapper=WikipediaAPIWrapper(lang="en", top_k_results=1))
        return wiki.run(query)
    except Exception as exc:  # noqa: BLE001
        return f"Wikipedia lookup failed: {exc}"


def get_tools() -> list:
    return [calculator, current_datetime, web_search, wikipedia_lookup]


# --------------------------------------------------------------------------- #
# Agent construction
# --------------------------------------------------------------------------- #

def build_agent(api_key: str, model: str = DEFAULT_MODEL) -> AgentExecutor:
    """Create a ready-to-run AgentExecutor for the given Groq API key."""
    llm = ChatGroq(
        model=model,
        temperature=0.2,
        groq_api_key=api_key,
        streaming=False,
    )

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", SYSTEM_PROMPT),
            MessagesPlaceholder(variable_name="chat_history", optional=True),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ]
    )

    agent = create_tool_calling_agent(llm, get_tools(), prompt)
    return AgentExecutor(
        agent=agent,
        tools=get_tools(),
        verbose=False,
        max_iterations=6,
        handle_parsing_errors=True,
        return_intermediate_steps=True,
    )


def run_agent(
    executor: AgentExecutor,
    user_input: str,
    chat_history: List[BaseMessage] | None = None,
) -> Tuple[str, list]:
    """Run the agent and return (final_answer, intermediate_steps)."""
    result = executor.invoke(
        {"input": user_input, "chat_history": chat_history or []}
    )
    return result.get("output", ""), result.get("intermediate_steps", [])


# --------------------------------------------------------------------------- #
# Speech-to-text (voice input) via Groq Whisper
# --------------------------------------------------------------------------- #

WHISPER_MODEL = "whisper-large-v3-turbo"


CHAT_MODEL_PREFIXES = (
    "llama-", "meta-llama", "openai/gpt-oss", "qwen", "kimi", "mistral", "gemma",
)


def list_chat_models(api_key: str) -> list:
    """Return Groq chat model IDs that this key can actually use (live from API)."""
    from groq import Groq

    client = Groq(api_key=api_key)
    ids = []
    for m in client.models.list().data:
        mid = getattr(m, "id", "") or ""
        low = mid.lower()
        if any(low.startswith(p) for p in CHAT_MODEL_PREFIXES):
            ids.append(mid)
    return sorted(ids)


def transcribe_audio(
    audio_bytes: bytes,
    api_key: str,
    filename: str = "audio.wav",
    model: str = WHISPER_MODEL,
    language: str = "en",
) -> str:
    """Transcribe recorded audio to text using Groq's Whisper endpoint."""
    from groq import Groq

    client = Groq(api_key=api_key)
    result = client.audio.transcriptions.create(
        file=(filename, audio_bytes),
        model=model,
        language=language,
    )
    return (result.text or "").strip()
