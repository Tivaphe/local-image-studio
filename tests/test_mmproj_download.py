"""Régression — téléchargement mmproj (/api/download-mmproj).

Rapporte par l'utilisateur : « ✗ app.json.response() takes either args or kwargs,
not both » lors du téléchargement du mmproj (Flask 3 : jsonify(dict, status=500)
lève un TypeError). Causé par une dépendance présente sur disque mais absente du
manifeste — la route répondait alors « fichier non trouvé » via un jsonify invalide.
"""

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
import registry


class _PatchedAppTestCase(unittest.TestCase):
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

    def _fake_dep_file(self):
        f = self.root / "llm" / "mmproj-Qwen3VL-4B-Instruct-F16.gguf"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"fake-weights-bytes")
        return f


class MmprojDownloadRouteTests(_PatchedAppTestCase):
    def test_ok_when_dep_resolves(self):
        target = self._fake_dep_file()
        with patch("engine.ensure_dep") as m_ensure, \
             patch("registry.load_manifest", return_value={}), \
             patch("registry._dep_path", return_value=str(target)):
            r = self.client.post("/api/download-mmproj", json={"model_id": "fibo2-dev"})
        self.assertEqual(r.status_code, 200)
        j = r.get_json()
        self.assertTrue(j["ok"])
        self.assertEqual(j["dep"], "mmproj_qwen3vl_4b")
        m_ensure.assert_called_once()

    def test_missing_file_returns_clear_french_error_not_typeerror(self):
        with patch("engine.ensure_dep"), \
             patch("registry.load_manifest", return_value={}), \
             patch("registry._dep_path", return_value=None):
            r = self.client.post("/api/download-mmproj", json={"model_id": "fibo2-dev"})
        self.assertEqual(r.status_code, 500)
        err = r.get_json()["error"].lower()
        self.assertIn("introuvable", err)
        self.assertNotIn("jsonify", err)
        self.assertNotIn("app.json", err)

    def test_download_failure_returns_friendly_json_error(self):
        with patch("engine.ensure_dep", side_effect=RuntimeError("401 Client Error: gated repo")):
            r = self.client.post("/api/download-mmproj", json={"model_id": "qwen-image-2.1"})
        self.assertEqual(r.status_code, 500)
        err = r.get_json()["error"].lower()
        self.assertIn("token", err)  # friendly_download_error → message actionnable

    def test_unreachable_module_style_exception_stays_json(self):
        with patch("engine.ensure_dep", side_effect=RuntimeError("No space left on device")):
            r = self.client.post("/api/download-mmproj", json={"model_id": "fibo2-dev"})
        self.assertEqual(r.status_code, 500)
        j = r.get_json()
        self.assertFalse(j["ok"])
        self.assertIn("disque", j["error"].lower())


class EnsureDepBackfillTests(_PatchedAppTestCase):
    def test_manifest_backfilled_from_disk_then_no_redownload(self):
        target = self._fake_dep_file()
        fake_dep = {"type": "exact", "repo": "test/repo", "filename": target.name,
                    "dest": target, "size_gb": 0.1}
        manifest_path = self.root / "manifest.json"
        manifest_path.write_text("{}", encoding="utf-8")
        with patch.object(registry, "MANIFEST_PATH", manifest_path), \
             patch.object(engine, "_dep_path", return_value=str(target)), \
             patch.dict(engine.DEPS, {"mmproj_test_dep": fake_dep}):
            engine.ensure_dep("mmproj_test_dep", token=None)
        saved = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["mmproj_test_dep"]["path"], str(target))
        self.assertTrue(saved["mmproj_test_dep"].get("found_on_disk"))
        # 2e passage (process simulé) : manifeste réparé → aucun réseau du tout
        with patch.object(registry, "MANIFEST_PATH", manifest_path),              patch.dict(engine.DEPS, {"mmproj_test_dep": fake_dep}),              patch("engine._hf_download_file",
                   side_effect=AssertionError("ne doit pas retélécharger")):
            engine.ensure_dep("mmproj_test_dep", token=None)
        # le manifeste reste cohérent après le 2e passage
        saved2 = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(saved2["mmproj_test_dep"]["path"], str(target))


if __name__ == "__main__":
    unittest.main()
