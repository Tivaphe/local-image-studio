import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import app as studio_app
import config
import db
import engine
import registry


def _flag_value(cmd: list[str], flag: str) -> str:
    idx = cmd.index(flag)
    return cmd[idx + 1]


def _fake_dep_path(manifest, dep_id):
    dep = registry.DEPS[dep_id]
    if "dest" in dep:
        return str(dep["dest"])
    return str(dep["dest_dir"] / f"{dep_id}.gguf")


class OutpaintRegistryAndCommandTests(unittest.TestCase):
    def setUp(self):
        self.manifest = {}
        self.dep_patch = patch.object(registry, "_dep_path", side_effect=_fake_dep_path)
        self.dep_patch.start()

    def tearDown(self):
        self.dep_patch.stop()

    def test_flux1_fill_dev_registered_and_guarded(self):
        self.assertIn("flux1-fill-dev", registry.MODELS)
        m = registry.MODELS["flux1-fill-dev"]
        self.assertEqual(m["arch"], "flux_fill")
        self.assertTrue(m["inpaint_only"])
        self.assertTrue(registry.supports_outpaint("flux1-fill-dev"))
        self.assertEqual(registry.outpaint_mode("flux1-fill-dev"), "fill")
        self.assertEqual(registry.input_modes("flux1-fill-dev"), ["outpaint"])
        for q in m["quants"]:
            self.assertIn(q, m["file_for_quant"])
            self.assertTrue(m["file_for_quant"][q].endswith(".gguf"))

        # Refuse text-to-image sans image
        _, _, err = registry.check_images_input("flux1-fill-dev", [])
        self.assertIsNotNone(err)

        # Refuse outpaint sans masque
        _, _, err = registry.check_images_input(
            "flux1-fill-dev", ["source_images/pad.png"], "outpaint", mask_image=None
        )
        self.assertIsNotNone(err)

        # Accepte outpaint avec image étendue + masque
        imgs, mode, err = registry.check_images_input(
            "flux1-fill-dev",
            ["source_images/pad.png"],
            "outpaint",
            mask_image="source_images/mask.png",
        )
        self.assertIsNone(err)
        self.assertEqual(mode, "outpaint")
        self.assertEqual(imgs, ["source_images/pad.png"])

    def test_flux1_fill_dev_build_command(self):
        cmd = registry.build_command(
            "flux1-fill-dev", "Q5_K_S",
            prompt="wide alpine valley with pine trees",
            negative="",
            width=1536, height=1024, steps=28, cfg=1.0,
            seed=123, batch=2, out_template="/tmp/out_%03d.png",
            sd_cli="/bin/sd-cli", manifest=self.manifest,
            source_image="source_images/pad.png",
            input_mode="outpaint",
            mask_image="source_images/mask.png",
        )
        self.assertTrue(_flag_value(cmd, "--diffusion-model").endswith("flux1-fill-dev-Q5_K_S.gguf"))
        self.assertTrue(_flag_value(cmd, "--vae").endswith("ae.safetensors"))
        self.assertIn("--clip_l", cmd)
        self.assertIn("--t5xxl", cmd)
        self.assertIn("--clip-on-cpu", cmd)
        self.assertEqual(_flag_value(cmd, "-i"), "source_images/pad.png")
        self.assertEqual(_flag_value(cmd, "--mask"), "source_images/mask.png")
        self.assertEqual(float(_flag_value(cmd, "--strength")), 1.0)
        self.assertEqual(float(_flag_value(cmd, "--cfg-scale")), 1.0)
        self.assertEqual(float(_flag_value(cmd, "--guidance")), 30.0)
        self.assertNotIn("-r", cmd)

    def test_qwen_image_outpaint_uses_ref_and_mask_and_mmproj(self):
        self.assertEqual(registry.outpaint_mode("qwen-image-2.1-turbo"), "ref_mask")
        self.assertIn("outpaint", registry.input_modes("qwen-image-2.1-turbo"))
        # Le mode par défaut reste "ref" pour ne pas casser l'édition classique
        self.assertEqual(registry.input_modes("qwen-image-2.1-turbo")[0], "ref")

        q = registry.MODELS["qwen-image-2.1-turbo"]["default_quant"]
        cmd = registry.build_command(
            "qwen-image-2.1-turbo", q,
            prompt="vast sunlit beach panorama",
            negative="",
            width=1536, height=1024, steps=8, cfg=1.0,
            seed=7, batch=1, out_template="/tmp/out_%03d.png",
            sd_cli="/bin/sd-cli", manifest=self.manifest,
            source_image="source_images/pad.png",
            ref_images=["source_images/pad.png", "source_images/style.png"],
            input_mode="outpaint",
            mask_image="source_images/mask.png",
        )
        r_vals = [cmd[i + 1] for i, tok in enumerate(cmd) if tok == "-r"]
        self.assertEqual(r_vals, ["source_images/pad.png", "source_images/style.png"])
        self.assertEqual(_flag_value(cmd, "-i"), "source_images/pad.png")
        self.assertEqual(_flag_value(cmd, "--mask"), "source_images/mask.png")
        self.assertEqual(float(_flag_value(cmd, "--strength")), 1.0)
        self.assertIn("--llm_vision", cmd)
        self.assertIn("qwen_image_zero_cond_t=true", cmd)

    def test_sd35_outpaint_uses_init_mask(self):
        self.assertEqual(registry.outpaint_mode("sd3.5-large"), "init_mask")
        q = registry.MODELS["sd3.5-large"]["default_quant"]
        cmd = registry.build_command(
            "sd3.5-large", q,
            prompt="forest canopy extending upward",
            negative="blurry",
            width=1024, height=1536, steps=30, cfg=4.5,
            seed=99, batch=1, out_template="/tmp/out_%03d.png",
            sd_cli="/bin/sd-cli", manifest=self.manifest,
            source_image="source_images/pad.png",
            input_mode="outpaint",
            mask_image="source_images/mask.png",
        )
        self.assertEqual(_flag_value(cmd, "-i"), "source_images/pad.png")
        self.assertEqual(_flag_value(cmd, "--mask"), "source_images/mask.png")
        self.assertEqual(float(_flag_value(cmd, "--strength")), 1.0)
        self.assertNotIn("-r", cmd)

    def test_text_only_models_do_not_advertise_outpaint(self):
        for mid in ("flux-schnell", "z-image", "krea2-turbo"):
            self.assertFalse(registry.supports_outpaint(mid), mid)
            self.assertIsNone(registry.outpaint_mode(mid), mid)
            _, _, err = registry.check_images_input(
                mid, ["source_images/pad.png"], "outpaint", mask_image="source_images/mask.png"
            )
            self.assertIsNotNone(err)


class OutpaintEndToEndAndRoutesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.output_dir = self.root / "output"
        self.source_dir = self.root / "source_images"
        self.db_path = self.root / "history.db"
        self.output_dir.mkdir()
        self.source_dir.mkdir()

        self.patches = [
            patch.object(config, "ROOT", self.root),
            patch.object(config, "OUTPUT_DIR", self.output_dir),
            patch.object(config, "SOURCE_IMAGES_DIR", self.source_dir),
            patch.object(config, "DB_PATH", self.db_path),
            patch.object(engine, "ROOT", self.root),
            patch.object(engine, "OUTPUT_DIR", self.output_dir),
            patch.object(engine, "SOURCE_IMAGES_DIR", self.source_dir),
            patch.object(db, "DB_PATH", self.db_path),
        ]
        for p in self.patches:
            p.start()
        db.init_db()
        self.client = studio_app.app.test_client()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def test_pages_and_api_models_expose_outpaint_and_viewer(self):
        res = self.client.get("/api/models")
        self.assertEqual(res.status_code, 200)
        models = res.get_json()
        self.assertIn("flux1-fill-dev", models)
        self.assertTrue(models["flux1-fill-dev"]["supports_outpaint"])
        self.assertTrue(models["flux1-fill-dev"]["inpaint_only"])
        self.assertEqual(models["flux1-fill-dev"]["outpaint_mode"], "fill")
        self.assertEqual(models["flux1-fill-dev"]["distilled_guidance"], 30.0)
        self.assertTrue(models["qwen-image-2.1"]["supports_outpaint"])
        self.assertFalse(models["flux-schnell"]["supports_outpaint"])

        for route in ("/generate", "/edit", "/history", "/models"):
            r = self.client.get(route)
            self.assertEqual(r.status_code, 200, route)

        edit_html = self.client.get("/edit").get_data(as_text=True)
        self.assertIn("data-studio-mode=\"outpaint\"", edit_html)
        self.assertIn("outpaint-preview-canvas", edit_html)

        models_html = self.client.get("/models").get_data(as_text=True)
        self.assertIn("FLUX.1 Fill [dev]", models_html)
        self.assertIn("Dédié Outpaint", models_html)

    def test_outpaint_execution_cleans_temp_files_and_persists_clean_original_source(self):
        orig = self.source_dir / "orig.png"
        padded = self.source_dir / "padded.png"
        mask = self.source_dir / "mask.png"
        for f, payload in ((orig, b"orig"), (padded, b"padded"), (mask, b"mask")):
            f.write_bytes(payload)

        captured = {}

        class FakeProc:
            def __init__(self, cmd, **kwargs):
                captured["cmd"] = cmd
                # Vérifie que les fichiers temporaires existent bien au lancement de sd-cli
                captured["padded_existed"] = padded.exists()
                captured["mask_existed"] = mask.exists()
                idx = cmd.index("-o")
                out_tmpl = Path(cmd[idx + 1])
                (out_tmpl.parent / (out_tmpl.name % 1)).write_bytes(b"outpainted-png")
                self.stdout = iter(["step 1/28\n", "step 28/28\n"])

            def wait(self):
                return 0

        with patch.object(engine, "find_sd_cli", return_value="/fake/sd-cli"), \
             patch.object(engine, "_model_present", return_value=True), \
             patch.object(engine, "_dep_present", return_value=True), \
             patch.object(registry, "_dep_path", side_effect=_fake_dep_path), \
             patch.object(engine, "_dep_path", side_effect=_fake_dep_path), \
             patch.object(engine, "load_manifest", return_value={}), \
             patch.object(engine.subprocess, "Popen", FakeProc):
            res = self.client.post("/api/generate", json={
                "model_id": "flux1-fill-dev",
                "quant": "Q5_K_S",
                "prompt": "extended snowy mountain landscape",
                "width": 1536,
                "height": 1024,
                "steps": 28,
                "cfg": 1.0,
                "batch": 1,
                "input_mode": "outpaint",
                "ref_images": ["source_images/padded.png"],
                "mask_image": "source_images/mask.png",
                "history_sources": ["source_images/orig.png"],
                "temp_sources": ["source_images/padded.png", "source_images/mask.png"],
            })
            self.assertEqual(res.status_code, 200, res.get_json())

            deadline = time.time() + 5
            while studio_app.tasks.snapshot()["busy"] and time.time() < deadline:
                time.sleep(0.02)

        snap = studio_app.tasks.snapshot()
        self.assertIsNone(snap["error"])
        self.assertTrue(captured.get("padded_existed"))
        self.assertTrue(captured.get("mask_existed"))
        self.assertIn("--mask", captured["cmd"])
        self.assertEqual(_flag_value(captured["cmd"], "--mask"), "source_images/mask.png")

        # Les fichiers temporaires padded/mask ont été nettoyés, mais l'original est intact
        self.assertTrue(orig.exists())
        self.assertFalse(padded.exists())
        self.assertFalse(mask.exists())

        # L'historique référence bien l'image originale non-paddée
        rows = db.list_images()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_images_list"], ["source_images/orig.png"])
        self.assertTrue(db.source_is_referenced("source_images/orig.png"))


if __name__ == "__main__":
    unittest.main()
