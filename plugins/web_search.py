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


def _extract_search_query(text: str) -> str:
    """Extract search query from various voice command phrases."""
    text_lower = text.lower().strip()

    # Remove common trigger phrases
    patterns = [
        r"^(search for|search)\s+(.+)$",
        r"^(what is|what's)\s+(.+)$",
        r"^(latest news about|news about)\s+(.+)$",
        r"^(look up|look for)\s+(.+)$",
        r"^(who is|who's)\s+(.+)$",
        r"^(what are)\s+(.+)$",
    ]

    for pattern in patterns:
        match = re.search(pattern, text_lower)
        if match:
            return match.group(2).strip()

    # Fallback: return text after trigger phrase
    return text_lower


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
        from duckduckgo_search import DDGS

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
        logger.error("duckduckgo-search not installed. Install with: pip install duckduckgo-search")
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


def execute(
    text: str,
    config: Dict[str, Any] | None = None,
    trigger: Dict[str, Any] | None = None,
    alarm_manager=None,
    handler=None,
) -> str:
    """
    Execute web search plugin.

    Extracts query, fetches DuckDuckGo results, and passes to LLM for summarization.

    Args:
        text: User input text
        config: Configuration dict
        trigger: Trigger metadata
        alarm_manager: Alarm manager instance
        handler: CommandHandler instance

    Returns:
        LLM-generated summary of search results
    """
    try:
        # Extract search query from voice command
        query = _extract_search_query(text)
        if not query or len(query) < 2:
            return "I didn't catch the search query. Try: search for python programming."

        logger.info(f"Web search plugin: searching for '{query}'")

        # Fetch DuckDuckGo results
        results = _fetch_duckduckgo_results(query, max_results=3)
        if not results:
            return f"No search results found for '{query}'. Please try a different search term."

        # Format results for LLM
        formatted_results = _format_results_for_llm(query, results)
        logger.debug(f"Search results:\n{formatted_results}")

        # Pass to LLM for summarization
        from ai_brain import AIBrain

        # Create a temporary brain instance to avoid polluting the main brain's memory
        # Use the same config for consistency
        brain = AIBrain(config or {})
        summary_prompt = f"Summarize these search results in 3 sentences:\n\n{formatted_results}"
        summary = brain.ask(summary_prompt)

        return summary

    except Exception as e:
        logger.exception(f"Web search plugin error: {e}")
        return f"Web search encountered an error: {e}"


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
