import sys
import tempfile
import unittest
from pathlib import Path

from mathernet.api import handle_api_request
from mathernet.config import Settings
from mathernet.services import build_service


ROOT = Path(__file__).resolve().parents[1]


class LearningWorkflowTests(unittest.TestCase):
    def test_configured_mcp_and_offline_synthesis_create_a_persistent_card(self):
        fixture = ROOT / "tests" / "fixtures" / "fake_mcp_server.py"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(
                data_path=root / "graph.json",
                search_cache_path=root / "search_cache.json",
                mcp_transport="stdio",
                mcp_command=(sys.executable, str(fixture)),
                mcp_http_url="",
                mcp_tool_name="search",
                mcp_headers="",
                openai_api_key="",
                openai_model="test-model",
                approved_publishers=("Wikipedia",),
                request_timeout_seconds=5,
            )
            service = build_service(settings)

            created = handle_api_request(
                service,
                "POST",
                "/api/learn",
                {"query": "synthetic concept"},
            )
            self.assertEqual(created.status, 201)
            self.assertTrue(created.payload["created"])
            self.assertEqual(
                created.payload["formula"]["formula"]["name"],
                "synthetic concept",
            )
            self.assertEqual(len(created.payload["formula"]["sources"]), 1)
            self.assertIn(
                "does not propose dependency edges",
                created.payload["warnings"][0],
            )

            reused = handle_api_request(
                service,
                "POST",
                "/api/learn",
                {"query": "synthetic concept"},
            )
            self.assertEqual(reused.status, 200)
            self.assertFalse(reused.payload["created"])

            persisted = build_service(settings).get_formula_card("synthetic concept")
            self.assertEqual(
                persisted["formula"]["ai_module"]["summary"],
                created.payload["formula"]["formula"]["ai_module"]["summary"],
            )


if __name__ == "__main__":
    unittest.main()
