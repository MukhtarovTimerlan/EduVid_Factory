import os
import re
import time

from ddgs import DDGS

_MAX_QUERY_LEN = 100
_MAX_SNIPPETS = 5
_MAX_SNIPPET_LEN = 500
_RETRY_BACKOFF = (1, 2, 4)

_CONTROL_CHARS_RE = re.compile(r"[\n\r\t]")


class SearchTool:
    """Wraps DuckDuckGo Search. Free, no API key required. Never raises on transient failures."""

    def __init__(self, logger=None) -> None:
        self._n_results = int(os.environ.get("SEARCH_N_RESULTS", str(_MAX_SNIPPETS)))
        self._logger = logger

    def query(self, q: str, n: int | None = None) -> list[str]:
        """
        Execute web search via DuckDuckGo. Returns normalized snippets.
        Never raises for transient errors — returns ["search unavailable"].
        """
        n = n or self._n_results
        q = self._sanitize_query(q)
        if not q:
            return ["no results found for this query"]

        for attempt, delay in enumerate(_RETRY_BACKOFF, 1):
            try:
                self._log("info", f'search query: "{q}"')
                with DDGS() as ddgs:
                    results = list(ddgs.text(q, max_results=n))
                snippets = self._normalize(results)
                self._log(
                    "info",
                    f"search results: {len(snippets)} snippets, "
                    f"{sum(len(s) for s in snippets)} chars",
                )
                return snippets if snippets else ["no results found for this query"]

            except Exception as e:  # noqa: BLE001
                self._log("warning", f"search retry {attempt}/3: {e}")
                if attempt < len(_RETRY_BACKOFF):
                    time.sleep(delay)

        self._log("error", "search unavailable after 3 retries")
        return ["search unavailable"]

    # ── private ───────────────────────────────────────────────────────────────

    def _sanitize_query(self, q: str) -> str:
        q = _CONTROL_CHARS_RE.sub(" ", q).strip()
        return q[:_MAX_QUERY_LEN]

    def _normalize(self, items: list[dict]) -> list[str]:
        snippets = []
        for item in items[:_MAX_SNIPPETS]:
            title = item.get("title", "")
            snippet = item.get("body", "")
            text = f"Title: {title} | Snippet: {snippet}"
            snippets.append(text[:_MAX_SNIPPET_LEN])
        return snippets

    def _log(self, level: str, msg: str) -> None:
        if self._logger:
            getattr(self._logger, level)(msg)
