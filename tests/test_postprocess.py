"""Tests — post-traitement photo (🎛️) : route d'enregistrement + câblage UI."""

import io
import json
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
import engine
import metadata as pngmeta
import registry

try:
    from PIL import Image
    PIL_OK = True
except Exception:
    PIL_OK = False


def _png_bytes(w=48, h=32, color=(200, 120, 60)):
    if PIL_OK:
        buf = io.BytesIO()
        Image.new("RGB", (w, h), color).save(buf, format="PNG")
        return buf.getvalue()
    # en-tête PNG minimal valide (1×1) — suffit pour les tests de structure
    return (b"\x89PNG\r\n\x1a\n" + b"\x00" * 1200)


class PostprocessSaveRouteTests(unittest.TestCase):
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

    def test_save_records_history_and_file(self):
        payload = _png_bytes()
        r = self.client.post("/api/postprocess/save", data={
            "image": (io.BytesIO(payload), "postprocess.png"),
            "source": "output/source_test.png",
            "prompt": "portrait de femme, lumière douce",
            "settings": json.dumps({"exposure": 0.35, "contrast": 12, "warmth": 20}),
            "summary": "exposition +0,35 EV, contraste +12, chaleur +20",
        }, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 200)
        j = r.get_json()
        self.assertTrue(j["ok"])
        out = self.output / j["filename"]
        self.assertTrue(out.exists())
        self.assertTrue(j["filename"].startswith("post_"))
        rows = db.list_images()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["model"], "postprocess")
        self.assertEqual(rows[0]["sampler"], "post-processing")
        self.assertIn("contraste +12", rows[0]["prompt"])
        self.assertIn("portrait de femme", rows[0]["prompt"])
        self.assertIn("output/source_test.png", rows[0]["source_images_list"])

    def test_saved_png_carries_webui_metadata(self):
        if not PIL_OK:
            self.skipTest("Pillow requis pour lire les métadonnées")
        r = self.client.post("/api/postprocess/save", data={
            "image": (io.BytesIO(_png_bytes()), "postprocess.png"),
            "settings": "{}", "summary": "contraste +30",
        }, content_type="multipart/form-data")
        self.assertTrue(r.get_json()["ok"])
        meta = pngmeta.read_params(self.output / r.get_json()["filename"])
        self.assertTrue(meta)
        self.assertIn("contraste +30", meta.get("prompt", ""))

    def test_rejects_missing_file(self):
        r = self.client.post("/api/postprocess/save", data={}, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 400)

    def test_rejects_tiny_or_non_image(self):
        r = self.client.post("/api/postprocess/save", data={
            "image": (io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"\x00" * 10), "tiny.png"),
        }, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/postprocess/save", data={
            "image": (io.BytesIO(b"not an image at all, really not an image " * 100), "fake.png"),
        }, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 400)

    def test_source_path_outside_repo_is_ignored_but_save_ok(self):
        r = self.client.post("/api/postprocess/save", data={
            "image": (io.BytesIO(_png_bytes()), "postprocess.png"),
            "source": "../../etc/passwd", "settings": "{}",
        }, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["ok"])
        rows = db.list_images()
        self.assertEqual(rows[0]["source_images_list"], [])


class PostprocessWiringTests(unittest.TestCase):
    ROOT = ROOT

    def test_modal_included_everywhere_via_base(self):
        base = (self.ROOT / "src/templates/base.html").read_text(encoding="utf-8")
        self.assertIn('_postprocess.html', base)
        modal = (self.ROOT / "src/templates/_postprocess.html").read_text(encoding="utf-8")
        for sid in ("pp-exposure", "pp-contrast", "pp-brightness", "pp-warmth",
                    "pp-clarity", "pp-saturation", "pp-vibrance"):
            self.assertIn(f'id="{sid}"', modal)
        self.assertIn('id="pp-save"', modal)
        self.assertIn('id="pp-save-edit"', modal)

    def test_postprocess_js_exposes_api_and_loads_locally(self):
        js = (self.ROOT / "src/static/postprocess.js").read_text(encoding="utf-8")
        self.assertIn("window.LisPost", js)
        self.assertIn("/api/postprocess/save", js)
        self.assertIn("/api/use-output-as-source", js)
        self.assertIn("vibrance", js)
        self.assertIn("clarity", js)

    def test_result_pages_and_history_have_adjust_button(self):
        gen = (self.ROOT / "src/static/generate.js").read_text(encoding="utf-8")
        self.assertIn("LisPost.open", gen)
        edit = (self.ROOT / "src/static/edit.js").read_text(encoding="utf-8")
        self.assertIn("LisPost.open", edit)
        hist = (self.ROOT / "src/templates/history.html").read_text(encoding="utf-8")
        self.assertIn("postprocess-link", hist)
        self.assertIn("LisPost.open", hist)


if __name__ == "__main__":
    unittest.main()
