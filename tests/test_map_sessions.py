import tempfile
import unittest
from pathlib import Path

from mathernet.api import handle_api_request
from mathernet.map_sessions import MapSessionStore
from mathernet.models import AIModule, SourceRecord
from mathernet.repository import GraphRepository
from mathernet.services import MathernetService


class MapSessionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.repository = GraphRepository(root / "graph.json")
        self.repository.add_or_update_source(
            SourceRecord(
                "src_map",
                "Map source",
                "https://example.edu/map",
                "Example University",
                "2026-10-15T00:00:00+00:00",
                "Verified source excerpt",
            )
        )
        self.formula = self.repository.add_formula(
            formula_id="formula_map",
            name="Map formula",
            latex="x=y",
            aliases=["map formula"],
            topic_tags=["algebra"],
            ai_module=AIModule("summary", "explanation"),
            sources=["src_map"],
        )
        self.repository.save()
        self.map_sessions = MapSessionStore(root / "map_sessions.json")
        self.service = MathernetService(self.repository, map_sessions=self.map_sessions)

    def tearDown(self):
        self.temporary.cleanup()

    def test_default_map_contains_existing_formulas(self):
        payload = self.service.list_map_sessions()
        self.assertEqual(payload["sessions"][0]["name"], "Main map")
        self.assertEqual(payload["sessions"][0]["formula_count"], 1)

    def test_create_add_pin_rename_and_delete_session(self):
        created = self.service.create_map_session("Probability")
        added = self.service.add_formula_to_map_session(created["id"], self.formula.id)
        self.assertTrue(added["added"])

        pinned = self.service.update_map_session(created["id"], pinned=True)
        self.assertTrue(pinned["pinned"])
        renamed = self.service.update_map_session(created["id"], name="Probability review")
        self.assertEqual(renamed["name"], "Probability review")

        graph = self.service.get_map_graph(created["id"])
        self.assertEqual([item["id"] for item in graph["nodes"]], [self.formula.id])
        self.service.delete_map_session(created["id"])
        self.assertNotIn(created["id"], [item["id"] for item in self.service.list_map_sessions()["sessions"]])

    def test_formula_deletion_removes_it_from_every_map(self):
        self.service.list_map_sessions()
        secondary = self.service.create_map_session("Secondary")
        self.service.add_formula_to_map_session(secondary["id"], self.formula.id)

        response = handle_api_request(
            self.service,
            "DELETE",
            f"/api/formulas/{self.formula.id}",
        )

        self.assertEqual(response.status, 200)
        self.assertEqual(response.payload["removed_from_maps"], 2)
        self.assertIsNone(self.repository.find_formula(self.formula.id))
        self.assertEqual(self.service.get_map_graph(secondary["id"])["nodes"], [])


if __name__ == "__main__":
    unittest.main()
