# -*- coding: utf-8 -*-
"""Tests du mode « 🧠 Thinking » (Générer/Édition/Traduction/Enrichissement)."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import app
import config
import thinking


class SplitThinkTests(unittest.TestCase):
    def test_closed_block(self):
        reasoning, final = thinking.split_think("<think>étape 1, étape 2</think>\nUn chat sur un toit, lumière dorée.")
        self.assertEqual(reasoning, "étape 1, étape 2")
        self.assertIn("Un chat", final)

    def test_unterminated_block(self):
        reasoning, final = thinking.split_think("<think>réflexion coupée par le budget")
        self.assertIn("réflexion", reasoning)
        self.assertEqual(final, "")

    def test_no_block(self):
        reasoning, final = thinking.split_think("Just the prompt, no thinking.")
        self.assertEqual(reasoning, "")
        self.assertEqual(final, "Just the prompt, no thinking.")

    def test_multiple_blocks_and_prefix_cleanup(self):
        reasoning, final = thinking.split_think(
            "<think>a</think>\nFinal prompt: <think>b</think> a cat in Paris")
        self.assertIn("a", reasoning)
        self.assertIn("b", reasoning)
        self.assertEqual(final, "a cat in Paris")

    def test_quotes_stripped(self):
        _, final = thinking.split_think('"a quiet forest, misty morning"')
        self.assertEqual(final, "a quiet forest, misty morning")


class ResolveModelTests(unittest.TestCase):
    def test_explicit_thinking_model_wins(self):
        settings = {"thinking_model": "bonsai2_4b", "captioner_model": "qwen35_4b"}
        self.assertEqual(thinking.resolve_think_captioner_id(settings), "bonsai2_4b")

    def test_fallback_to_captioner_default(self):
        self.assertEqual(thinking.resolve_think_captioner_id({"captioner_model": "qwen35_4b"}), "qwen35_4b")
        self.assertEqual(thinking.resolve_think_captioner_id({"thinking_model": "qwen35_4b", "captioner_model": ""}), "qwen35_4b")

    def test_invalid_ids_are_rejected(self):
        self.assertEqual(thinking.resolve_think_captioner_id({"thinking_model": "modele-invente"}), "")
        self.assertEqual(thinking.resolve_think_captioner_id({"thinking_model": "", "captioner_model": "nope"}), "")
        self.assertEqual(thinking.resolve_think_captioner_id({}), "")


class ResolveImageTests(unittest.TestCase):
    def test_traversal_rejected(self):
        with self.assertRaises(ValueError):
            thinking._resolve_image("../../etc/passwd")

    def test_missing_file_rejected(self):
        with self.assertRaises(ValueError):
            thinking._resolve_image("source_images/does-not-exist-zzz.png")

    def test_valid_file_accepted(self):
        import tempfile, os
        with tempfile.TemporaryDirectory(dir=str(config.ROOT)) as td:
            rel = Path(td).relative_to(config.ROOT) / "ok.png"
            (config.ROOT / rel).write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
            self.assertTrue(thinking._resolve_image(str(rel)).exists())


class RunThinkTests(unittest.TestCase):
    def test_invalid_kind(self):
        with self.assertRaises(ValueError):
            thinking.run_think("wat", "un chat")

    def test_empty_text(self):
        with self.assertRaises(ValueError):
            thinking.run_think("generate", "   ")

    def test_cpu_fallback_for_text_tasks(self):
        with patch("registry.captioners_ready", return_value=[]), \
             patch("thinking._cpu_fallback", return_value=("a cat on the moon, cinematic light", "llama-cpp-python (CPU)")):
            out = thinking.run_think("generate", "un chat sur la lune", settings={})
        self.assertTrue(out["degraded"])
        self.assertEqual(out["model_id"], "qwen3_4b")
        self.assertIn("moon", out["prompt"])

    def test_edit_without_vlm_refuses(self):
        with patch("registry.captioners_ready", return_value=[]):
            with self.assertRaises(RuntimeError):
                thinking.run_think("edit", "mets un bonnet rouge", settings={})

    def test_server_path_splits_think(self):
        with patch("registry.captioner_files", return_value=("m.gguf", "mm.gguf")), \
             patch("engine.llama_available", return_value=("app", {"kind": "server", "path": "/fake/llama-server", "version": "b12366"})), \
             patch("engine._llama_version_status", return_value=(True, "ok")), \
             patch("thinking._server_chat", return_value=("<think>sujet, lumière</think>\nA red beanie on the subject, same pose.", "", "stop")):
            out = thinking.run_think("edit", "mets un bonnet rouge",
                                     image_rel=None,
                                     settings={"thinking_model": "bonsai2_4b"})
        self.assertEqual(out["prompt"], "A red beanie on the subject, same pose.")
        self.assertIn("lumière", out["reasoning"])
        self.assertFalse(out["degraded"])
        self.assertIn("bonsai2_4b", out["model_id"])

    def test_bonsai2_version_gate(self):
        with patch("registry.captioner_files", return_value=("m.gguf", "mm.gguf")), \
             patch("engine.llama_available", return_value=("app", {"kind": "server", "path": "/fake/llama-server", "version": "b10000"})), \
             patch("engine._llama_version_status", return_value=(False, "b11556 requis")):
            with self.assertRaises(RuntimeError):
                thinking.run_think("generate", "un chat", settings={"thinking_model": "bonsai2_4b"})


class ApiRoutesTests(unittest.TestCase):
    def setUp(self):
        self.client = app.app.test_client()

    def test_think_validation(self):
        r = self.client.post("/api/think", json={"kind": "nope", "text": "x"})
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/think", json={"kind": "generate", "text": "   "})
        self.assertEqual(r.status_code, 400)

    def test_think_ok(self):
        fake = {"prompt": "a cat", "reasoning": "because", "model_id": "bonsai2_4b",
                "model_name": "Bonsai-2 4B", "backend": "app · llama-server",
                "elapsed": 12.3, "degraded": False}
        with patch.object(app, "load_settings", lambda: {}), \
             patch.object(app.thinking, "run_think", return_value=fake):
            r = self.client.post("/api/think", json={"kind": "generate", "text": "un chat"})
        self.assertEqual(r.status_code, 200)
        j = r.get_json()
        self.assertTrue(j["ok"])
        self.assertEqual(j["prompt"], "a cat")
        self.assertEqual(j["reasoning"], "because")

    def test_think_runtime_error_maps_to_503(self):
        with patch.object(app, "load_settings", lambda: {}), \
             patch.object(app.thinking, "run_think", side_effect=RuntimeError("llama.cpp introuvable")):
            r = self.client.post("/api/think", json={"kind": "generate", "text": "un chat"})
        self.assertEqual(r.status_code, 503)
        self.assertIn("llama.cpp", r.get_json()["error"])

    def test_think_cancel_route(self):
        with patch.object(app.thinking, "cancel_current", return_value=False):
            r = self.client.post("/api/think-cancel")
        self.assertTrue(r.get_json()["ok"] is False)

    def test_translate_falls_back_to_cpu_enhancer(self):
        with patch.object(app, "load_settings", lambda: {}), \
             patch.object(app.thinking, "run_think", side_effect=RuntimeError("pas de llama.cpp")), \
             patch.object(app, "_ENHANCER_OK", True), \
             patch.object(app.prompt_enhancer, "enhancer_available", return_value=True), \
             patch.object(app.prompt_enhancer, "translate_prompt", return_value="a cat"):
            r = self.client.post("/api/translate", json={"prompt": "un chat"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["prompt"], "a cat")
        self.assertIn("CPU", r.get_json()["backend"])

    def test_translate_unavailable_everywhere(self):
        with patch.object(app, "load_settings", lambda: {}), \
             patch.object(app.thinking, "run_think", side_effect=RuntimeError("pas de llama.cpp")), \
             patch.object(app, "_ENHANCER_OK", False):
            r = self.client.post("/api/translate", json={"prompt": "un chat"})
        self.assertEqual(r.status_code, 400)

    def test_settings_whitelist_thinking_model(self):
        saved = {}

        def fake_load_settings():
            return dict(saved)

        def fake_save_settings(patch_dict):
            saved.update(patch_dict)

        with patch.object(app, "load_settings", fake_load_settings), \
             patch.object(app, "save_settings", fake_save_settings):
            r = self.client.post("/api/settings",
                                 json={"hf_token": "", "open_browser": False,
                                       "thinking_model": "modele-invente"})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(saved.get("thinking_model"), "")
            r = self.client.post("/api/settings",
                                 json={"hf_token": "", "open_browser": False,
                                       "thinking_model": "bonsai2_4b"})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(saved.get("thinking_model"), "bonsai2_4b")
            self.assertEqual(r.get_json()["thinking_model"], "bonsai2_4b")


class TemplateWiringTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parent.parent

    def test_toggle_and_modal_on_both_pages(self):
        for page in ("generate.html", "edit.html"):
            html = (self.ROOT / "src/templates" / page).read_text(encoding="utf-8")
            self.assertIn('id="thinking-toggle"', html, page)
            self.assertIn('thinking_modal.html', html, page)
            self.assertIn('thinking.js', html, page)

    def test_modal_and_js_assets_exist(self):
        modal = (self.ROOT / "src/templates/thinking_modal.html").read_text(encoding="utf-8")
        for token in ('id="thinking-final"', 'id="thinking-reasoning"', 'id="thinking-go"',
                      'id="thinking-cancel"', 'id="thinking-elapsed"', 'id="thinking-error"'):
            self.assertIn(token, modal)
        js = (self.ROOT / "src/static/thinking.js").read_text(encoding="utf-8")
        self.assertIn("lis_thinking", js)
        self.assertIn("/api/think", js)
        self.assertIn("maybeIntercept", js)

    def test_interception_present_in_generate_and_edit(self):
        for js_name in ("generate.js", "edit.js"):
            js = (self.ROOT / "src/static" / js_name).read_text(encoding="utf-8")
            self.assertIn("LisThinking", js, js_name)
            self.assertIn("maybeIntercept", js, js_name)
            self.assertIn("__lisThinkingSkip", js, js_name)

    def test_edit_sends_source_image_for_vision(self):
        js = (self.ROOT / "src/static/edit.js").read_text(encoding="utf-8")
        i = js.index("kind: 'edit'")
        window = js[i:i + 300]
        self.assertIn("canvas.path", window)


if __name__ == '__main__':
    unittest.main()
