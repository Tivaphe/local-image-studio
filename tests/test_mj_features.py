# -*- coding: utf-8 -*-
"""Tests des options façon Midjourney (styles 1-clic, Stylisation/Weird/Chaos,
live preview interval dans Paramètres, tri/filtre dropdowns) — câblage et plomberie serveur."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import app
import config
import db
import engine
import registry

_REPO = Path(__file__).resolve().parent.parent


class MjApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.output = self.root / "output"
        self.sources = self.root / "source_images"
        self.output.mkdir()
        self.sources.mkdir()
        self.patches = [
            patch.object(db, "DB_PATH", self.root / "history.db"),
            patch.object(config, "ROOT", self.root),
            patch.object(config, "OUTPUT_DIR", self.output),
            patch.object(config, "SOURCE_IMAGES_DIR", self.sources),
            patch.object(engine, "ROOT", self.root),
            patch.object(engine, "OUTPUT_DIR", self.output),
        ]
        for p in self.patches:
            p.start()
        db.init_db()
        self.client = app.app.test_client()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def _captured_enqueue(self):
        captured = {}

        def fake_enqueue(params):
            captured["params"] = dict(params)
            return {"queued": False, "started": True}
        return captured, fake_enqueue

    def test_generate_chaos_default_zero(self):
        captured, fake = self._captured_enqueue()
        with patch.object(app.tasks, "enqueue_generate", fake):
            r = self.client.post("/api/generate", json={"model_id": "sd3.5-medium", "prompt": "a quiet cat"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(captured["params"]["chaos"], 0)

    def test_generate_chaos_passthrough_and_clamp(self):
        captured, fake = self._captured_enqueue()
        with patch.object(app.tasks, "enqueue_generate", fake):
            r = self.client.post("/api/generate", json={"model_id": "sd3.5-medium", "prompt": "a cat", "chaos": 150})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(captured["params"]["chaos"], 100)

        captured2, fake2 = self._captured_enqueue()
        with patch.object(app.tasks, "enqueue_generate", fake2):
            r = self.client.post("/api/generate", json={"model_id": "sd3.5-medium", "prompt": "a cat", "chaos": -5})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(captured2["params"]["chaos"], 0)

    def test_generate_chaos_invalid_returns_400(self):
        r = self.client.post("/api/generate", json={"model_id": "sd3.5-medium", "prompt": "a cat", "chaos": "abc"})
        self.assertEqual(r.status_code, 400)

    def test_settings_persists_preview_interval(self):
        saved = {}

        def fake_load_settings():
            return dict(saved)

        def fake_save_settings(patch_dict):
            saved.update(patch_dict)

        with patch.object(app, "load_settings", fake_load_settings), \
             patch.object(app, "save_settings", fake_save_settings):
            r = self.client.post("/api/settings",
                                 json={"hf_token": "", "open_browser": False, "preview_interval": 5})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(saved.get("preview_interval"), 5)
            self.assertEqual(r.get_json()["preview_interval"], 5)

            # borné à 12
            r = self.client.post("/api/settings",
                                 json={"hf_token": "", "open_browser": False, "preview_interval": 999})
            self.assertEqual(saved.get("preview_interval"), 12)

            # valeur invalide → défaut 3
            r = self.client.post("/api/settings",
                                 json={"hf_token": "", "open_browser": False, "preview_interval": "abc"})
            self.assertEqual(saved.get("preview_interval"), 3)


class MjUiWiringTests(unittest.TestCase):
    def test_generate_html_has_mj_controls(self):
        html = (_REPO / "src/templates/generate.html").read_text(encoding="utf-8")
        for token in ("mj-style-chips", "mj-stylize", "mj-weird", "mj-chaos",
                      "mj-stylize-val", "mj-weird-val", "mj-chaos-val",
                      "mj-weird-desc", "gen-panel"):
            self.assertIn(token, html, token)

    def test_generate_js_has_mj_logic(self):
        js = (_REPO / "src/static/generate.js").read_text(encoding="utf-8")
        for token in ("MJ_STYLE_CHIPS", "mjInitChips", "mjInitStylize", "mjInitWeird", "mjInitChaos",
                      "captureStylizeBase", "stylizeBase", "chaos:"):
            self.assertIn(token, js, token)
        # le payload final inclut bien la clé chaos
        self.assertIn("chaos: $('#mj-chaos')", js)

    def test_engine_implements_chaos(self):
        src = (_REPO / "src/engine.py").read_text(encoding="utf-8")
        self.assertIn("img_seeds", src)
        self.assertIn("getrandbits", src)
        self.assertIn('p.get("chaos")', src)

    def test_app_clamps_chaos(self):
        src = (_REPO / "src/app.py").read_text(encoding="utf-8")
        self.assertIn('params["chaos"]', src)

    def test_quality_js_still_defines_collect(self):
        # le slider Weird pilote #q-sampler/#q-scheduler → collect() doit les transporter
        js = (_REPO / "src/static/quality.js").read_text(encoding="utf-8")
        self.assertIn("out.sampler", js)
        self.assertIn("out.scheduler", js)

    def test_settings_ui_exposes_preview_interval(self):
        html = (_REPO / "src/templates/settings.html").read_text(encoding="utf-8")
        js = html  # le script est inline
        self.assertIn("preview_interval", html)

    def test_history_has_sort_dropdown(self):
        html = (_REPO / "src/templates/history.html").read_text(encoding="utf-8")
        self.assertIn('id="history-sort"', html)
        self.assertIn("history-sort", html)
        self.assertIn('value="oldest"', html)
        self.assertIn("data-pixels", html)

    def test_models_page_has_filter_dropdown(self):
        html = (_REPO / "src/templates/models.html").read_text(encoding="utf-8")
        self.assertIn('id="models-filter"', html)
        self.assertIn('id="model-grid-main"', html)

    def test_style_css_has_mj_styles(self):
        css = (_REPO / "src/static/style.css").read_text(encoding="utf-8")
        for token in (".mj-chip", ".mj-box", ".mj-slider", ".gen-panel", ".history-sort", ".models-toolbar"):
            self.assertIn(token, css, token)


if __name__ == "__main__":
    unittest.main()
