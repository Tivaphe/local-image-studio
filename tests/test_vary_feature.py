# -*- coding: utf-8 -*-
"""Tests de la variation façon Midjourney (boutons « 🔀 Varier subtil / fort »)
et des nouveaux formats d'image (2:3, 4:5, 21:9, 9:21)."""
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
from registry import MODELS, RATIOS

_PNG_BYTES = (b"\x89PNG\r\n\x1a\n"
              b"\x00\x00\x00\x0dIHDR"
              b"\x00\x00\x00\x08\x00\x00\x00\x08\x08\x02\x00\x00\x00"
              b"\x00")


class ExtraRatiosTests(unittest.TestCase):
    def test_mj_like_ratios_present(self):
        for rid in ("2:3", "4:5", "21:9", "9:21"):
            with self.subTest(ratio=rid):
                w, h = RATIOS[rid]
                self.assertEqual(w % 16, 0)
                self.assertEqual(h % 16, 0)
                self.assertGreater(w, 0)
                self.assertGreater(h, 0)
        # 2:3 et 9:21 sont des portraits ; 21:9 est un panoramique
        self.assertGreater(RATIOS["2:3"][1], RATIOS["2:3"][0])
        self.assertGreater(RATIOS["9:21"][1], RATIOS["9:21"][0])
        self.assertGreater(RATIOS["21:9"][0], RATIOS["21:9"][1])


class VaryApiTests(unittest.TestCase):
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

    def _make_image(self, model="sd3.5-medium", width=1024, height=1024, quant="Q5_K_M"):
        fn = f"sample_{model.replace('.', '_')}_{width}_{height}.png".replace(" ", "_")
        (self.output / fn).write_bytes(_PNG_BYTES)
        img_id = db.add_image(
            batch_id="batchvary", idx=0, model_id=model, model_name=MODELS.get(model, {}).get("name", model),
            quant=quant, prompt="a lighthouse at dawn, watercolor", negative="blurry",
            seed=123, width=width, height=height, steps=25, cfg=4.5,
            sampler="euler", filename=fn, batch_size=1)
        return img_id

    def _captured_enqueue(self):
        captured = {}

        def fake_enqueue(params):
            captured["params"] = dict(params)
            return {"queued": False, "started": True}
        return captured, fake_enqueue

    def test_vary_requires_image_id(self):
        r = self.client.post("/api/vary", json={"mode": "subtle"})
        self.assertEqual(r.status_code, 400)

    def test_vary_unknown_image(self):
        r = self.client.post("/api/vary", json={"image_id": 424242, "mode": "subtle"})
        self.assertEqual(r.status_code, 404)

    def test_vary_rejects_aux_model_images(self):
        # Une image « upscale:... » ne peut pas être variée (pas un vrai modèle txt2img/img2img).
        img_id = self._make_image(model="upscale:realesrgan-x4plus", quant="×4")
        r = self.client.post("/api/vary", json={"image_id": img_id, "mode": "subtle"})
        self.assertEqual(r.status_code, 400)

    def test_vary_rejects_non_img2img_model(self):
        # FLUX.1 schnell n'accepte pas d'image de départ (txt2img only).
        img_id = self._make_image(model="flux-schnell", quant="Q4_K_M")
        r = self.client.post("/api/vary", json={"image_id": img_id, "mode": "subtle"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("img2img", r.get_json()["error"].lower().replace("é", "e"))

    def test_vary_rejects_too_big_image(self):
        img_id = self._make_image(model="sd3.5-medium", width=4096, height=4096)
        r = self.client.post("/api/vary", json={"image_id": img_id, "mode": "subtle"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("1536", r.get_json()["error"])

    def test_vary_subtle_enqueues_img2img_with_strength_035(self):
        img_id = self._make_image(model="sd3.5-medium", width=1024, height=1024)
        captured, fake = self._captured_enqueue()
        with patch.object(app.tasks, "enqueue_generate", fake), \
             patch.object(engine.tasks, "enqueue_generate", fake):
            r = self.client.post("/api/vary", json={"image_id": img_id, "mode": "subtle"})
        self.assertEqual(r.status_code, 200)
        j = r.get_json()
        self.assertTrue(j["ok"])
        p = captured["params"]
        self.assertEqual(p["task_kind"], "vary")
        self.assertEqual(p["vary_mode"], "subtle")
        self.assertAlmostEqual(p["strength"], 0.35)
        self.assertEqual(p["input_mode"], "init")
        self.assertIsNotNone(p["source_image"])
        self.assertIsNone(p["seed"])          # nouvelle graine aléatoire
        self.assertEqual(p["batch"], 1)
        self.assertEqual(p["prompt"], "a lighthouse at dawn, watercolor")
        self.assertEqual(p["negative"], "blurry")
        self.assertEqual(p["width"], 1024)
        self.assertEqual(p["height"], 1024)

    def test_vary_strong_enqueues_with_strength_075(self):
        img_id = self._make_image(model="sd3.5-medium", width=1152, height=896)
        captured, fake = self._captured_enqueue()
        with patch.object(app.tasks, "enqueue_generate", fake), \
             patch.object(engine.tasks, "enqueue_generate", fake):
            r = self.client.post("/api/vary", json={"image_id": img_id, "mode": "strong"})
        self.assertEqual(r.status_code, 200)
        p = captured["params"]
        self.assertAlmostEqual(p["strength"], 0.75)
        self.assertEqual(p["vary_mode"], "strong")
        self.assertEqual(p["width"], 1152)
        self.assertEqual(p["height"], 896)

    def test_vary_queue_summary_labels(self):
        # Le résumé de file d'attente doit mentionner la variation.
        item = engine.tasks._build_queue_item(
            {"task_kind": "vary", "vary_mode": "subtle", "model_id": "sd3.5-medium",
             "strength": 0.35, "prompt": "x", "quant": "Q4_K_M", "width": 1024,
             "height": 1024, "batch": 1, "source_image": "output/x.png"})
        self.assertIn("Variation", item["summary"]["model_name"])
        self.assertTrue(item["summary"]["model_id"].startswith("vary:"))


class VaryFrontendWiringTests(unittest.TestCase):
    def test_quality_js_exposes_vary(self):
        js = (Path(__file__).resolve().parent.parent / "src/static/quality.js").read_text(encoding="utf-8")
        self.assertIn("Q.startVary", js)
        self.assertIn("makeVaryButtons", js)
        self.assertIn("/api/vary", js)
        self.assertIn('"vary"', js)

    def test_pages_append_vary_buttons(self):
        root = Path(__file__).resolve().parent.parent
        for rel in ("src/static/generate.js", "src/static/edit.js"):
            js = (root / rel).read_text(encoding="utf-8")
            self.assertIn("makeVaryButtons", js, rel)
            self.assertIn("'vary'", js, rel)

    def test_history_has_vary_buttons_and_aux_meta(self):
        html = (Path(__file__).resolve().parent.parent / "src/templates/history.html").read_text(encoding="utf-8")
        self.assertIn("vary-link", html)
        self.assertIn("startVary", html)
        self.assertIn("vary:", html)
        self.assertIn("vary_models", html)

    def test_generate_js_aux_kinds_and_badge(self):
        js = (Path(__file__).resolve().parent.parent / "src/static/generate.js").read_text(encoding="utf-8")
        self.assertIn("'vary'", js)
        self.assertIn("VARIANTE", js)


if __name__ == "__main__":
    unittest.main()
