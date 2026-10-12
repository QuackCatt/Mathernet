import json
import tempfile
import unittest
from pathlib import Path

from mathernet.errors import StorageError, ValidationError
from mathernet.models import GraphDocument, SourceRecord
from mathernet.storage import JsonGraphStore
from mathernet.normalization import latex_to_ascii


ROOT = Path(__file__).resolve().parents[1]


class ModelsAndStorageTests(unittest.TestCase):
    def test_demo_graph_round_trip(self):
        payload = json.loads((ROOT / "examples" / "demo_graph.json").read_text(encoding="utf-8"))
        document = GraphDocument.from_dict(payload)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "graph.json"
            store = JsonGraphStore(path)
            store.save(document)
            loaded = store.load()
        self.assertEqual(document.to_dict(), loaded.to_dict())

    def test_invalid_source_is_rejected(self):
        with self.assertRaises(ValidationError):
            SourceRecord.from_dict(
                {
                    "id": "bad",
                    "title": "Bad",
                    "url": "not a URL",
                    "publisher": "Unknown",
                    "retrieved_at": "2026-10-12T00:00:00+00:00",
                    "excerpt": "text",
                }
            )

    def test_corrupt_json_reports_storage_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "graph.json"
            path.write_text("{broken", encoding="utf-8")
            with self.assertRaises(StorageError):
                JsonGraphStore(path).load()

    def test_latex_display_uses_terminal_friendly_notation(self):
        self.assertEqual(latex_to_ascii(r"e^{i\pi}+1=0"), "e^(ipi)+1=0")
        self.assertEqual(
            latex_to_ascii(r"\text{quadratic formula}"),
            "quadratic formula",
        )


if __name__ == "__main__":
    unittest.main()
