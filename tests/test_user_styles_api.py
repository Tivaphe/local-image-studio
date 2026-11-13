"""Tests — styles personnalisés (page /styles) : CRUD API + câblage des sélecteurs."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import app
import config
import db
import registry


class UserStylesApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.output = self.root / "output"
        self.sources = self.root / "source_images"
        self.portraits = self.root / "portraits"
        self.output.mkdir()
        self.sources.mkdir()
        self.portraits.mkdir()
        self.patches = [
            patch.object(db, "DB_PATH", self.root / "history.db"),
            patch.object(config, "ROOT", self.root),
            patch.object(config, "OUTPUT_DIR", self.output),
            patch.object(config, "SOURCE_IMAGES_DIR", self.sources),
            patch.object(config, "PORTRAITS_DIR", self.portraits),
            patch.object(registry, "PORTRAITS_DIR", self.portraits),
            patch.object(engine := __import__("engine"), "ROOT", self.root),
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

    # ------------------------------------------------------------------ CRUD
    def test_create_list_update_delete_cycle(self):
        r = self.client.post("/api/styles", json={
            "name": "Néo-rétro cinéma 70s",
            "prompt": "70s neo-retro film still, kodachrome tones, subtle grain",
            "applies_to": "both",
            "models": "all",
        })
        self.assertEqual(r.status_code, 200)
        style_id = r.get_json()["id"]
        self.assertIsNotNone(style_id)

        j = self.client.get("/api/styles").get_json()
        self.assertTrue(j["ok"])
        match = [s for s in j["styles"] if s["id"] == style_id]
        self.assertEqual(len(match), 1)
        self.assertEqual(match[0]["name"], "Néo-rétro cinéma 70s")
        self.assertEqual(match[0]["applies_to"], "both")
        self.assertEqual(match[0]["models"], "all")

        r = self.client.post("/api/styles/update", json={
            "id": style_id, "name": "Néo-rétro cinéma 80s",
            "prompt": "80s neo-retro film still, vhs-style grain",
            "applies_to": "gen", "models": ["qwen-image-2512"],
        })
        self.assertTrue(r.get_json()["ok"])
        match = [s for s in self.client.get("/api/styles").get_json()["styles"] if s["id"] == style_id][0]
        self.assertEqual(match["name"], "Néo-rétro cinéma 80s")
        self.assertEqual(match["applies_to"], "gen")
        self.assertEqual(match["models"], ["qwen-image-2512"])

        r = self.client.post("/api/styles/delete", json={"id": style_id})
        self.assertTrue(r.get_json()["ok"])
        match = [s for s in self.client.get("/api/styles").get_json()["styles"] if s["id"] == style_id]
        self.assertEqual(match, [])

    def test_create_rejects_missing_fields(self):
        r = self.client.post("/api/styles", json={"name": "", "prompt": "x"})
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/styles", json={"name": "x", "prompt": ""})
        self.assertEqual(r.status_code, 400)

    def test_create_rejects_invalid_applies_to(self):
        r = self.client.post("/api/styles", json={
            "name": "Test", "prompt": "test prompt", "applies_to": "video", "models": "all",
        })
        self.assertEqual(r.status_code, 400)

    def test_unknown_model_ids_fall_back_to_all(self):
        r = self.client.post("/api/styles", json={
            "name": "Modèle inconnu", "prompt": "test", "applies_to": "both",
            "models": ["modele-qui-nexiste-pas"],
        })
        self.assertEqual(r.status_code, 200)
        style_id = r.get_json()["id"]
        match = [s for s in self.client.get("/api/styles").get_json()["styles"] if s["id"] == style_id][0]
        self.assertEqual(match["models"], "all")  # invalides filtrés → retombe sur « tous »

    def test_applies_to_filter_and_model_filter(self):
        self.client.post("/api/styles", json={
            "name": "Style gen seul", "prompt": "gen only", "applies_to": "gen", "models": "all"})
        self.client.post("/api/styles", json={
            "name": "Style edit seul", "prompt": "edit only", "applies_to": "edit", "models": "all"})
        self.client.post("/api/styles", json={
            "name": "Style édition qwen", "prompt": "edit qwen", "applies_to": "edit",
            "models": ["qwen-image-2512"]})

        gen = self.client.get("/api/styles?applies_to=gen").get_json()["styles"]
        self.assertEqual({s["name"] for s in gen}, {"Style gen seul"})

        edit = self.client.get("/api/styles?applies_to=edit").get_json()["styles"]
        self.assertEqual({s["name"] for s in edit}, {"Style edit seul", "Style édition qwen"})

        qwen_edit = self.client.get("/api/styles?applies_to=edit&model_id=qwen-image-2512").get_json()["styles"]
        self.assertEqual({s["name"] for s in qwen_edit}, {"Style edit seul", "Style édition qwen"})

        other6 = self.client.get("/api/styles?applies_to=edit&model_id=flux2-klein-4b").get_json()["styles"]
        self.assertEqual({s["name"] for s in other6}, {"Style edit seul"})

    def test_update_and_delete_missing(self):
        r = self.client.post("/api/styles/update", json={
            "id": 99999, "name": "x", "prompt": "y", "applies_to": "both", "models": "all"})
        self.assertEqual(r.status_code, 404)
        r = self.client.post("/api/styles/delete", json={"id": 99999})
        self.assertEqual(r.status_code, 404)

    # --------------------------------------------------------------- contenu
    def test_api_styles_exposes_builtin_style_catalogues(self):
        j = self.client.get("/api/styles").get_json()
        self.assertTrue(j["ok"])
        self.assertGreaterEqual(len(j["builtin_gen"]), 24)
        self.assertGreaterEqual(len(j["builtin_edit"]), 16)
        self.assertIn("qwen-image-2512", j["models"])

    def test_styles_page_and_nav_wired(self):
        r = self.client.get("/styles")
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        self.assertIn('id="style-form"', html)
        self.assertIn('id="user-styles-list"', html)
        self.assertIn('id="new-style-btn"', html)

        base = (ROOT / "src/templates/base.html").read_text(encoding="utf-8")
        self.assertIn("styles_page", base)

    def test_generate_and_edit_js_load_user_styles(self):
        gen_js = (ROOT / "src/static/generate.js").read_text(encoding="utf-8")
        self.assertIn("/api/styles?applies_to=gen", gen_js)
        self.assertIn("⭐ Mes styles", gen_js)
        edit_js = (ROOT / "src/static/edit.js").read_text(encoding="utf-8")
        self.assertIn("/api/styles?applies_to=edit", edit_js)
        self.assertIn("⭐ Mes styles", edit_js)


if __name__ == "__main__":
    unittest.main()
