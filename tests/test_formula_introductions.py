import json
import tempfile
import unittest
from pathlib import Path

from mathernet.agent_skills import load_agent_skill, parse_formula_introduction
from mathernet.api import handle_api_request, openapi_document
from mathernet.errors import SynthesisError
from mathernet.formula_introductions import FormulaIntroductionStore
from mathernet.models import GraphDocument
from mathernet.repository import GraphRepository
from mathernet.services import MathernetService


ROOT = Path(__file__).resolve().parents[1]
INTRODUCTION = " ".join(f"term{number}" for number in range(1, 121))


class FakeIntroductionGateway:
    def __init__(self):
        self.calls = []

    def introduce(self, formula, sources):
        self.calls.append((formula, sources))
        return INTRODUCTION


class FormulaIntroductionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        payload = json.loads(
            (ROOT / "tests" / "fixtures" / "demo_graph.json").read_text(encoding="utf-8")
        )
        self.repository = GraphRepository(Path(self.temporary.name) / "graph.json")
        self.repository.document = GraphDocument.from_dict(payload)
        self.repository.save()
        self.gateway = FakeIntroductionGateway()
        self.introductions = FormulaIntroductionStore(
            Path(self.temporary.name) / "introductions.json"
        )
        self.service = MathernetService(
            self.repository,
            ai_gateway=self.gateway,
            formula_introductions=self.introductions,
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_skill_and_parser_require_a_substantial_introduction(self):
        skill = load_agent_skill("formula_introduction")
        self.assertIn("110-150 words", skill)
        self.assertIn("without turning the passage into a derivation", skill)
        self.assertIn("Use the model's built-in web search", skill)

        parsed = parse_formula_introduction(json.dumps({"introduction": INTRODUCTION}))
        self.assertEqual(parsed, INTRODUCTION)
        with self.assertRaises(SynthesisError):
            parse_formula_introduction(json.dumps({"introduction": "A short definition."}))

    def test_introduction_is_generated_once_then_reused(self):
        first = handle_api_request(
            self.service,
            "POST",
            "/api/formulas/formula_euler_identity/introduction",
            {},
        )
        second = handle_api_request(
            self.service,
            "POST",
            "/api/formulas/formula_euler_identity/introduction",
            {},
        )

        self.assertEqual(first.status, 200)
        self.assertFalse(first.payload["cached"])
        self.assertEqual(first.payload["introduction"], INTRODUCTION)
        self.assertTrue(second.payload["cached"])
        self.assertEqual(len(self.gateway.calls), 1)
        self.assertEqual(
            self.introductions.get("formula_euler_identity")["introduction"],
            INTRODUCTION,
        )

    def test_openapi_exposes_introduction_generation(self):
        self.assertIn(
            "/api/formulas/{formula_id}/introduction",
            openapi_document()["paths"],
        )


if __name__ == "__main__":
    unittest.main()
