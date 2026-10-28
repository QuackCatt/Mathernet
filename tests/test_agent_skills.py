import json
import tempfile
import unittest
from pathlib import Path

from mathernet.agent import FormulaAgent, stable_id
from mathernet.agent_skills import (
    AI_SAFETY_POLICY,
    FORMULA_RELATIONSHIP_SKILL,
    FORMULA_SYNTHESIS_SKILL,
    FormulaDiscovery,
    FormulaCandidate,
    build_formula_chat_prompt,
    build_relationship_deep_dive_prompt,
    load_agent_skill,
    parse_formula_discovery,
    parse_formula_candidates,
    parse_relationship_validation,
)
from mathernet.errors import SynthesisError
from mathernet.llm import SynthesisResult
from mathernet.models import AIModule
from mathernet.normalization import formula_key
from mathernet.repository import GraphRepository


class DiscoverySynthesizer:
    def __init__(self, discovery, result=None):
        self.discovery = discovery
        self.result = result
        self.discovery_calls = []
        self.synthesis_calls = []

    def discover_formula(self, query, library):
        self.discovery_calls.append((query, library))
        return self.discovery

    def synthesize(self, query, sources, map_context=None):
        self.synthesis_calls.append((query, sources))
        if self.result is None:
            raise AssertionError("synthesis must not run")
        return self.result


class AgentSkillTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.repository = GraphRepository(Path(self.temporary.name) / "graph.json")

    def tearDown(self):
        self.temporary.cleanup()

    def add_formula(self, formula_id, name, aliases):
        return self.repository.add_formula(
            formula_id=formula_id,
            name=name,
            latex="x=1",
            aliases=aliases,
            topic_tags=["algebra"],
            ai_module=AIModule("summary"),
            sources=[],
        )

    def test_parses_formula_discovery_skill_output(self):
        discovery = parse_formula_discovery(json.dumps({
            "canonical_name": "Quadratic formula",
            "local_formula_id": "formula_quadratic",
            "aliases": ["roots of a quadratic"],
            "confidence": 0.94,
            "reason": "Same canonical formula.",
        }))
        self.assertIsInstance(discovery, FormulaDiscovery)
        self.assertEqual(discovery.local_formula_id, "formula_quadratic")
        self.assertEqual(discovery.aliases, ["roots of a quadratic"])
        self.assertEqual(discovery.confidence, 0.94)

    def test_deep_dive_skill_file_contains_optional_topic_and_latex_rules(self):
        skill = load_agent_skill("formula_deep_dive")
        self.assertIn("Read these instructions before generating", skill)
        self.assertIn("Omit a topic instead of padding the article", skill)
        self.assertIn("single dollar delimiters", skill)
        self.assertIn("Never invent citations", skill)
        self.assertIn("one initial deep dive automatically", skill)

    def test_parses_relationship_validation_and_drops_invalid_sources(self):
        parsed = parse_relationship_validation(json.dumps({
            "explanation_is_reasonable": True,
            "web_supported": False,
            "assessment": "The explanation is mathematically coherent.",
            "sources": [
                {"title": "Valid", "url": "https://example.edu/a", "publisher": "Example", "excerpt": "Text"},
                {"title": "Invalid", "url": "javascript:alert(1)", "publisher": "Example", "excerpt": "Text"},
            ],
        }))
        self.assertTrue(parsed["explanation_is_reasonable"])
        self.assertFalse(parsed["web_supported"])
        self.assertEqual(len(parsed["sources"]), 1)

    def test_confirmed_manual_relationship_prompt_includes_learner_note(self):
        prompt = json.loads(build_relationship_deep_dive_prompt(
            {
                "id": "edge_manual",
                "created_by": "manual",
                "relation": "special_case",
                "rationale": "This is my explanation of the special case.",
                "evidence_status": "supported",
            },
            [],
        ))

        self.assertEqual(
            prompt["relationship"]["learner_note"],
            "This is my explanation of the special case.",
        )
        self.assertNotIn("rationale", prompt["relationship"])
        self.assertIn("AI-confirmed manual relationship", prompt["task"])

    def test_confirmed_manual_relationship_prompt_omits_empty_learner_note(self):
        prompt = json.loads(build_relationship_deep_dive_prompt(
            {
                "id": "edge_manual",
                "created_by": "manual",
                "relation": "special_case",
                "rationale": "",
                "evidence_status": "supported",
            },
            [],
        ))

        self.assertNotIn("learner_note", prompt["relationship"])
        self.assertNotIn("rationale", prompt["relationship"])

    def test_parses_one_to_five_distinct_formula_candidates(self):
        candidates = parse_formula_candidates(json.dumps({
            "candidates": [
                {
                    "canonical_name": "Normal distribution",
                    "latex": "f(x)=\\frac{1}{\\sigma\\sqrt{2\\pi}}e^{-\\frac{(x-\\mu)^2}{2\\sigma^2}}",
                    "summary": "A continuous probability distribution.",
                    "topic": "probability",
                    "reason": "Matches the distribution description.",
                    "confidence": 0.92,
                    "local_formula_id": "formula_normal",
                },
                {
                    "canonical_name": "Normal distribution",
                    "latex": "f(x)=...",
                    "summary": "Duplicate.",
                    "topic": "probability",
                    "reason": "Duplicate.",
                    "confidence": 0.5,
                    "local_formula_id": "",
                },
            ],
        }))

        self.assertEqual(len(candidates), 1)
        self.assertIsInstance(candidates[0], FormulaCandidate)
        self.assertEqual(candidates[0].local_formula_id, "formula_normal")

    def test_formula_candidate_parser_rejects_empty_results(self):
        with self.assertRaises(SynthesisError):
            parse_formula_candidates(json.dumps({"candidates": []}))

    def test_formula_candidate_parser_rejects_answers_instead_of_formulas(self):
        with self.assertRaises(SynthesisError):
            parse_formula_candidates(json.dumps({
                "candidates": [{
                    "canonical_name": "Answer",
                    "latex": "42",
                    "summary": "The final answer is 42.",
                    "topic": "algebra",
                    "reason": "Solves the learner's question.",
                    "confidence": 1,
                    "local_formula_id": "",
                }],
            }))

    def test_chat_context_compresses_old_messages_but_keeps_initial_article(self):
        article = {
            "title": "Original explanation",
            "article": {
                "introduction": "This exact opening explanation must remain clear.",
                "sections": [],
            },
            "sources": [],
        }
        messages = [
            {"role": "user" if index % 2 == 0 else "assistant", "content": f"history {index} " + "x" * 400}
            for index in range(12)
        ]
        messages.append({"role": "user", "content": "Continue explaining the formula."})

        prompt = json.loads(build_formula_chat_prompt(
            {"id": "formula_test", "name": "Test formula"},
            article,
            messages,
        ))

        self.assertEqual(prompt["immutable_deep_dive_article"], article)
        self.assertEqual(prompt["latest_message"]["content"], "Continue explaining the formula.")
        self.assertGreater(len(prompt["conversation_context"]["older_message_digest"]), 0)
        self.assertLess(
            len(prompt["conversation_context"]["older_message_digest"][0]["content"]),
            400,
        )
        self.assertIn("never compress or omit", " ".join(prompt["context_priority"]))

    def test_safety_policy_forbids_concrete_problem_solutions(self):
        self.assertIn("Never solve, complete, grade, or check", AI_SAFETY_POLICY)

    def test_formula_prompts_require_renderable_latex_delimiters(self):
        self.assertIn("single dollar delimiters", FORMULA_SYNTHESIS_SKILL)
        self.assertIn("single dollar delimiters", FORMULA_RELATIONSHIP_SKILL)

    def test_discovery_opens_an_existing_card_before_synthesis(self):
        existing = self.add_formula("formula_existing", "Existing formula", ["local alias"])
        synthesizer = DiscoverySynthesizer(
            FormulaDiscovery(
                canonical_name="Existing formula",
                local_formula_id=existing.id,
                confidence=0.99,
            )
        )
        agent = FormulaAgent(self.repository, synthesizer)

        result = agent.learn("the formula described by the learner")

        self.assertFalse(result.created)
        self.assertEqual(result.node.id, existing.id)
        self.assertEqual(synthesizer.synthesis_calls, [])

    def test_post_synthesis_match_never_creates_a_duplicate(self):
        existing = self.add_formula("formula_existing", "Existing formula", ["alternate name"])
        synthesizer = DiscoverySynthesizer(
            FormulaDiscovery(canonical_name="Unmatched description"),
            SynthesisResult(
                name="Existing formula",
                latex="x=1",
                aliases=["alternate name"],
                topic_tags=["algebra"],
                ai_module=AIModule("summary"),
            ),
        )
        agent = FormulaAgent(self.repository, synthesizer)

        result = agent.learn("a description that resolves later")

        self.assertFalse(result.created)
        self.assertEqual(result.node.id, existing.id)
        self.assertEqual(len(self.repository.list_formulas()), 1)

    def test_new_formula_uses_canonical_identity_and_keeps_query_alias(self):
        synthesizer = DiscoverySynthesizer(
            FormulaDiscovery(
                canonical_name="Quadratic formula",
                aliases=["roots of a quadratic"],
                confidence=0.91,
            ),
            SynthesisResult(
                name="Quadratic formula",
                latex="x=1",
                aliases=["abc formula"],
                topic_tags=["algebra"],
                ai_module=AIModule("summary"),
            ),
        )
        agent = FormulaAgent(self.repository, synthesizer)

        result = agent.learn("formula for the roots of ax^2+bx+c")

        self.assertTrue(result.created)
        self.assertEqual(result.node.id, stable_id("formula", formula_key("Quadratic formula")))
        self.assertIn("formula for the roots of ax^2+bx+c", result.node.aliases)
        self.assertIn("roots of a quadratic", result.node.aliases)

    def test_discovery_failure_falls_back_to_the_original_query(self):
        class FailingDiscovery:
            def discover_formula(self, query, library):
                raise SynthesisError("temporary discovery failure")

            def synthesize(self, query, sources, map_context=None):
                return SynthesisResult(
                    name=query,
                    latex="x=1",
                    aliases=[],
                    topic_tags=["algebra"],
                    ai_module=AIModule("summary"),
                )

        agent = FormulaAgent(self.repository, FailingDiscovery())
        result = agent.learn("fallback formula")
        self.assertTrue(result.created)
        self.assertEqual(result.node.name, "fallback formula")


if __name__ == "__main__":
    unittest.main()
