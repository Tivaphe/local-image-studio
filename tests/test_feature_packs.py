# -*- coding: utf-8 -*-
"""
Tests des trois nouveaux packs :
  A. Restauration / réparation (ADetailer standalone, SeedVR2)
  B. Performance (mini-VAE TAE, SageAttention, aperçu en direct)
  C. PuLID (recommandation de quant, empreintes de portraits)
  + métadonnées PNG (lecture / injection) et routes API associées.
"""
import io
import json
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
import metadata
import registry
from registry import (MODELS, DEPS, SEEDVR2, TAESD, PULID,
                      seedvr2_status, taesd_status, taesd_for_model,
                      pulid_status, supports_pulid, recommended_quant,
                      quant_recommendations,
                      build_command, build_adetailer_command,
                      build_seedvr2_command,
                      PID, pid_status, pid_backbone_for_arch,
                      build_pid_command)

try:
    from PIL import Image, PngImagePlugin
    PIL_OK = True
except Exception:  # pragma: no cover
    PIL_OK = False


# --------------------------------------------------------------------------- #
#  Métadonnées PNG (module metadata)
# --------------------------------------------------------------------------- #
class MetadataTests(unittest.TestCase):
    def test_build_webui_text_layout(self):
        txt = metadata.build_webui_text(
            prompt="a cat", negative="blurry", steps=28, cfg=4.0, seed=42,
            width=1024, height=768, sampler="euler", model_id="flux-schnell")
        self.assertIn("a cat", txt)
        self.assertIn("Negative prompt: blurry", txt)
        self.assertIn("Steps: 28", txt)
        self.assertIn("CFG scale: 4", txt)
        self.assertIn("Seed: 42", txt)
        self.assertIn("Size: 1024x768", txt)
        self.assertIn("Model: flux-schnell", txt)

    def test_parse_roundtrip(self):
        txt = metadata.build_webui_text(
            prompt="un renard cyberpunk", negative="lowres", steps=20,
            cfg=1.0, seed=123, width=512, height=512,
            sampler="euler", model_id="flux-schnell")
        meta = metadata.parse_parameters_text(txt)
        self.assertEqual(meta["prompt"], "un renard cyberpunk")
        self.assertEqual(meta["negative"], "lowres")
        self.assertEqual(meta["steps"], 20)
        self.assertEqual(meta["cfg"], 1.0)
        self.assertEqual(meta["seed"], 123)
        self.assertEqual((meta["width"], meta["height"]), (512, 512))
        self.assertEqual(meta["model"], "flux-schnell")

    def test_parse_tolerates_garbage(self):
        self.assertIsNone(metadata.parse_parameters_text(""))
        meta = metadata.parse_parameters_text("juste un prompt sans paramètres")
        self.assertEqual(meta["prompt"], "juste un prompt sans paramètres")
        self.assertIsNone(meta["seed"])

    def test_parse_extracts_native_json(self):
        native = {"sample_params": {"sampler": "euler", "scheduler": "karras",
                                    "steps": 25, "guidance": 3.5},
                  "prompt": "x"}
        txt = metadata.build_webui_text(prompt="x", seed=7, native=native)
        meta = metadata.parse_parameters_text(txt)
        self.assertIsNotNone(meta["native"])
        self.assertEqual(meta["native"]["sample_params"]["scheduler"], "karras")

    @unittest.skipUnless(PIL_OK, "Pillow requis pour le test PNG complet")
    def test_embed_and_read_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "test.png"
            img = Image.new("RGB", (32, 24), (200, 30, 30))
            img.save(p, format="PNG")
            txt = metadata.build_webui_text(prompt="bonjour", seed=99,
                                            steps=4, cfg=1.0, model_id="flux-schnell")
            self.assertTrue(metadata.embed_params(p, txt))
            # only_if_missing : ne réécrit pas un PNG déjà tagué
            self.assertFalse(metadata.embed_params(p, "texte différent",
                                                   only_if_missing=True))
            meta = metadata.read_params(p)
            self.assertEqual(meta["prompt"], "bonjour")
            self.assertEqual(meta["seed"], 99)
            # lecture depuis un flux binaire (upload drag-drop)
            with open(p, "rb") as fh:
                meta2 = metadata.read_params(io.BytesIO(fh.read()))
            self.assertEqual(meta2["seed"], 99)

    def test_read_params_graceful_without_pil(self):
        # Quel que soit l'état de Pillow, read_params ne doit pas lever d'exception.
        out = metadata.read_params(Path("/chemin/qui/nexiste/pas.png"))
        self.assertIn(out, (None,))

    def test_to_form_settings_maps_model(self):
        meta = {"prompt": "p", "negative": "n", "steps": 8, "cfg": 1.0,
                "seed": 5, "width": 640, "height": 480, "sampler": "Euler",
                "model": "flux-schnell", "native": None}
        form = metadata.to_form_settings(meta, MODELS)
        self.assertEqual(form["prompt"], "p")
        self.assertEqual(form["model"], "flux-schnell")
        self.assertEqual(form["width"], 640)
        self.assertEqual(form["seed"], 5)


# --------------------------------------------------------------------------- #
#  Registre : recommandation de quant, status, builders
# --------------------------------------------------------------------------- #
class RegistryFeatureTests(unittest.TestCase):
    def test_recommended_quant_prefers_big_when_vram_plenty(self):
        # 48 Go : le plus gros quant disponible passe
        m = MODELS["flux-schnell"]
        rec = recommended_quant("flux-schnell", 48.0)
        self.assertEqual(rec, max(m["size_gb"], key=m["size_gb"].get))

    def test_recommended_quant_steps_down_on_tight_vram(self):
        m = MODELS["flux-schnell"]
        sizes = m["size_gb"]
        biggest = max(sizes.values())
        # VRAM juste au-dessus de la marge -> un quant plus petit que le plus gros
        vram = biggest * 1.15 + 1.0   # le plus gros ne rentre pas (×1.2 + 1.5 > vram)
        rec = recommended_quant("flux-schnell", vram)
        self.assertIn(rec, m["quants"])
        self.assertLess(sizes[rec], biggest)

    def test_recommended_quant_minimal_vram_falls_back_to_lightest(self):
        m = MODELS["flux-schnell"]
        lightest = min(m["size_gb"].values())
        rec = recommended_quant("flux-schnell", 2.0)  # rien ne rentre
        self.assertEqual(m["size_gb"][rec], lightest)

    def test_quant_recommendations_covers_registry(self):
        recs = quant_recommendations(24.0)
        for mid in MODELS:
            self.assertIn(mid, recs)

    def test_quant_recommendations_zero_vram(self):
        self.assertEqual(quant_recommendations(0), {})

    def test_seedvr2_status_missing_files(self):
        with patch.object(registry, "SEEDVR2_DIR", Path("/nonexistent-lis")):
            st = seedvr2_status()
            self.assertFalse(st["downloaded"])
            self.assertFalse(st["diffusion"])
            self.assertFalse(st["vae"])

    def test_taesd_status_and_for_model(self):
        with patch.object(registry, "TAESD_DIR", Path("/nonexistent-lis")):
            self.assertFalse(taesd_status("taew2_1")["downloaded"])
        # Qwen-Image 2512 ↔ taew2_1 ; Qwen-Image 2.1 ↔ taeqi2_1
        self.assertEqual(taesd_for_model("qwen-image-2512"), "taew2_1")
        self.assertEqual(taesd_for_model("qwen-image-2.1"), "taeqi2_1")
        self.assertIsNone(taesd_for_model("flux-schnell"))
        # chaque TAE référence un VAE existant dans le registre
        for t in TAESD.values():
            self.assertIn(t["vae_dep"], DEPS)

    def test_pulid_supports_flux_only(self):
        self.assertTrue(supports_pulid("flux-schnell"))
        self.assertTrue(supports_pulid("flux-dev"))
        self.assertTrue(supports_pulid("flux-kontext-dev"))
        self.assertFalse(supports_pulid("qwen-image-2512"))
        self.assertFalse(supports_pulid("sd3.5-large"))

    def test_pulid_status_missing_weights(self):
        with patch.object(registry, "PULID_DIR", Path("/nonexistent-lis")):
            self.assertFalse(pulid_status()["downloaded"])

    def test_build_command_adds_taesd_sage_preview(self):
        cmd = build_command(
            "flux-schnell", "Q4_K_M", "a cat", "", 512, 512, 4, 1.0, 42, 1,
            "/tmp/out_%03d.png", "/bin/sd-cli", {"models": {}},
            taesd_path="/fake/taew2_1.safetensors", sage_attn=True,
            preview_method="tae", preview_path="/tmp/live_%03d.png",
            preview_interval=2)
        self.assertIn("--taesd", cmd)
        self.assertIn("/fake/taew2_1.safetensors", cmd)
        self.assertIn("--sage-attn", cmd)
        self.assertIn("--preview", cmd)
        self.assertIn("tae", cmd)
        self.assertIn("--preview-path", cmd)
        self.assertIn("--preview-interval", cmd)

    def test_build_command_preview_none_omits_flags(self):
        cmd = build_command(
            "flux-schnell", "Q4_K_M", "a cat", "", 512, 512, 4, 1.0, 42, 1,
            "/tmp/out_%03d.png", "/bin/sd-cli", {"models": {}},
            preview_method="none")
        self.assertNotIn("--preview", cmd)
        self.assertNotIn("--taesd", cmd)
        self.assertNotIn("--sage-attn", cmd)

    def test_build_command_tae_preview_only(self):
        cmd = build_command(
            "qwen-image-2512", "Q4_K_M", "a cat", "", 512, 512, 4, 1.0, 42, 1,
            "/tmp/out_%03d.png", "/bin/sd-cli", {"models": {}},
            taesd_path="/fake/taew2_1.safetensors",
            preview_method="tae", preview_path="/tmp/live_%03d.png",
            preview_interval=2, tae_preview_only=True)
        self.assertIn("--taesd", cmd)
        self.assertIn("--taesd-preview-only", cmd)
        self.assertIn("--preview", cmd)

    def test_build_command_taesd_without_preview_only(self):
        # TAE seul (aperçu désactivé) : on ne bascule pas le décodage final
        cmd = build_command(
            "qwen-image-2512", "Q4_K_M", "a cat", "", 512, 512, 4, 1.0, 42, 1,
            "/tmp/out_%03d.png", "/bin/sd-cli", {"models": {}},
            taesd_path="/fake/taew2_1.safetensors")
        self.assertIn("--taesd", cmd)
        self.assertNotIn("--taesd-preview-only", cmd)

    def test_build_command_pulid_flux_only(self):
        kwargs = dict(pulid_weights="/fake/pulid.safetensors",
                      pulid_id_embedding="/fake/id.pulidembd",
                      pulid_id_weight=0.8)
        cmd = build_command(
            "flux-schnell", "Q4_K_M", "a cat", "", 512, 512, 4, 1.0, 42, 1,
            "/tmp/out_%03d.png", "/bin/sd-cli", {"models": {}}, **kwargs)
        self.assertIn("--pulid-weights", cmd)
        self.assertIn("--pulid-id-embedding", cmd)
        self.assertIn("--pulid-id-weight", cmd)
        self.assertIn("0.8", cmd)
        # architecture non FLUX : les flags PuLID sont ignorés silencieusement
        cmd2 = build_command(
            "sd3.5-large", MODELS["sd3.5-large"]["default_quant"],
            "a cat", "", 512, 512, 4, 1.0, 42, 1,
            "/tmp/out_%03d.png", "/bin/sd-cli", {"models": {}}, **kwargs)
        self.assertNotIn("--pulid-weights", cmd2)

    def test_build_command_pulid_weight_clamped(self):
        cmd = build_command(
            "flux-schnell", "Q4_K_M", "a cat", "", 512, 512, 4, 1.0, 42, 1,
            "/tmp/out_%03d.png", "/bin/sd-cli", {"models": {}},
            pulid_weights="/fake/pulid.safetensors",
            pulid_id_embedding="/fake/id.pulidembd",
            pulid_id_weight=99)
        wi = cmd.index("--pulid-id-weight")
        self.assertEqual(float(cmd[wi + 1]), PULID["max_weight"])

    def test_build_adetailer_command(self):
        cmd = build_adetailer_command(
            "flux-schnell", "Q4_K_M", "in.png", "out.png", "/bin/sd-cli",
            {"models": {}}, "/fake/face_yolov8n.safetensors",
            prompt="portrait", seed=1, denoise=0.4)
        self.assertIn("-M", cmd)
        self.assertEqual(cmd[cmd.index("-M") + 1], "adetailer")
        self.assertIn("--ad-model", cmd)
        self.assertIn("--extra-ad-args", cmd)
        self.assertIn("denoising_strength=0.4", "".join(cmd))
        self.assertIn("-i", cmd) and self.assertIn("in.png", cmd)

    def test_pid_status_missing_files(self):
        with patch.object(registry, "PID_DIR", Path("/nonexistent-lis")):
            st = pid_status()
            self.assertFalse(st["downloaded"])
            self.assertEqual(st["ready_backbones"], [])
            self.assertFalse(st["shared"]["ready"])
            for bb in st["backbones"].values():
                self.assertFalse(bb["ready"])

    def test_pid_status_with_fake_weights(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            gemma = tmp / PID["gemma"]["dest_name"]
            tok = tmp / PID["tokenizer"]["dest_name"]
            model = tmp / PID["backbones"]["flux1"]["filename"]
            gemma.write_bytes(b"g" * 64)
            tok.write_bytes(b"t" * 64)
            model.write_bytes(b"m" * 64)
            flux_vae = Path(DEPS["vae_flux"]["dest"])
            flux_vae.parent.mkdir(parents=True, exist_ok=True)
            created_vae = not flux_vae.exists()
            if created_vae:
                flux_vae.write_bytes(b"v" * 64)
            try:
                with patch.object(registry, "PID_DIR", tmp), \
                     patch.object(registry, "PID_GEMMA_MIN_BYTES", 1), \
                     patch.object(registry, "PID_TOKENIZER_MIN_BYTES", 1), \
                     patch.object(registry, "PID_MODEL_MIN_BYTES", 1), \
                     patch.object(registry, "PID_VAE_MIN_BYTES", 1):
                    st = pid_status()
                    self.assertTrue(st["downloaded"])
                    self.assertIn("flux1", st["ready_backbones"])
                    self.assertTrue(st["backbones"]["flux1"]["ready"])
                    self.assertFalse(st["backbones"]["flux2"]["ready"])
            finally:
                if created_vae:
                    flux_vae.unlink(missing_ok=True)

    def test_pid_arch_mapping(self):
        self.assertEqual(pid_backbone_for_arch("flux"), "flux1")
        self.assertEqual(pid_backbone_for_arch("flux_kontext"), "flux1")
        self.assertEqual(pid_backbone_for_arch("chroma"), "flux1")
        self.assertEqual(pid_backbone_for_arch("zimage"), "flux1")
        self.assertEqual(pid_backbone_for_arch("flux2"), "flux2")
        self.assertEqual(pid_backbone_for_arch("qwen_image"), "qwenimage")
        self.assertIsNone(pid_backbone_for_arch("sd3"))
        self.assertIsNone(pid_backbone_for_arch(None))

    def test_pid_vae_deps_exist(self):
        for bb in PID["backbones"].values():
            self.assertIn(bb["vae_dep"], DEPS)

    def test_pid_tokenizer_source_is_not_gated(self):
        # Le tokenizer Gemma 2 provient du miroir non-gated unsloth (le dépôt
        # officiel google/gemma-2-2b est gated).
        self.assertEqual(PID["tokenizer"]["repo"], "unsloth/gemma-2-2b-it")
        self.assertEqual(PID["gemma"]["repo"], "Comfy-Org/PixelDiT")

    def test_build_pid_command(self):
        cmd = build_pid_command("/bin/sd-cli", "in.png", "out.png",
                                "/fake/pid.safetensors", "/fake/gemma.safetensors",
                                "/fake/tokenizer_gemma2.json", "/fake/ae.safetensors",
                                "flux", "un chat", seed=7)
        self.assertEqual(cmd[cmd.index("--diffusion-model") + 1], "/fake/pid.safetensors")
        self.assertEqual(cmd[cmd.index("--llm") + 1], "/fake/gemma.safetensors")
        self.assertEqual(cmd[cmd.index("--tokenizer") + 1], "/fake/tokenizer_gemma2.json")
        self.assertEqual(cmd[cmd.index("--vae-format") + 1], "flux")
        self.assertEqual(cmd[cmd.index("-r") + 1], "in.png")
        self.assertEqual(cmd[cmd.index("-p") + 1], "un chat")
        self.assertEqual(cmd[cmd.index("--steps") + 1], "4")
        self.assertEqual(cmd[cmd.index("-H") + 1], "4096")
        self.assertEqual(cmd[cmd.index("-W") + 1], "4096")
        self.assertEqual(cmd[cmd.index("-s") + 1], "7")
        self.assertEqual(cmd[cmd.index("-o") + 1], "out.png")

    def test_build_seedvr2_command(self):
        cmd = build_seedvr2_command("/bin/sd-cli", "in.png", "out.png",
                                    "/fake/seedvr2.safetensors",
                                    "/fake/seedvr2_vae.safetensors",
                                    upscale_factor=2, seed=7)
        self.assertEqual(cmd[cmd.index("-M") + 1], "vid_upscale")
        self.assertEqual(cmd[cmd.index("--upscale-factor") + 1], "2")
        self.assertEqual(cmd[cmd.index("-s") + 1], "7")
        self.assertIn("--diffusion-model", cmd)
        self.assertIn("--vae", cmd)


# --------------------------------------------------------------------------- #
#  Moteur : classification des tâches
# --------------------------------------------------------------------------- #
class EngineKindTests(unittest.TestCase):
    def test_kind_of_task_kinds(self):
        self.assertEqual(engine.TaskManager._kind_of({"task_kind": "upscale"}), "upscale")
        self.assertEqual(engine.TaskManager._kind_of({"task_kind": "repair"}), "repair")
        self.assertEqual(engine.TaskManager._kind_of({"task_kind": "restore_x2"}), "restore_x2")
        self.assertEqual(engine.TaskManager._kind_of({"task_kind": "pid"}), "pid")
        self.assertEqual(engine.TaskManager._kind_of({}), "generate")
        self.assertEqual(engine.TaskManager._kind_of({"task_kind": "autre"}), "generate")

    def test_queue_summaries_for_new_kinds(self):
        for kind, model_name_part in (("repair", "🙂"),
                                      ("restore_x2", "SeedVR2"),
                                      ("pid", "PiD")):
            item = engine.tasks._build_queue_item(
                {"task_kind": kind, "source_image": "output/foo.png",
                 "detector_id": "face_yolov8n"})
            self.assertEqual(item["params"]["task_kind"], kind)
            self.assertIn(model_name_part, item["summary"]["model_name"])


# --------------------------------------------------------------------------- #
#  API : nouvelles routes (test_client)
# --------------------------------------------------------------------------- #
class FeatureApiTests(unittest.TestCase):
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

    def test_quality_info_exposes_new_sections(self):
        r = self.client.get("/api/quality-info")
        self.assertEqual(r.status_code, 200)
        j = r.get_json()
        for key in ("seedvr2", "taesd", "pulid", "pid", "quant_recommendations", "vram_gb"):
            self.assertIn(key, j)
        self.assertIn("backbones", j["pid"])
        self.assertIn("status", j["pid"])
        self.assertEqual(len(j["taesd"]), 2)
        self.assertIn("status", j["pulid"])

    def test_repair_rejects_unknown_detector(self):
        r = self.client.post("/api/repair", json={"detector_id": "nope"})
        self.assertEqual(r.status_code, 400)

    def test_repair_errors_when_none_installed(self):
        with patch.object(app, "adetailer_status",
                          lambda did: {"downloaded": False, "path": None}):
            r = self.client.post("/api/repair", json={"path": "image.png"})
        self.assertEqual(r.status_code, 400)

    def test_repair_happy_path_queues_task(self):
        (self.output / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 4096)
        captured = {}

        def fake_enqueue(params):
            captured["params"] = dict(params)
            return {"queued": False, "started": True}

        with patch.object(app, "adetailer_status",
                          lambda did: {"downloaded": True, "path": "/fake/d.safetensors"}), \
             patch.object(engine.tasks, "enqueue_generate", fake_enqueue), \
             patch.object(app.tasks, "enqueue_generate", fake_enqueue):
            r = self.client.post("/api/repair",
                                 json={"path": "image.png",
                                       "detector_id": "face_yolov8n"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(captured["params"]["task_kind"], "repair")
        self.assertEqual(captured["params"]["source_image"], "output/image.png")

    def test_restore_x2_requires_seedvr2(self):
        with patch.object(app, "seedvr2_status",
                          lambda: {"downloaded": False}):
            r = self.client.post("/api/restore-x2", json={"path": "x.png"})
        self.assertEqual(r.status_code, 400)

    def test_restore_x2_happy_path(self):
        (self.output / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 4096)
        captured = {}

        def fake_enqueue(params):
            captured["params"] = dict(params)
            return {"queued": True, "position": 1}

        with patch.object(app, "seedvr2_status",
                          lambda: {"downloaded": True, "diffusion": True,
                                   "vae": True, "paths": ["/fake/a", "/fake/b"]}), \
             patch.object(engine.tasks, "enqueue_generate", fake_enqueue), \
             patch.object(app.tasks, "enqueue_generate", fake_enqueue):
            r = self.client.post("/api/restore-x2", json={"path": "image.png"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(captured["params"]["task_kind"], "restore_x2")

    def test_pid_upscale_requires_install(self):
        with patch.object(app, "pid_status",
                          lambda: {"downloaded": False,
                                   "ready_backbones": [],
                                   "shared": {"ready": False},
                                   "backbones": {bb: {"ready": False} for bb in PID["backbones"]}}):
            r = self.client.post("/api/pid-upscale", json={"path": "x.png"})
        self.assertEqual(r.status_code, 400)

    def test_pid_upscale_rejects_unknown_backbone(self):
        fake = {"downloaded": True, "ready_backbones": ["flux1"],
                "shared": {"ready": True},
                "backbones": {bb: {"ready": bb == "flux1"} for bb in PID["backbones"]}}
        with patch.object(app, "pid_status", lambda: fake):
            r = self.client.post("/api/pid-upscale", json={"path": "x.png", "backbone": "nope"})
            self.assertEqual(r.status_code, 400)
            r = self.client.post("/api/pid-upscale", json={"path": "x.png", "backbone": "flux2"})
            self.assertEqual(r.status_code, 400)

    def test_pid_upscale_happy_path(self):
        (self.output / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 4096)
        fake = {"downloaded": True, "ready_backbones": ["flux1"],
                "shared": {"ready": True},
                "backbones": {bb: {"ready": bb == "flux1",
                                   "model": bb == "flux1", "vae": bb == "flux1",
                                   "vae_dep": "vae_flux"} for bb in PID["backbones"]}}
        captured = {}

        def fake_enqueue(params):
            captured["params"] = dict(params)
            return {"queued": True, "position": 1}

        img_id = db.add_image(batch_id="b", idx=0, model_id="flux-schnell",
                              model_name="FLUX.1 Schnell", quant="Q4_K_M",
                              prompt="un chat", negative="", seed=42,
                              width=1024, height=1024, steps=4, cfg=1.0,
                              sampler="euler", filename="image.png",
                              batch_size=1, gen_time=1.0)

        # 1) via image_id (image présente dans l'historique)
        with patch.object(app, "pid_status", lambda: fake), \
             patch.object(engine.tasks, "enqueue_generate", fake_enqueue), \
             patch.object(app.tasks, "enqueue_generate", fake_enqueue):
            r = self.client.post("/api/pid-upscale",
                                 json={"image_id": img_id})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(captured["params"]["task_kind"], "pid")
        self.assertEqual(captured["params"]["image_id"], img_id)

        # 2) via path direct (sans image_id)
        captured.clear()
        with patch.object(app, "pid_status", lambda: fake), \
             patch.object(engine.tasks, "enqueue_generate", fake_enqueue), \
             patch.object(app.tasks, "enqueue_generate", fake_enqueue):
            r = self.client.post("/api/pid-upscale", json={"path": "image.png"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(captured["params"]["task_kind"], "pid")
        self.assertEqual(captured["params"]["source_image"], "output/image.png")

    def test_download_pid_rejects_unknown_backbone(self):
        r = self.client.post("/api/download-pid", json={"backbone": "nope"})
        self.assertEqual(r.status_code, 400)

    def test_download_pid_happy_path(self):
        captured = {}

        def fake_start(backbone):
            captured["backbone"] = backbone

        with patch.object(app.tasks, "start_pid_download", fake_start):
            r = self.client.post("/api/download-pid", json={"backbone": "flux1"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(captured["backbone"], "flux1")

    def test_image_meta_rejects_garbage(self):
        data = {"image": (io.BytesIO(b"pas un png du tout"), "fake.png")}
        r = self.client.post("/api/image-meta", data=data,
                             content_type="multipart/form-data")
        self.assertEqual(r.status_code, 422)

    @unittest.skipUnless(PIL_OK, "Pillow requis pour le roundtrip PNG")
    def test_image_meta_roundtrip(self):
        buf = io.BytesIO()
        txt = metadata.build_webui_text(prompt="mon prompt", seed=321,
                                        steps=6, cfg=1.0, model_id="flux-schnell",
                                        width=320, height=256)
        pnginfo = PngImagePlugin.PngInfo()
        pnginfo.add_text("parameters", txt)
        Image.new("RGB", (320, 256), (10, 20, 30)).save(buf, format="PNG", pnginfo=pnginfo)
        buf.seek(0)
        r = self.client.post("/api/image-meta",
                             data={"image": (buf, "capture.png")},
                             content_type="multipart/form-data")
        self.assertEqual(r.status_code, 200)
        j = r.get_json()
        self.assertTrue(j["ok"])
        self.assertEqual(j["form"]["prompt"], "mon prompt")
        self.assertEqual(j["form"]["seed"], 321)
        self.assertEqual(j["form"]["model"], "flux-schnell")

    def test_batch_requires_prompts(self):
        r = self.client.post("/api/batch", json={"model_id": "flux-schnell",
                                                 "prompts": ""})
        self.assertEqual(r.status_code, 400)

    def test_batch_rejects_too_many_lines(self):
        prompts = "\n".join(f"prompt {i}" for i in range(17))
        r = self.client.post("/api/batch", json={"model_id": "flux-schnell",
                                                 "prompts": prompts})
        self.assertEqual(r.status_code, 400)

    def test_batch_unknown_model(self):
        r = self.client.post("/api/batch", json={"model_id": "nope",
                                                 "prompts": "a\nb"})
        self.assertEqual(r.status_code, 400)

    def test_quant_recommendation_endpoint(self):
        r = self.client.get("/api/quant-recommendation?model_id=flux-schnell&vram_gb=24")
        self.assertEqual(r.status_code, 200)
        j = r.get_json()
        self.assertTrue(j["ok"])
        self.assertIn("quant", j)
        self.assertEqual(j["vram_gb"], 24.0)

    def test_pulid_extract_fails_cleanly_without_weights(self):
        portrait = self.sources / "p.jpg"
        portrait.write_bytes(b"\xff\xd8\xff" + b"0" * 100)
        with patch.object(app, "pulid_weights_path") as mock_path:
            mock_path.return_value = self.root / "noweights.safetensors"
            r = self.client.post("/api/pulid-extract",
                                 json={"portrait": "p.jpg", "name": "test"})
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()


class TestLivePreviewWiring(unittest.TestCase):
    """L'aperçu en direct doit être câblé sur Générer ET Édition (markup + JS)."""

    ROOT = Path(__file__).resolve().parent.parent

    def test_generate_template_has_live_preview_wrap(self):
        html = (self.ROOT / "src/templates/generate.html").read_text(encoding="utf-8")
        self.assertIn('id="live-preview-wrap"', html)
        self.assertIn('id="live-preview-waiting"', html)

    def test_edit_template_has_live_preview_wrap(self):
        html = (self.ROOT / "src/templates/edit.html").read_text(encoding="utf-8")
        self.assertIn('id="live-preview-wrap"', html)
        self.assertIn('id="live-preview-waiting"', html)

    def test_edit_js_polls_preview_endpoint(self):
        js = (self.ROOT / "src/static/edit.js").read_text(encoding="utf-8")
        self.assertIn("updateLivePreview", js)
        self.assertIn("'/api/preview'", js)
        self.assertIn("preview_batch_id", js)

    def test_generate_js_polls_preview_endpoint(self):
        js = (self.ROOT / "src/static/generate.js").read_text(encoding="utf-8")
        self.assertIn("'/api/preview'", js)
        self.assertIn("preview_batch_id", js)

    def test_api_preview_route_registered(self):
        self.assertTrue(any(r.rule == "/api/preview" for r in app.app.url_map.iter_rules()))
