from src.tools.search import SearchTool


class TestSearchTool:
    def test_returns_normalized_snippets(self, monkeypatch):
        data = [
            {"title": "XGBoost Explained", "body": "A powerful boosting algo.", "href": "https://x.com"},
            {"title": "Gradient Boosting", "body": "Ensemble technique.", "href": "https://y.com"},
        ]

        class FakeDDGS:
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def text(self, _q, max_results=5): return data  # noqa: ARG002

        monkeypatch.setattr("src.tools.search.DDGS", FakeDDGS)  # ddgs.DDGS re-exported in search.py
        tool = SearchTool()
        results = tool.query("gradient boosting")
        assert len(results) == 2
        assert results[0].startswith("Title: XGBoost Explained")
        assert "Snippet:" in results[0]

    def test_returns_fallback_on_error(self, monkeypatch):
        call_count = {"n": 0}

        class FakeDDGS:
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def text(self, _q, max_results=5):  # noqa: ARG002
                call_count["n"] += 1
                raise RuntimeError("connection error")

        monkeypatch.setattr("src.tools.search.DDGS", FakeDDGS)  # ddgs.DDGS re-exported in search.py
        monkeypatch.setattr("time.sleep", lambda s: None)
        tool = SearchTool()
        result = tool.query("test query")
        assert result == ["search unavailable"]
        assert call_count["n"] == 3  # retried 3 times

    def test_returns_no_results_on_empty(self, monkeypatch):
        class FakeDDGS:
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def text(self, _q, max_results=5): return []  # noqa: ARG002

        monkeypatch.setattr("src.tools.search.DDGS", FakeDDGS)  # ddgs.DDGS re-exported in search.py
        tool = SearchTool()
        result = tool.query("obscure topic xyz123")
        assert result == ["no results found for this query"]

    def test_sanitizes_query(self, monkeypatch):
        captured = {}

        class FakeDDGS:
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def text(self, q, **_kw):
                captured["q"] = q
                return []

        monkeypatch.setattr("src.tools.search.DDGS", FakeDDGS)  # ddgs.DDGS re-exported in search.py
        tool = SearchTool()
        tool.query("hello\nworld\t!")
        assert "\n" not in captured["q"]
        assert "\t" not in captured["q"]
