# -*- coding: utf-8 -*-
"""
Tests des fonctionnalités Qualité / Détails / Upscaling ×4 / ADetailer
et des 5 nouveaux modèles GGUF (FLUX Dev, FLUX Kontext, Chroma, Chroma-Radiance, LongCat).
"""
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
from registry import (MODELS, DEPS, UPSCALERS, ADETAILERS,
                      SAMPLERS_INFO, SCHEDULERS_INFO,
                      upscaler_path, upscaler_status,
                      adetailer_path, adetailer_status,
                      build_command, build_upscale_command)

NEW_QUALITY_MODELS = ["flux-dev", "flux-kontext-dev", "chroma",
                      "chroma-radiance", "longcat-image"]

# PNG minimal valide (en-tête + IHDR factice 8×8) pour les tests de chemins.
_PNG_BYTES = (b"\x89PNG\r\n\x1a\n"
              b"\x00\x00\x00\x0dIHDR"
              b"\x00\x00\x00\x08\x00\x00\x00\x08\x08\x02\x00\x00\x00"
              b"\x00")


class NewModelsRegistryTests(unittest.TestCase):
    def test_new_models_registered_and_coherent(self):
        for mid in NEW_QUALITY_MODELS:
            with self.subTest(model=mid):
                m = MODELS[mid]
                self.assertTrue(m["quants"])
                self.assertEqual(set(m["quants"]), set(m["file_for_quant"]))
                self.assertEqual(set(m["quants"]), set(m["size_gb"]))
                self.assertIn(m["default_quant"], m["quants"])
                for dep in m["deps"]:
                    self.assertIn(dep, DEPS, f"dépendance inconnue : {dep}")
                for preset in m.get("presets", {}).values():
                    self.assertIn(preset["quant"], m["quants"])
                # Chaque modèle doit avoir une explication claire en français.
                self.assertGreater(len(m.get("desc", "")), 40)

    def test_new_models_reuse_existing_shared_deps(self):
        # Toutes les dépendances doivent déjà exister dans le registre (pas de nouveau dep dédié).
        shared = {"vae_flux", "clip_l", "t5xxl", "qwen25vl_7b"}
        for mid in NEW_QUALITY_MODELS:
            with self.subTest(model=mid):
                self.assertTrue(set(MODELS[mid]["deps"]).issubset(shared))

    def test_longcat_remote_files_use_comfy_subfolder(self):
        m = MODELS["longcat-image"]
        for q, local in m["file_for_quant"].items():
            remote = m["remote_file_for_quant"][q]
            self.assertTrue(remote.startswith("comfy/"))
            self.assertTrue(remote.endswith(local))

    def test_kontext_declares_ref_editing(self):
        m = MODELS["flux-kontext-dev"]
        self.assertTrue(m["supports_ref_images"])
        self.assertTrue(m["supports_img2img"])
        self.assertIn("ref", registry.input_modes("flux-kontext-dev"))
        self.assertTrue(registry.supports_outpainting("flux-kontext-dev"))
        self.assertTrue(m.get("ref_hint"), "Kontext devrait expliquer son fonctionnement")
        self.assertTrue(m.get("ref_examples"))


class UpscalersRegistryTests(unittest.TestCase):
    def test_three_upscalers_four_x(self):
        self.assertEqual(len(UPSCALERS), 3)
        for uid, u in UPSCALERS.items():
            with self.subTest(upscaler=uid):
                self.assertEqual(u["scale"], 4)
                self.assertTrue(u["filename"].endswith(".pth"))
                self.assertTrue(u["url"].startswith("https://"))
                self.assertGreater(len(u["desc"]), 30)
                self.assertEqual(upscaler_path(uid), config.UPSCALE_DIR / u["filename"])
        self.assertIsNone(upscaler_path("inconnu"))
        self.assertFalse(upscaler_status("inconnu")["downloaded"])

    def test_adetailers_registry(self):
        self.assertEqual(len(ADETAILERS), 3)
        for did, d in ADETAILERS.items():
            with self.subTest(detector=did):
                self.assertTrue(d["filename"].endswith(".safetensors"))
                self.assertTrue(d["repo"])
                self.assertGreater(len(d["desc"]), 30)
                self.assertEqual(adetailer_path(did), config.ADETAILER_DIR / d["filename"])
        self.assertIsNone(adetailer_path("inconnu"))
        self.assertFalse(adetailer_status("inconnu")["downloaded"])

    def test_sampler_and_scheduler_catalogs_explained(self):
        samplers = {s["id"] for s in SAMPLERS_INFO}
        self.assertIn("default", samplers)
        for wanted in ("euler", "heun", "dpm++2m", "euler_a", "lcm"):
            self.assertIn(wanted, samplers)
        schedulers = {s["id"] for s in SCHEDULERS_INFO}
        self.assertIn("default", schedulers)
        for wanted in ("discrete", "karras", "beta", "sgm_uniform", "exponential"):
            self.assertIn(wanted, schedulers)
        for item in SAMPLERS_INFO + SCHEDULERS_INFO:
            self.assertGreater(len(item["desc"]), 10)
            self.assertGreater(len(item["label"]), 10)


class BuildCommandQualityTests(unittest.TestCase):
    """Vérifie les arguments sd-cli construits pour les options qualité, sans téléchargement."""

    def _manifest(self):
        return {d: {"path": f"/fake/{d}.file"} for d in DEPS}

    def _cmd(self, model_id, ref_images=None, **quality):
        m = MODELS[model_id]
        with patch.object(registry, "_dep_path",
                          lambda mf, d: mf.get(d, {}).get("path")):
            return build_command(model_id, m["default_quant"], "a prompt", "bad",
                                 1024, 1024, m["defaults"]["steps"],
                                 m["defaults"]["cfg"], 42, 1, "out.png", "sd-cli",
                                 self._manifest(), ref_images=ref_images,
                                 input_mode="ref" if ref_images else None,
                                 **quality)

    @staticmethod
    def _val(args, flag):
        return args[args.index(flag) + 1] if flag in args else None

    def test_quality_flags_added(self):
        args = self._cmd("flux-dev", sampler="dpm++2m", scheduler="karras",
                         vae_tiling=True, slg_scale=3.0,
                         upscale_model="/fake/RealESRGAN_x4plus.pth",
                         adetailer_model="/fake/face_yolov8n.safetensors")
        self.assertEqual(self._val(args, "--sampling-method"), "dpm++2m")
        self.assertEqual(self._val(args, "--scheduler"), "karras")
        self.assertIn("--vae-tiling", args)
        self.assertEqual(self._val(args, "--slg-scale"), "3.0")
        self.assertEqual(self._val(args, "--upscale-model"),
                         "/fake/RealESRGAN_x4plus.pth")
        self.assertEqual(self._val(args, "--ad-model"),
                         "/fake/face_yolov8n.safetensors")

    def test_no_quality_flags_by_default(self):
        args = self._cmd("flux-dev")
        self.assertNotIn("--scheduler", args)
        self.assertNotIn("--vae-tiling", args)
        self.assertNotIn("--slg-scale", args)
        self.assertNotIn("--upscale-model", args)
        self.assertNotIn("--ad-model", args)
        # l'échantillonneur par défaut du modèle est utilisé
        self.assertEqual(self._val(args, "--sampling-method"), "euler")

    def test_slg_zero_or_none_omitted(self):
        for val in (None, 0, 0.0, "0"):
            args = self._cmd("flux-dev", slg_scale=val)
            self.assertNotIn("--slg-scale", args)

    def test_default_sampler_keyword_uses_model_default(self):
        args = self._cmd("chroma", sampler="default", scheduler="default")
        self.assertEqual(self._val(args, "--sampling-method"), "euler")
        self.assertNotIn("--scheduler", args)

    def test_kontext_uses_references_without_tag_syntax(self):
        args = self._cmd("flux-kontext-dev", ref_images=["a.png", "b.png"])
        self.assertEqual(args.count("-r"), 2)
        self.assertEqual(self._val(args, "--cfg-scale"), "1.0")
        self.assertIn("--clip-on-cpu", args)
        self.assertEqual(self._val(args, "--t5xxl"), "/fake/t5xxl.file")
        self.assertEqual(self._val(args, "--clip_l"), "/fake/clip_l.file")
        self.assertEqual(self._val(args, "--vae"), "/fake/vae_flux.file")

    def test_chroma_injects_model_args(self):
        args = self._cmd("chroma")
        self.assertEqual(self._val(args, "--model-args"), "chroma_use_dit_mask=false")
        self.assertEqual(self._val(args, "--t5xxl"), "/fake/t5xxl.file")
        self.assertEqual(self._val(args, "--vae"), "/fake/vae_flux.file")

    def test_chroma_radiance_has_no_external_vae(self):
        args = self._cmd("chroma-radiance")
        self.assertNotIn("--vae", args)
        self.assertEqual(self._val(args, "--t5xxl"), "/fake/t5xxl.file")

    def test_longcat_uses_llm_and_flow_shift(self):
        args = self._cmd("longcat-image")
        self.assertEqual(self._val(args, "--llm"), "/fake/qwen25vl_7b.file")
        self.assertEqual(self._val(args, "--flow-shift"), "3")
        self.assertEqual(self._val(args, "--vae"), "/fake/vae_flux.file")
        self.assertIsNone(self._val(args, "--t5xxl"))

    def test_build_upscale_command_shape(self):
        args = build_upscale_command("sd-cli", "in.png", "out.png",
                                     "/fake/RealESRGAN_x4plus.pth")
        self.assertEqual(args[:2], ["sd-cli", "-M"])
        self.assertEqual(self._val(args, "-M"), "upscale")
        self.assertEqual(self._val(args, "-i"), "in.png")
        self.assertEqual(self._val(args, "-o"), "out.png")
        self.assertEqual(self._val(args, "--upscale-model"),
                         "/fake/RealESRGAN_x4plus.pth")
        self.assertEqual(self._val(args, "--upscale-tile-size"), "256")


class QualityApiTests(unittest.TestCase):
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

    def test_quality_info_endpoint(self):
        r = self.client.get("/api/quality-info")
        self.assertEqual(r.status_code, 200)
        j = r.get_json()
        self.assertTrue(j["ok"])
        self.assertEqual(len(j["upscalers"]), 3)
        self.assertEqual(len(j["adetailers"]), 3)
        self.assertTrue(all("status" in u for u in j["upscalers"]))
        self.assertTrue(any(s["id"] == "dpm++2m" for s in j["samplers"]))
        self.assertTrue(any(s["id"] == "karras" for s in j["schedulers"]))

    def test_upscale_rejects_unknown_upscaler(self):
        r = self.client.post("/api/upscale", json={"upscaler_id": "nope"})
        self.assertEqual(r.status_code, 400)

    def test_upscale_errors_when_none_installed(self):
        with patch.object(app, "upscaler_status",
                          lambda uid: {"downloaded": False, "path": None}):
            r = self.client.post("/api/upscale", json={"path": "image.png"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("Modèles", r.get_json()["error"])

    def test_upscale_happy_path_queues_task(self):
        (self.output / "image.png").write_bytes(_PNG_BYTES)
        captured, fake = self._captured_enqueue()
        with patch.object(app, "upscaler_status",
                          lambda uid: {"downloaded": True,
                                       "path": "/fake/" + uid + ".pth"}), \
             patch.object(engine.tasks, "enqueue_generate", fake), \
             patch.object(app.tasks, "enqueue_generate", fake):
            r = self.client.post("/api/upscale",
                                 json={"path": "image.png",
                                       "upscaler_id": "realesrgan-x4plus"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["ok"])
        self.assertEqual(captured["params"]["task_kind"], "upscale")
        self.assertEqual(captured["params"]["upscaler_id"], "realesrgan-x4plus")
        self.assertEqual(captured["params"]["source_image"], "output/image.png")

    def test_upscale_by_image_id_uses_db_filename(self):
        img_id = db.add_image("batch", 0, "m", "Model", "q", "p", "",
                              1, 8, 8, 1, 1, "euler", "fromdb.png", 1)
        (self.output / "fromdb.png").write_bytes(_PNG_BYTES)
        captured, fake = self._captured_enqueue()
        with patch.object(app, "upscaler_status",
                          lambda uid: {"downloaded": True, "path": "/f.pth"}), \
             patch.object(app.tasks, "enqueue_generate", fake):
            r = self.client.post("/api/upscale",
                                 json={"image_id": img_id,
                                       "upscaler_id": "4x-nomos2-hq"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(captured["params"]["source_image"], "output/fromdb.png")

    def test_upscale_rejects_missing_file(self):
        with patch.object(app, "upscaler_status",
                          lambda uid: {"downloaded": True, "path": "/f.pth"}):
            r = self.client.post("/api/upscale", json={"path": "absent.png"})
        self.assertEqual(r.status_code, 404)

    def test_generate_forwards_quality_params(self):
        captured, fake = self._captured_enqueue()
        with patch.object(app, "upscaler_status",
                          lambda uid: {"downloaded": True, "path": "/f.pth"}), \
             patch.object(app, "adetailer_status",
                          lambda did: {"downloaded": True, "path": "/f.st"}), \
             patch.object(app.tasks, "enqueue_generate", fake):
            r = self.client.post("/api/generate", json={
                "model_id": "flux-dev", "quant": "Q5_K_S",
                "prompt": "a fox", "steps": 24, "cfg": 1.0,
                "sampler": "heun", "scheduler": "karras",
                "vae_tiling": True, "slg_scale": 3.0,
                "hires_fix": True, "hires_strength": 0.4,
                "upscale_id": "realesrgan-x4plus",
                "adetailer_id": "face_yolov8n",
            })
        self.assertEqual(r.status_code, 200)
        p = captured["params"]
        self.assertEqual(p["sampler"], "heun")
        self.assertEqual(p["scheduler"], "karras")
        self.assertTrue(p["vae_tiling"])
        self.assertEqual(p["slg_scale"], 3.0)
        self.assertTrue(p["hires_fix"])
        self.assertEqual(p["hires_strength"], 0.4)
        self.assertEqual(p["upscale_id"], "realesrgan-x4plus")
        self.assertEqual(p["adetailer_id"], "face_yolov8n")

    def test_generate_rejects_unknown_sampler(self):
        r = self.client.post("/api/generate", json={
            "model_id": "flux-dev", "quant": "Q5_K_S", "prompt": "a fox",
            "sampler": "bogus-sampler",
        })
        self.assertEqual(r.status_code, 400)
        self.assertIn("chantillonneur", r.get_json()["error"])

    def test_generate_rejects_undownloaded_upscaler(self):
        with patch.object(app, "upscaler_status",
                          lambda uid: {"downloaded": False, "path": None}):
            r = self.client.post("/api/generate", json={
                "model_id": "flux-dev", "quant": "Q5_K_S", "prompt": "a fox",
                "upscale_id": "realesrgan-x4plus",
            })
        self.assertEqual(r.status_code, 400)
        self.assertIn("Upscaling", r.get_json()["error"])

    def test_hires_fix_disabled_with_source_image(self):
        (self.sources / "in.png").write_bytes(_PNG_BYTES)
        captured, fake = self._captured_enqueue()
        with patch.object(app.tasks, "enqueue_generate", fake):
            r = self.client.post("/api/generate", json={
                "model_id": "flux-dev", "quant": "Q5_K_S", "prompt": "restyle",
                "input_mode": "init", "ref_images": ["source_images/in.png"],
                "hires_fix": True,
            })
        self.assertEqual(r.status_code, 200)
        # Le Hires Fix est réservé à la génération pure (img de départ -> ignoré)
        self.assertFalse(captured["params"]["hires_fix"])


class EngineQualityForwardTests(unittest.TestCase):
    """_run_generate doit résoudre upscale/adetailer en chemins et bloquer si absents."""

    def test_generate_task_fails_fast_without_upscaler_downloaded(self):
        p = {
            "model_id": "flux-dev", "quant": "Q5_K_S", "prompt": "fox",
            "negative": "", "width": 1024, "height": 1024, "steps": 24,
            "cfg": 1.0, "seed": 1, "batch": 1, "upscale_id": "realesrgan-x4plus",
        }
        with patch.object(engine, "find_sd_cli", lambda: "/fake/sd-cli"), \
             patch.object(engine, "_model_present", lambda *a: True), \
             patch.object(engine, "_dep_present", lambda *a: True), \
             patch.object(registry, "upscaler_path",
                          lambda uid: Path("/inexistant/None.pth")):
            engine.tasks._reset("generate")
            engine.tasks._run_generate(p)
        self.assertIn("Onglet Modèles",
                      engine.tasks.state.get("error", "") + engine.tasks.state.get("log", "")
                      .replace("onglet Modèles", "Onglet Modèles"))


if __name__ == "__main__":
    unittest.main()
