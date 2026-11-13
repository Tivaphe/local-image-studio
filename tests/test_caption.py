"""Tests — 🔎 légendeurs d'image (vision LLM) : backend llama.cpp + routes."""

import io
import os
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
import registry


class CaptionParsingTests(unittest.TestCase):
    def test_strips_logs_think_and_quotes(self):
        raw = (
            "llama_model_loader: loaded\n"
            "print_info: 5555 tensors\n"
            "<think>\nI should describe it\n</think>\n"
            "  \"A red teapot on a wooden table, soft window light, shallow depth of field.\"  \n"
        )
        out = engine.parse_caption_output(raw)
        self.assertEqual(out, "A red teapot on a wooden table, soft window light, shallow depth of field.")

    def test_rejects_empty_or_noise(self):
        with self.assertRaises(ValueError):
            engine.parse_caption_output("llama_model_loader: nothing useful\nprint_info: x\n")
        with self.assertRaises(ValueError):
            engine.parse_caption_output("")

    def test_build_caption_command_targets_image(self):
        cmd = engine.build_caption_command("/bin/llama-mtmd-cli", "/models/x.gguf",
                                           "/models/mm.gguf", "/img/src.png",
                                           "Describe it", 128)
        joined = " ".join(cmd)
        self.assertIn("--image /img/src.png", joined)
        self.assertIn("--mmproj /models/mm.gguf", joined)
        self.assertIn("-m /models/x.gguf", joined)
        self.assertIn("-n 128", joined)
        self.assertIn("-ngl 99", joined)


class BonsaiVersionGuardTests(unittest.TestCase):
    """Bonsai-2 sous un llama.cpp trop ancien → refus explicite (jamais de légende fausse)."""

    def _run(self, captioner, version_tuple):
        with patch.object(registry, "CAPTIONER_MODELS", registry.CAPTIONER_MODELS), \
             patch.object(engine, "captioner_files", return_value=("/m.gguf", "/mm.gguf")), \
             patch.object(engine, "llama_available", return_value=("app", {"path": "/bin/llama-mtmd-cli",
                                                                        "version": "b11000"})), \
             patch.object(engine, "_llama_bin_version", return_value=version_tuple), \
             patch.object(engine, "build_caption_command", return_value=["/bin/true"]), \
             patch.object(engine, "parse_caption_output", return_value="dense caption here."):
            return engine.run_caption("/img.png", captioner, "prompt")

    def test_bonsai2_refused_on_old_llama(self):
        with self.assertRaises(RuntimeError) as ctx:
            self._run("bonsai2_2b", ("b", 11000, "b11000"))
        self.assertIn("Bonsai-2", str(ctx.exception))

    def test_bonsai2_allowed_on_new_llama(self):
        caption, cid, backend = self._run("bonsai2_2b", ("b", 12366, "b12366"))
        self.assertEqual(caption, "dense caption here.")

    def test_other_captioner_not_blocked_by_old_llama(self):
        caption, _, _ = self._run("qwen35_4b", ("b", 11000, "b11000"))
        self.assertEqual(caption, "dense caption here.")


FAKE_LLAMA_SERVER = r'''#!/usr/bin/env python3
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer

port = 0
for i, a in enumerate(sys.argv):
    if a == "--port":
        port = int(sys.argv[i + 1])

CAPTION = "<think>\nreason about the image\n</think>\nA dense red teapot on a wooden table, soft window light, shallow depth of field, warm muted palette, photographic."

class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send_json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            return self._send_json({"status": "ok"})
        return self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        if self.path == "/v1/chat/completions":
            n = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(n)
            return self._send_json({
                "choices": [{"message": {"role": "assistant", "content": CAPTION}}]})
        return self._send_json({"error": "not found"}, 404)

HTTPServer(("127.0.0.1", port), H).serve_forever()
'''


class LlamaServerBackendTests(unittest.TestCase):
    def test_llama_roots_covers_source_build_layout(self):
        import tempfile as _tf
        with _tf.TemporaryDirectory() as tmp:
            home = Path(tmp)
            build = home / "llama.cpp" / "build" / "bin" / "Release"
            build.mkdir(parents=True)
            roots = engine._llama_roots(home=home)
            self.assertTrue(any(str(r).endswith(os.path.join("llama.cpp", "build")) and str(r).startswith(str(home))
                                for r in roots))

    def test_host_detection_server_only_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            rel = home / "llama.cpp" / "build" / "bin" / "Release"
            rel.mkdir(parents=True)
            fake = rel / "llama-server"
            fake.write_text("#!/bin/sh\nexit 0\n")
            fake.chmod(0o755)
            with patch.object(engine, "_llama_roots", return_value=[home / "llama.cpp" / "build"]), \
                 patch.object(engine.shutil, "which", return_value=None), \
                 patch.object(engine, "_llama_bin_version", return_value=("b", 12366, "b12366")):
                host = engine.host_llama_cpp()
            self.assertIsNotNone(host)
            self.assertEqual(host["kind"], "server")
            self.assertEqual(host["backend_label"], "llama-server")
            self.assertTrue(host["ok"])
            self.assertTrue(host["path"].endswith("llama-server"))

    def test_host_detection_prefers_cli_over_server(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            rel = home / "llama.cpp" / "build" / "bin" / "Release"
            rel.mkdir(parents=True)
            for name in ("llama-server", "llama-mtmd-cli"):
                f = rel / name
                f.write_text("#!/bin/sh\nexit 0\n")
                f.chmod(0o755)
            with patch.object(engine, "_llama_roots", return_value=[home / "llama.cpp" / "build"]), \
                 patch.object(engine.shutil, "which", return_value=None), \
                 patch.object(engine, "_llama_bin_version", return_value=("b", 12366, "b12366")):
                host = engine.host_llama_cpp()
            self.assertEqual(host["kind"], "cli")
            self.assertTrue(host["path"].endswith("llama-mtmd-cli"))

    def test_host_detection_none_when_absent(self):
        with patch.object(engine, "_llama_roots", return_value=[]), \
             patch.object(engine.shutil, "which", return_value=None):
            self.assertIsNone(engine.host_llama_cpp())

    def test_run_caption_via_server_end_to_end(self):
        import tempfile as _tf
        with _tf.TemporaryDirectory() as tmp:
            server = Path(tmp) / "llama-server"
            server.write_text(FAKE_LLAMA_SERVER)
            server.chmod(0o755)
            img = Path(tmp) / "in.png"
            img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
            caption = engine.run_caption_via_server(str(server), "/m.gguf", "/mm.gguf",
                                                    str(img), "Describe it", 64)
            self.assertIn("red teapot", caption)
            self.assertNotIn("<think>", caption)
            self.assertNotIn("reason about", caption)

    def test_run_caption_dispatches_to_server_backend(self):
        with patch.object(engine, "captioner_files", return_value=("/m.gguf", "/mm.gguf")), \
             patch.object(engine, "llama_available",
                          return_value=("host", {"path": "/opt/llama/bin/llama-server",
                                                 "kind": "server", "version": "b12366"})), \
             patch.object(engine, "_llama_bin_version", return_value=("b", 12366, "b12366")), \
             patch.object(engine, "run_caption_via_server",
                          return_value="a dense caption via the http backend") as srv, \
             patch.object(engine, "subprocess") as sub:
            caption, cid, backend = engine.run_caption("/img.png", "qwen35_4b", "prompt")
        srv.assert_called_once()
        sub.run.assert_not_called()
        self.assertIn("llama-server", backend)


class LlamaAssetPickTests(unittest.TestCase):
    RELEASE_ASSETS = [
        {"name": "nightly-tag.txt"},
        {"name": "llama-b12366-bin-ubuntu-x64.tar.gz"},
        {"name": "llama-b12366-bin-win-cuda-12.4-x64.zip"},
        {"name": "llama-b12366-bin-win-cuda-13.5-x64.zip"},
        {"name": "cudart-llama-bin-win-cuda-12.4-x64.zip"},
        {"name": "cudart-llama-bin-win-cuda-13.5-x64.zip"},
        {"name": "llama-b12366-bin-win-cpu-x64.zip"},
        {"name": "llama-b12366-bin-macos-arm64.tar.gz"},
    ]

    def test_picks_self_contained_cudart_win_cuda(self):
        win = engine.pick_llama_windows_asset(self.RELEASE_ASSETS)
        self.assertEqual(win["name"], "cudart-llama-bin-win-cuda-13.5-x64.zip")

    def test_cuda_only_prefers_highest_version(self):
        assets = [a for a in self.RELEASE_ASSETS if not a["name"].startswith("cudart")]
        win = engine.pick_llama_windows_asset(assets)
        self.assertEqual(win["name"], "llama-b12366-bin-win-cuda-13.5-x64.zip")

    def test_cpu_fallback(self):
        assets = [a for a in self.RELEASE_ASSETS if "cuda" not in a["name"]]
        win = engine.pick_llama_windows_asset(assets)
        self.assertEqual(win["name"], "llama-b12366-bin-win-cpu-x64.zip")

    def test_v100_release_with_only_txt_asset_is_rejected(self):
        assets = [a for a in self.RELEASE_ASSETS if a["name"] == "nightly-tag.txt"]
        self.assertIsNone(engine.pick_llama_windows_asset(assets))

    def test_latest_release_info_prefers_binaries_over_showcase(self):
        releases = [
            {"tag_name": "v1.0.0", "draft": False, "prerelease": False,
             "assets": [{"name": "nightly-tag.txt"}]},
            {"tag_name": "b12366", "draft": False, "prerelease": True,
             "assets": [{"name": "llama-b12366-bin-win-cpu-x64.zip"}]},
        ]
        with patch.object(engine, "_gh_get", return_value=releases):
            tag, assets = engine.llama_latest_release_info(use_cache=False)
        self.assertEqual(tag, "b12366")
        self.assertEqual(assets[0]["name"], "llama-b12366-bin-win-cpu-x64.zip")

    def test_latest_release_info_prefers_stable_with_binaries(self):
        releases = [
            {"tag_name": "v1.2.0", "draft": False, "prerelease": False,
             "assets": [{"name": "llama-v1.2.0-bin-win-cpu-x64.zip"}]},
            {"tag_name": "b12366", "draft": False, "prerelease": True,
             "assets": [{"name": "llama-b12366-bin-win-cpu-x64.zip"}]},
        ]
        with patch.object(engine, "_gh_get", return_value=releases):
            tag, assets = engine.llama_latest_release_info(use_cache=False)
        self.assertEqual(tag, "v1.2.0")

    def test_latest_release_info_offline(self):
        with patch.object(engine, "_gh_get", side_effect=RuntimeError("offline")):
            tag, assets = engine.llama_latest_release_info(use_cache=False)
        self.assertIsNone(tag)
        self.assertEqual(assets, [])


class LlamaVersionGateTests(unittest.TestCase):
    def test_build_tags(self):
        ok, _ = engine._llama_version_status(("b", 11556, "b11556"))
        self.assertTrue(ok)
        ok, reason = engine._llama_version_status(("b", 11000, "b11000"))
        self.assertFalse(ok)
        self.assertIn("b11556", reason)

    def test_semver_tags(self):
        ok, _ = engine._llama_version_status(("semver", (0, 8, 0), "v0.8.0"))
        self.assertTrue(ok)
        ok, _ = engine._llama_version_status(("semver", (0, 7, 1), "v0.7.1"))
        self.assertFalse(ok)

    def test_unknown_is_accepted_with_warning(self):
        ok, reason = engine._llama_version_status(("unknown", None, "???"))
        self.assertTrue(ok)
        self.assertTrue(reason)


class CaptionRouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.output = self.root / "output"
        self.output.mkdir()
        self.patches = [
            patch.object(db, "DB_PATH", self.root / "history.db"),
            patch.object(config, "ROOT", self.root),
            patch.object(config, "OUTPUT_DIR", self.output),
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

    def _png(self, name="probe.png"):
        p = self.output / name
        p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 512)
        return p

    def test_upload_happy_path(self):
        self._png()
        payload = b"\x89PNG\r\n\x1a\n" + b"\x00" * 512
        with patch.object(app, "captioner_status", return_value={"ready": True, "deps": {}, "missing": []}), \
             patch.object(engine, "run_caption",
                          return_value=("A dense english caption.", "bonsai2_2b", "app")):
            r = self.client.post("/api/caption-upload",
                                 data={"image": (io.BytesIO(payload), "x.png"),
                                       "captioner": "bonsai2_2b"},
                                 content_type="multipart/form-data")
        self.assertEqual(r.status_code, 200)
        j = r.get_json()
        self.assertTrue(j["ok"])
        self.assertEqual(j["caption"], "A dense english caption.")

    def test_unknown_captioner_is_rejected(self):
        payload = b"\x89PNG\r\n\x1a\n" + b"\x00" * 512
        r = self.client.post("/api/caption-upload",
                             data={"image": (io.BytesIO(payload), "x.png"),
                                   "captioner": "not-a-model"},
                             content_type="multipart/form-data")
        self.assertEqual(r.status_code, 400)
        self.assertIn("inconnu", r.get_json()["error"])

    def test_caption_route_requires_existing_file(self):
        r = self.client.post("/api/caption", json={"path": "output/nope.png",
                                                   "captioner": "bonsai2_2b"})
        self.assertEqual(r.status_code, 404)

    def test_path_traversal_is_rejected(self):
        r = self.client.post("/api/caption", json={"path": "../secret.png",
                                                   "captioner": "bonsai2_2b"})
        self.assertIn(r.status_code, (400, 404))


if __name__ == "__main__":
    unittest.main()
