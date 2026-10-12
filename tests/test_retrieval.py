import tempfile
import sys
import unittest
from pathlib import Path

from mathernet.errors import RetrievalError
from mathernet.retrieval import (
    CachingSearchProvider,
    MCPStdioClient,
    SearchResult,
    StaticSearchProvider,
    filter_approved_sources,
    parse_search_results,
)


class RetrievalTests(unittest.TestCase):
    def test_parses_common_mcp_result_fields(self):
        results = parse_search_results(
            {
                "items": [
                    {
                        "name": "A source",
                        "link": "https://example.com/a",
                        "source": "Example University",
                        "snippet": "An excerpt",
                    }
                ]
            }
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "A source")

    def test_filters_to_approved_publishers(self):
        results = [
            SearchResult("Trusted", "https://a.example", "Wikipedia", "excerpt"),
            SearchResult("Untrusted", "https://b.example", "Unknown Blog", "excerpt"),
        ]
        filtered = filter_approved_sources(results, ("Wikipedia",))
        self.assertEqual([result.title for result in filtered], ["Trusted"])

    def test_mcp_stdio_calls_search_tool(self):
        fixture = Path(__file__).parent / "fixtures" / "fake_mcp_server.py"
        with MCPStdioClient((sys.executable, str(fixture)), tool_name="search") as client:
            results = client.search("quadratic formula")
        self.assertEqual(results[0].title, "Quadratic formula")
        self.assertEqual(results[0].publisher, "Wikipedia")

    def test_cached_sources_are_used_when_retrieval_is_unavailable(self):
        class UnavailableProvider:
            def search(self, query, limit=5):
                raise RetrievalError("offline")

        result = SearchResult(
            "Quadratic formula",
            "https://example.edu/quadratic",
            "Example University",
            "A cached authoritative excerpt.",
        )
        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / "search_cache.json"
            online = CachingSearchProvider(StaticSearchProvider([result]), cache_path)
            self.assertEqual(online.search("Quadratic formula")[0].url, result.url)

            offline = CachingSearchProvider(UnavailableProvider(), cache_path)
            cached = offline.search("Quadratic formula")
        self.assertEqual(cached, [result])

    def test_cached_sources_are_used_when_server_cannot_start(self):
        class UnstartableProvider:
            def __enter__(self):
                raise RetrievalError("server unavailable")

            def search(self, query, limit=5):
                raise AssertionError("search must not run after startup failure")

        result = SearchResult(
            "Cached formula",
            "https://example.edu/cached",
            "Example University",
            "A cached excerpt.",
        )
        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / "search_cache.json"
            CachingSearchProvider(StaticSearchProvider([result]), cache_path).search(
                "Cached formula"
            )
            with CachingSearchProvider(UnstartableProvider(), cache_path) as provider:
                cached = provider.search("Cached formula")
        self.assertEqual(cached, [result])


if __name__ == "__main__":
    unittest.main()
