"""Tests de la route /api/pulid-extract (extraction d'empreinte PuLID)."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import app
import config


class PulidExtractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.sources = self.root / 'source_images'
        self.portraits = self.root / 'portraits'
        self.sources.mkdir()
        self.portraits.mkdir()
        self.patches = [patch.object(config, 'ROOT', self.root),
                        patch.object(config, 'SOURCE_IMAGES_DIR', self.sources),
                        patch.object(config, 'PORTRAITS_DIR', self.portraits)]
        for p in self.patches:
            p.start()
        self.client = app.app.test_client()
        (self.sources / 'face.png').write_bytes(b'\x89PNG\r\n\x1a\nfakejpegdata')

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def test_missing_weights_returns_400_with_french_message(self):
        with patch('app.pulid_weights_path') as w:
            w.return_value = self.root / 'nope.safetensors'  # inexistant
            resp = self.client.post('/api/pulid-extract',
                                    json={'portrait': 'face.png', 'name': 'moi'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('PuLID', resp.json['error'])

    def test_missing_portrait_returns_404(self):
        with patch('app.pulid_weights_path') as w:
            w.return_value = self.root / 'weights.safetensors'
            (self.root / 'weights.safetensors').write_bytes(b'x')
            resp = self.client.post('/api/pulid-extract',
                                    json={'portrait': 'absente.png', 'name': 'moi'})
        self.assertEqual(resp.status_code, 404)

    def test_success_writes_embedding_and_copies_thumbnail(self):
        weights = self.root / 'pulid_flux_v0.9.1.safetensors'
        weights.write_bytes(b'x' * 1024)

        class FakeProc:
            returncode = 0
            stdout = ''
            stderr = ''

        def fake_run(cmd, **kwargs):
            # L'extracteur écrit le fichier .pulidembd à côté
            out = Path(cmd[cmd.index('--out') + 1])
            out.write_bytes(b'PULID' + b'\x00' * 60 * 1024)  # > 50 Ko
            return FakeProc()

        with patch('app.pulid_weights_path', return_value=weights), \
             patch('app.subprocess.run', side_effect=fake_run):
            resp = self.client.post('/api/pulid-extract',
                                    json={'portrait': 'face.png', 'name': 'Moi! 2026'})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json['ok'])
        emb = self.portraits / resp.json['embedding']
        self.assertTrue(emb.exists())
        self.assertGreater(emb.stat().st_size, 50 * 1024)
        # Le nom est assaini (pas d'espace ni de ponctuation)
        self.assertRegex(resp.json['embedding'], r'^[A-Za-z0-9_-]+\.pulidembd$')
        # La photo est copiée à côté pour la vignette de la galerie
        self.assertEqual(resp.json['preview'], emb.with_suffix('.png').name)
        self.assertTrue((self.portraits / resp.json['preview']).exists())

    def test_extractor_failure_returns_500_with_details(self):
        weights = self.root / 'pulid_flux_v0.9.1.safetensors'
        weights.write_bytes(b'x')

        class FakeProc:
            returncode = 1
            stdout = ''
            stderr = 'Traceback...\nRuntimeError: no face detected\n'

        with patch('app.pulid_weights_path', return_value=weights), \
             patch('app.subprocess.run', return_value=FakeProc()):
            resp = self.client.post('/api/pulid-extract',
                                    json={'portrait': 'face.png', 'name': 'moi'})
        self.assertEqual(resp.status_code, 500)
        self.assertIn('no face detected', resp.json['error'])


if __name__ == '__main__':
    unittest.main()
