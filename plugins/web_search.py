"""
plugins/web_search.py
---------------------
Web search plugin using DuckDuckGo with LLM summarization.

Capabilities:
- Search the web via DuckDuckGo
- Fetch top 3 results with title, snippet, and URL
- Summarize results using Groq LLM

This plugin uses the duckduckgo-search package (free, no API key required).
Results are passed to the AI brain for natural language summarization.
"""

import logging
import re
from typing import Dict, Any

logger = logging.getLogger(__name__)


# Short conversational fragments that follow "what's"/"what is" but are chit-chat, not searches.
_CHITCHAT = {"up", "new", "wrong", "happening", "going on", "good", "cooking", "the matter", "the time", "the date", "today", "time", "date"}


def _extract_search_query(text: str) -> str:
    """
    Extract the search query from a voice command.

    Returns "" when `text` is not really a search request, so the caller can
    decline and let the AI brain handle it. The patterns are anchored at the
    start of the sentence: "what is Ohm's law" is a search, but "can you tell
    me what is on your mind" is not, and neither is "what's your name".
    """
    text_lower = text.lower().strip()

    patterns = [
        r"^(?:please\s+)?(?:search|look up|look for|find)(?:\s+(?:the web|the internet|online|google))?(?:\s+for)?\s+(.+)$",
        r"^(?:what is|what's|what are|what were)\s+(?:a |an |the )?(.+)$",
        r"^(?:who is|who's|who was)\s+(.+)$",
        r"^(?:the )?(?:latest )?news (?:about|on)\s+(.+)$",
        r"^(?:latest news about|news about)\s+(.+)$",
    ]

    query = ""
    for pattern in patterns:
        match = re.search(pattern, text_lower)
        if match:
            query = match.group(1).strip(" ?.!,")
            break

    if not query or query in _CHITCHAT:
        return ""
    # Questions about the assistant itself ("what is your name", "who are you") aren't web searches.
    if re.match(r"^(?:your|you|you're|yours)\b", query):
        return ""
    return query


def _fetch_duckduckgo_results(query: str, max_results: int = 3) -> list[Dict[str, str]]:
    """
    Fetch search results from DuckDuckGo.

    Args:
        query: Search query string
        max_results: Number of results to return (default: 3)

    Returns:
        List of dicts with 'title', 'snippet', and 'url' keys
    """
    try:
        try:
            from ddgs import DDGS  # current package name
        except ImportError:
            from duckduckgo_search import DDGS  # legacy name

        results = []
        with DDGS() as ddgs:
            for result in ddgs.text(query, max_results=max_results):
                results.append({
                    "title": result.get("title", ""),
                    "snippet": result.get("body", ""),
                    "url": result.get("href", ""),
                })
        return results
    except ImportError:
        logger.error("DuckDuckGo search library not installed. Install with: pip install duckduckgo-search")
        return []
    except Exception as e:
        logger.error(f"DuckDuckGo search error: {e}")
        return []


def _format_results_for_llm(query: str, results: list[Dict[str, str]]) -> str:
    """Format search results for LLM summarization."""
    if not results:
        return f"No results found for '{query}'."

    formatted = f"Search query: {query}\n\nTop {len(results)} results:\n"
    for i, result in enumerate(results, 1):
        formatted += f"\n{i}. {result.get('title', 'Untitled')}\n"
        formatted += f"   {result.get('snippet', 'No snippet available')}\n"
        formatted += f"   URL: {result.get('url', 'No URL')}\n"

    return formatted


def _fallback_readout(query: str, results: list[Dict[str, str]]) -> str:
    """Spoken answer built straight from the top result when no LLM is available."""
    top = results[0]
    title = (top.get("title") or "").strip()
    snippet = (top.get("snippet") or "").strip()
    if len(snippet) > 300:
        snippet = snippet[:300].rsplit(" ", 1)[0] + "..."
    return f"Here is the top result for {query}. {title}. {snippet}".strip()


def execute(
    text: str,
    config: Dict[str, Any] | None = None,
    trigger: Dict[str, Any] | None = None,
    alarm_manager=None,
    handler=None,
) -> str:
    """
    Execute web search plugin.

    Extracts query, fetches DuckDuckGo results, and has the LLM summarize them.

    Args:
        text: User input text
        config: Configuration dict
        trigger: Trigger metadata
        alarm_manager: Alarm manager instance
        handler: CommandHandler instance

    Returns:
        A spoken summary, or "" if the text isn't a web-search request (so the
        assistant falls through to the AI brain).
    """
    try:
        query = _extract_search_query(text)
        if not query or len(query) < 2:
            return ""

        logger.info(f"Web search plugin: searching for '{query}'")

        results = _fetch_duckduckgo_results(query, max_results=3)
        if not results:
            return f"I couldn't find any web results for '{query}'. Please try a different search term."

        formatted_results = _format_results_for_llm(query, results)
        logger.debug(f"Search results:\n{formatted_results}")

        # Reuse the live brain when the handler has one; otherwise build a lightweight
        # one with RAG off (a full AIBrain reloads the embedding model and would write
        # this search into the user's long-term memory).
        from ai_brain import AIBrain

        brain = getattr(handler, "brain", None) or AIBrain(config or {}, enable_rag=False)
        summary = brain.complete(
            "Using only these search results, answer in at most 3 short spoken sentences. "
            "No lists, no URLs.\n\n" + formatted_results
        )

        return summary or _fallback_readout(query, results)

    except Exception as e:
        logger.exception(f"Web search plugin error: {e}")
        return "Web search ran into a problem. Please try again in a moment."


# Plugin discovery / registration hints
TRIGGERS = [
    {
        "name": "web_search",
        "description": "Search the web using DuckDuckGo",
        "phrases": [
            "search for",
            "what is",
            "what's",
            "latest news about",
            "news about",
            "look up",
            "who is",
            "who's",
            "what are",
        ],
        "handler": "web_search",
    },
]
