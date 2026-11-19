"""PiD ×4 — le prompt de reconstruction ne doit plus être deviné aveuglément.

Bug signalé : sur les images éditées (ou post-traitées / sans prompt fiable),
PiD conditionnait sa super-résolution générative au prompt d'édition → image
reconstruite dans la mauvaise direction (« sûrement horrible »).

Correctifs couverts :
- registry.prompt_looks_like_edit_instruction (heuristique FR/EN)
- engine.resolve_pid_prompt (explicit > historique descriptif > générique)
- /api/pid-upscale transmet le prompt explicite à la tâche
- câblage JS/HTML : modale de confirmation partagée
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import app
import config
import db
import engine
import registry

DEFAULT = registry.pid_default_prompt()


class PromptHeuristicTests(unittest.TestCase):
    def test_edit_instruction_prompts_flagged(self):
        for txt in [
            "Keep the subject and composition of <image1> unchanged, redraw the image as a watercolor",
            "keep the subject in image 1, change the background to a beach",
            "Garde le sujet inchangé, redessine le reste en style ukiyo-e",
            "Replace the sky in image 1 with a sunset, keep the buildings",
            "modifie la couleur du manteau en rouge",
            "inpaint the masked region with grass",
            "Post-traitement de image_pere.png (contraste +30)",
            "outpaint to a wide panorama",
            "post-processing of the portrait",
        ]:
            self.assertTrue(registry.prompt_looks_like_edit_instruction(txt), txt)

    def test_content_prompts_not_flagged(self):
        for txt in [
            "a young woman with red hair in a forest, soft golden light, 85mm portrait",
            "masterpiece, best quality, ultra detailed, sharp focus",
            "portrait d'un renard roux dans la neige, lumière douce",
            "cyberpunk city street at night, neon signs, rain, cinematic",
            "a castle on a hill at dawn, mist, highly detailed",
        ]:
            self.assertFalse(registry.prompt_looks_like_edit_instruction(txt), txt)

    def test_empty_is_not_edit_instruction(self):
        self.assertFalse(registry.prompt_looks_like_edit_instruction(""))
        self.assertFalse(registry.prompt_looks_like_edit_instruction(None))


class ResolvePidPromptTests(unittest.TestCase):
    def test_explicit_prompt_wins(self):
        prompt, source = engine.resolve_pid_prompt(
            "un renard roux dans la neige", {"prompt": "keep the subject", "model_id": "qwen-image-2.1"},
            DEFAULT)
        self.assertEqual((prompt, source), ("un renard roux dans la neige", "explicit"))

    def test_postprocess_entry_falls_back_to_default(self):
        prompt, source = engine.resolve_pid_prompt(
            "", {"prompt": "Post-traitement de img.png (contraste +30)", "model_id": "postprocess"},
            DEFAULT)
        self.assertEqual((prompt, source), (DEFAULT, "generic_postprocess"))

    def test_edit_instruction_entry_falls_back_to_default(self):
        prompt, source = engine.resolve_pid_prompt(
            "", {"prompt": "Keep the subject of <image1>, redraw as ukiyo-e", "model_id": "fibo2-dev"},
            DEFAULT)
        self.assertEqual((prompt, source), (DEFAULT, "generic_edit_instruction"))

    def test_genuine_content_entry_is_used(self):
        prompt, source = engine.resolve_pid_prompt(
            "  ", {"prompt": "portrait d'un renard roux dans la neige", "model_id": "z-image"},
            DEFAULT)
        self.assertEqual((prompt, source), ("portrait d'un renard roux dans la neige", "history"))

    def test_empty_everything_returns_default(self):
        self.assertEqual(engine.resolve_pid_prompt("", None, DEFAULT), (DEFAULT, "generic_default"))
        self.assertEqual(engine.resolve_pid_prompt("", {"prompt": "  ", "model_id": "z-image"},
                                                    DEFAULT), (DEFAULT, "generic_default"))


class PidUpscaleApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.output = self.root / "output"
        self.sources = self.root / "source_images"
        self.portraits = self.root / "portraits"
        self.output.mkdir()
        self.sources.mkdir()
        self.portraits.mkdir()
        (self.output / "src.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
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

    def _ready_pid(self):
        return {"downloaded": True,
                "backbones": {"flux2": {"ready": True}, "flux1": {"ready": False}, "qwen": {"ready": False}},
                "ready_backbones": ["flux2"]}

    def test_explicit_prompt_reaches_task(self):
        captured = {}
        fake_result = {"queued": False, "position": 0, "task_token": "tok123"}

        def fake_enqueue(params):
            captured.update(params)
            return fake_result

        with patch.object(app, "pid_status", self._ready_pid), \
             patch.object(app, "_resolve_source_image", return_value=("output/src.png", None)), \
             patch.object(engine.tasks, "enqueue_generate", side_effect=fake_enqueue):
            r = self.client.post("/api/pid-upscale",
                                 json={"image_id": None, "path": "output/src.png",
                                       "prompt": "a red fox in deep snow, detailed fur"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(captured.get("prompt"), "a red fox in deep snow, detailed fur")

    def test_empty_prompt_stays_empty_for_server_side_policy(self):
        captured = {}

        def fake_enqueue(params):
            captured.update(params)
            return {"queued": False, "position": 0, "task_token": "tok"}

        with patch.object(app, "pid_status", self._ready_pid), \
             patch.object(app, "_resolve_source_image", return_value=("output/src.png", None)), \
             patch.object(engine.tasks, "enqueue_generate", side_effect=fake_enqueue):
            r = self.client.post("/api/pid-upscale", json={"path": "output/src.png"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(captured.get("prompt"), "")  # la politique (engine.resolve_pid_prompt) décide


class PidPromptWiringTests(unittest.TestCase):
    ROOT = ROOT

    def test_modal_included_and_wired(self):
        base = (self.ROOT / "src/templates/base.html").read_text(encoding="utf-8")
        self.assertIn("_pid_prompt.html", base)
        modal = (self.ROOT / "src/templates/_pid_prompt.html").read_text(encoding="utf-8")
        for pid in ("pid-prompt-modal", "pid-prompt-text", "pid-prompt-launch",
                    "pid-prompt-generic", "pid-prompt-warn"):
            self.assertIn(f'id="{pid}"', modal)

    def test_quality_js_asks_prompt_and_warns_on_edit_prompts(self):
        js = (self.ROOT / "src/static/quality.js").read_text(encoding="utf-8")
        self.assertIn("Q.askPidPrompt", js)
        self.assertIn("looksLikeEditPrompt", js)
        self.assertIn("/api/image/", js)      # pré-remplissage depuis l'historique
        self.assertIn("pid-prompt-generic", js)
        # makePidButton ne lance plus directement : il passe par la modale
        self.assertIn("askPidPrompt({ imageId, path, backbone })", js)
        self.assertNotIn("prompt repris de l'image", js)

    def test_history_wired_through_modal(self):
        hist = (self.ROOT / "src/templates/history.html").read_text(encoding="utf-8")
        self.assertIn("LisQuality.askPidPrompt", hist)


if __name__ == "__main__":
    unittest.main()
