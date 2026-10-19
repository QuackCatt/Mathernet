from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RepositoryHygieneTests(unittest.TestCase):
    def test_versioned_snapshot_contains_no_local_state_or_saved_cards(self):
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        live_tracked_files = [
            Path(line)
            for line in result.stdout.splitlines()
            if (ROOT / line).is_file()
        ]
        forbidden_names = {
            ".env",
            "gateway.json",
            "map_sessions.json",
            "deep_dive_sessions.json",
            "formula_introductions.json",
            "search_cache.json",
            "mathernet.json",
        }
        for path in live_tracked_files:
            with self.subTest(path=path):
                self.assertNotIn("data/", path.as_posix())
                self.assertNotIn("output/", path.as_posix())
                self.assertNotIn("tmp/", path.as_posix())
                self.assertNotIn(path.name, forbidden_names)
                self.assertFalse(path.name.endswith("_card.json"))


if __name__ == "__main__":
    unittest.main()
