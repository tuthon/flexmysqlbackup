"""Prevent publishing a standalone script that differs from its maintained sources."""
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


class Distribution(unittest.TestCase):
    def test_distribution_matches_modular_sources(self):
        result = subprocess.run([sys.executable, str(ROOT / 'build.py'), '--check'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
