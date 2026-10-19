from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from mathernet.evaluation import load_gold_cases
from tests.test_data import gold_cases


class GoldSuiteTests(unittest.TestCase):
    def test_synthetic_acceptance_cases_are_complete(self):
        cases = gold_cases()
        self.assertEqual(len(cases["dependency_chains"]), 1)
        self.assertEqual(len(cases["lookup_cases"]), 10)
        self.assertEqual(len(cases["safety_cases"]), 4)
        self.assertEqual(len(cases["persistence_assertions"]), 4)

    def test_gold_case_loader_accepts_only_generated_test_data(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cases.json"
            path.write_text(json.dumps(gold_cases()), encoding="utf-8")
            loaded = load_gold_cases(path)
        self.assertEqual(loaded, gold_cases())


if __name__ == "__main__":
    unittest.main()
