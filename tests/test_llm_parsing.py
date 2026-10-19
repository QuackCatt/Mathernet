import json
import unittest

from mathernet.errors import SynthesisError
from mathernet.gateway import _extract_provider_text
from mathernet.llm import parse_synthesis_result


class LlmParsingTests(unittest.TestCase):
    def test_parses_nested_camel_case_openrouter_style_result(self):
        raw = json.dumps({
            "id": "response-1",
            "result": {
                "formulaName": "Euler's identity",
                "formulaLatex": "e^{i\\\\pi}+1=0",
                "topicTags": ["complex analysis"],
                "aiModule": {
                    "summary": "A compact identity.",
                    "explanation": "It links five constants.",
                    "derivationSteps": ["Use Euler's formula."],
                },
                "dependencies": [{
                    "prerequisiteName": "Euler's formula",
                    "relation": "derivation_basis",
                    "rationale": "Direct specialization.",
                    "sourceUrls": ["https://example.edu/euler"],
                }],
                "sources": [{
                    "title": "Euler source",
                    "url": "https://example.edu/euler",
                    "publisher": "Example University",
                    "excerpt": "Identity excerpt",
                }],
            },
        })
        result = parse_synthesis_result(raw)
        self.assertEqual(result.name, "Euler's identity")
        self.assertEqual(result.ai_module.summary, "A compact identity.")
        self.assertEqual(result.dependencies[0].prerequisite_name, "Euler's formula")
        self.assertEqual(result.sources[0].url, "https://example.edu/euler")

    def test_builds_ai_module_from_top_level_summary_and_explanation(self):
        result = parse_synthesis_result(json.dumps({
            "name": "Quadratic formula",
            "latex": "x=1",
            "summary": "Summary",
            "explanation": "Explanation",
        }))
        self.assertEqual(result.ai_module.summary, "Summary")
        self.assertEqual(result.ai_module.explanation, "Explanation")

    def test_extracts_content_blocks_and_tool_arguments(self):
        text = _extract_provider_text({
            "choices": [{
                "message": {
                    "content": [
                        {"type": "text", "text": '{"name":"A","ai_module":'},
                        {"type": "text", "text": '{"summary":"S","explanation":"E"}}'},
                    ],
                }
            }]
        })
        self.assertIn('"ai_module"', text)

        tool_text = _extract_provider_text({
            "content": [{
                "type": "tool_use",
                "input": {"name": "B", "ai_module": {"summary": "S", "explanation": "E"}},
            }]
        })
        self.assertIn('"name": "B"', tool_text)

    def test_extracts_openrouter_reasoning_fields_when_final_content_is_empty(self):
        text = _extract_provider_text({
            "choices": [{
                "finish_reason": "stop",
                "message": {
                    "content": "",
                    "reasoning": "",
                    "reasoning_details": [
                        {"type": "reasoning.text", "text": '{"name":"A","ai_module":'},
                        {"type": "reasoning.text", "text": '{"summary":"S","explanation":"E"}}'},
                    ],
                },
            }]
        })
        self.assertIn('"ai_module"', text)

        reasoning_content = _extract_provider_text({
            "choices": [{
                "message": {
                    "content": None,
                    "reasoning_content": '{"name":"B","ai_module":{"summary":"S","explanation":"E"}}',
                }
            }]
        })
        self.assertIn('"name":"B"', reasoning_content)

    def test_reports_provider_errors_and_empty_finish_reason(self):
        with self.assertRaises(SynthesisError) as raised:
            _extract_provider_text({"error": {"message": "route is temporarily unavailable"}})
        self.assertIn("route is temporarily unavailable", str(raised.exception))

        with self.assertRaises(SynthesisError) as raised:
            _extract_provider_text({"choices": [{"finish_reason": "length", "message": {"content": ""}}]})
        self.assertIn("finish_reason=length", str(raised.exception))

    def test_error_lists_received_top_level_fields(self):
        with self.assertRaises(SynthesisError) as raised:
            parse_synthesis_result(json.dumps({"answer": "hello", "usage": {}}))
        self.assertIn("answer", str(raised.exception))
        self.assertIn("usage", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
