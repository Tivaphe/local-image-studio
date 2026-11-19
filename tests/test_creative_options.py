# -*- coding: utf-8 -*-
"""Tests des options créatives (styles 1-clic, Stylisation/Excentricité/Chaos,
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
    def test_generate_html_has_cr_controls(self):
        html = (_REPO / "src/templates/generate.html").read_text(encoding="utf-8")
        for token in ("cr-style-chips", "cr-stylize", "cr-weird", "cr-chaos",
                      "cr-stylize-val", "cr-weird-val", "cr-chaos-val",
                      "cr-weird-desc", "gen-panel"):
            self.assertIn(token, html, token)

    def test_generate_js_has_cr_logic(self):
        js = (_REPO / "src/static/generate.js").read_text(encoding="utf-8")
        for token in ("CR_STYLE_CHIPS", "crInitChips", "crInitStylize", "crInitWeird", "crInitChaos",
                      "captureStylizeBase", "stylizeBase", "chaos:"):
            self.assertIn(token, js, token)
        # le payload final inclut bien la clé chaos
        self.assertIn("chaos: $('#cr-chaos')", js)

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

    def test_style_css_has_cr_styles(self):
        css = (_REPO / "src/static/style.css").read_text(encoding="utf-8")
        for token in (".cr-chip", ".cr-box", ".cr-slider", ".gen-panel", ".history-sort", ".models-toolbar"):
            self.assertIn(token, css, token)


if __name__ == "__main__":
    unittest.main()


class ThemeTests(unittest.TestCase):
    def test_base_html_has_toggle_and_antifousc(self):
        html = (_REPO / "src/templates/base.html").read_text(encoding="utf-8")
        self.assertIn('id="theme-toggle"', html)
        self.assertIn("lis-theme", html)
        self.assertIn("data-theme", html)

    def test_app_js_persists_theme(self):
        js = (_REPO / "src/static/app.js").read_text(encoding="utf-8")
        self.assertIn("function setTheme", js)
        self.assertIn("lis-theme", js)
        self.assertIn("theme-toggle", js)

    def test_style_css_defines_light_theme(self):
        css = (_REPO / "src/static/style.css").read_text(encoding="utf-8")
        self.assertIn('html[data-theme="light"]', css)
        self.assertIn('html[data-theme="light"] body', css)
        self.assertIn(".theme-toggle", css)

    def test_readmes_reference_screenshots_section(self):
        fr = (_REPO / "README.md").read_text(encoding="utf-8")
        en = (_REPO / "README_EN.md").read_text(encoding="utf-8")
        for s in (fr, en):
            self.assertIn("docs/screenshots/generate-dark.jpg", s)
            self.assertIn("scripts/take-screenshots.py", s)
        self.assertIn("Thème clair", fr)
        self.assertIn("Light / dark theme", en)

    def test_style_css_hidden_safeguard(self):
        """L'attribut [hidden] doit l'emporter sur les display auteur (régression historique :
        le panneau Détails restait ouvert en permanence, détail voir PR)."""
        css = (_REPO / "src/static/style.css").read_text(encoding="utf-8")
        self.assertIn("[hidden]{display:none !important}", css)
        for garde in (".detail-panel[hidden]{display:none}",
                      ".bulk-bar[hidden]{display:none}",
                      ".saved-searches[hidden]{display:none}"):
            self.assertIn(garde, css)

    def test_lightbox_above_detail_panel_below_errors_modal(self):
        """La visionneuse d'image doit passer au-dessus du panneau Détails (z-index 1201),
        en dessous du journal d'erreurs (1300) ; les toasts au sommet (1500)."""
        css = (_REPO / "src/static/style.css").read_text(encoding="utf-8")
        import re
        def z(sel):
            m = re.search(re.escape(sel) + r"[^{]*\{[^}]*z-index:(\d+)", css.replace("\n", " "))
            return int(m.group(1)) if m else None
        lb, dp, em, toast = z(".lightbox"), z(".detail-panel"), z(".errors-modal"), z(".lis-toast")
        self.assertIsNotNone(lb); self.assertIsNotNone(dp); self.assertIsNotNone(em); self.assertIsNotNone(toast)
        self.assertGreater(lb, dp)
        self.assertLess(lb, em)
        self.assertGreater(toast, em)

    def test_base_html_has_global_job_and_back_to_top(self):
        html = (_REPO / "src/templates/base.html").read_text(encoding="utf-8")
        self.assertIn('id="back-to-top"', html)
        self.assertIn('aria-label="Remonter en haut de la page"', html)
        self.assertIn('id="global-job"', html)
        self.assertIn('id="global-job-cancel"', html)
        self.assertIn("url_for('history')", html)

    def test_app_js_global_job_monitor_and_scroll_top(self):
        js = (_REPO / "src/static/app.js").read_text(encoding="utf-8")
        self.assertIn("backToTopBtn", js)
        self.assertIn("updateBackToTop", js)
        self.assertIn("initGlobalJob", js)
        self.assertIn("/api/status", js)
        self.assertIn("/api/cancel", js)
        # état « busy observé » requis pour ne pas toaster sur chaque chargement
        self.assertIn("seenBusy", js)

    def test_pages_reattach_to_running_job_on_load(self):
        for name in ("generate.js", "edit.js"):
            js = (_REPO / "src/static" / name).read_text(encoding="utf-8")
            self.assertIn("reattachToRunningJob", js, name)
            self.assertIn("pollStatus()", js, name)

    def test_edit_html_collapsible_folds(self):
        html = (_REPO / "src/templates/edit.html").read_text(encoding="utf-8")
        self.assertIn('id="canvas-tools-fold"', html)
        self.assertIn('id="refs-fold"', html)
        self.assertIn("lis_fold_tools", html)
        self.assertIn("lis_fold_refs", html)
        # les sections pliées utilisent bien <details>/<summary> natifs
        self.assertIn("<details", html)
        self.assertIn("</summary>", html)

    def test_style_css_fold_and_global_job_and_responsive(self):
        css = (_REPO / "src/static/style.css").read_text(encoding="utf-8")
        for token in (".back-to-top{", ".global-job{", ".edit-fold{", ".edit-fold-summary",
                      ".edit-fold-body", "prefers-reduced-motion", "@media (min-width:1500px)",
                      "@media (max-width:900px)", "@media (max-width:560px)"):
            self.assertIn(token, css)

    def test_screenshot_tooling_present(self):
        script = (_REPO / "scripts/take-screenshots.py").read_text(encoding="utf-8")
        self.assertIn("playwright", script)
        self.assertIn("docs", script)
        readme = (_REPO / "docs/screenshots/README.md").read_text(encoding="utf-8")
        self.assertIn("take-screenshots.py", readme)
