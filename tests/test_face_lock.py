"""Câblage statique du bouton « 🎭 Garder le visage » (onglet Édition)."""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class FaceLockUiTests(unittest.TestCase):
    def setUp(self):
        self.html = (ROOT / "src/templates/edit.html").read_text(encoding="utf-8")
        self.js = (ROOT / "src/static/edit.js").read_text(encoding="utf-8")

    def test_button_present_in_prompt_tools(self):
        m = re.search(r'id="face-lock-btn"[^>]*>', self.html)
        self.assertIsNotNone(m)
        # Le bouton se trouve dans .prompt-tools, à côté des autres actions de prompt
        tools = self.html[self.html.index('class="prompt-tools"'):self.html.index('</div>', self.html.index('class="prompt-tools"'))]
        self.assertIn('id="face-lock-btn"', tools)

    def test_clause_references_every_attached_image_with_model_token(self):
        self.assertIn('function faceLockClause()', self.js)
        # Toutes les images (canvas + références) sont référencées, pas seulement la première
        self.assertIn('orderedImages()', self.js)
        self.assertIn('refTokenForModel(m, i + 1)', self.js)
        self.assertIn('Keep the EXACT SAME PERSON as in', self.js)

    def test_toggle_removes_exactly_the_inserted_clause(self):
        self.assertIn('current.includes(clause)', self.js)
        self.assertIn('current.replace(clause,', self.js)
        # Le texte est un ajout visible/éditable, jamais un envoi silencieux
        self.assertIn('ta.value =', self.js)

    def test_status_reported_to_user(self):
        self.assertIn('enrich-status', self.js.split('face-lock-btn')[1])

    def test_syntax_of_module_parses(self):
        # new Function() via node échouerait le test si la syntaxe JS était cassée
        import shutil, subprocess
        node = shutil.which('node')
        if not node:
            self.skipTest("node indisponible")
        proc = subprocess.run([node, '-e',
            "new Function(require('fs').readFileSync('src/static/edit.js','utf8'))"],
            cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == '__main__':
    unittest.main()
