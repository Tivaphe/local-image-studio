import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app
import config
import db
import engine


class ImagePersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.output = self.root / 'output'
        self.sources = self.root / 'source_images'
        self.output.mkdir()
        self.sources.mkdir()
        self.patches = [patch.object(db, 'DB_PATH', self.root / 'history.db'),
                        patch.object(config, 'ROOT', self.root),
                        patch.object(config, 'OUTPUT_DIR', self.output),
                        patch.object(config, 'SOURCE_IMAGES_DIR', self.sources),
                        patch.object(engine, 'ROOT', self.root),
                        patch.object(engine, 'OUTPUT_DIR', self.output)]
        for p in self.patches:
            p.start()
        db.init_db()
        self.client = app.app.test_client()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def add_image(self, filename, sources=None):
        return db.add_image('batch', 0, 'model', 'Model', 'q', 'prompt', '',
                            1, 64, 64, 1, 1, 'sampler', filename, 1,
                            source_images=sources)

    def test_shared_legacy_output_not_removed_until_last_entry(self):
        path = self.output / 'shared.png'
        path.write_bytes(b'image')
        a = self.add_image(path.name)
        b = self.add_image(path.name)
        self.client.post('/api/delete-image', json={'id': a})
        self.assertTrue(path.exists())
        self.client.post('/api/delete-image', json={'id': b})
        self.assertFalse(path.exists())

    def test_source_used_by_history_is_not_deleted(self):
        source = self.sources / 'canvas.png'
        source.write_bytes(b'image')
        rel = 'source_images/canvas.png'
        self.add_image('result.png', [rel])
        response = self.client.post('/api/delete-source-image', json={'filename': rel})
        self.assertTrue(response.json['retained'])
        self.assertTrue(source.exists())
        unused = self.sources / 'unused.png'
        unused.write_bytes(b'image')
        self.client.post('/api/delete-source-image', json={'filename': 'source_images/unused.png'})
        self.assertFalse(unused.exists())

    def test_generated_image_can_be_uploaded_as_independent_source(self):
        generated = self.output / 'result.png'
        generated.write_bytes(b'generated image')
        image_id = self.add_image(generated.name)
        response = self.client.post('/api/upload-source-image',
                                    data={'images': (io.BytesIO(generated.read_bytes()), generated.name)},
                                    content_type='multipart/form-data')
        self.assertTrue(response.json['ok'])
        source = self.root / response.json['filename']
        self.assertEqual(source.read_bytes(), generated.read_bytes())
        self.client.post('/api/delete-image', json={'id': image_id})
        self.assertFalse(generated.exists())
        self.assertTrue(source.exists())

    def test_generations_have_distinct_outputs_and_ignore_unrelated_files(self):
        unrelated = self.output / 'unrelated.png'
        unrelated.write_bytes(b'other')
        model = {'name': 'Model', 'deps': [], 'defaults': {'sampler': 'euler'}}
        params = dict(model_id='test', quant='q', prompt='same prompt', negative='',
                      width=64, height=64, steps=1, cfg=1, seed=7, batch=1)
        def command(*args, **kwargs):
            return ['fake', args[10]]  # output template
        class Process:
            def __init__(self, cmd, **kwargs):
                Path(cmd[1].replace('%03d', '000')).write_bytes(b'new image')
                self.stdout = iter([])
            def wait(self):
                return 0
        manager = engine.TaskManager()
        with patch('registry.MODELS', {'test': model}), \
             patch.object(engine, 'find_sd_cli', return_value='fake'), \
             patch.object(engine, '_model_present', return_value=True), \
             patch.object(engine, 'load_manifest', return_value={}), \
             patch.object(engine, 'check_images_input', return_value=([], None, None)), \
             patch.object(engine, 'build_command', side_effect=command), \
             patch.object(engine.subprocess, 'Popen', Process):
            manager._run_generate(params)
            first = manager.snapshot()['result']['images']
            manager._run_generate(params)
            second = manager.snapshot()['result']['images']
        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 1)
        self.assertNotEqual(first[0]['filename'], second[0]['filename'])
        self.assertTrue((self.output / first[0]['filename']).exists())
        self.assertTrue(unrelated.exists())
        self.assertEqual({r['filename'] for r in db.list_images()},
                         {first[0]['filename'], second[0]['filename']})
        self.assertEqual(db.get_image(first[0]['id'])['filename'], first[0]['filename'])

    def test_outpaint_api_validation_and_auto_prompt(self):
        canvas = self.sources / 'expanded_canvas.png'
        canvas.write_bytes(b'image')
        rel = 'source_images/expanded_canvas.png'

        # Modèle ne supportant pas l'outpainting -> 400
        resp_bad = self.client.post('/api/generate', json={
            'model_id': 'flux-schnell',
            'prompt': 'extend',
            'outpaint': {'enabled': True, 'directions': ['left', 'right']},
        })
        self.assertEqual(resp_bad.status_code, 400)

        # Modèle compatible avec prompt vide et auto_prompt actif -> 200 + prompt auto-adapté
        with patch.object(engine.tasks, 'start_generate') as start_mock:
            resp_ok = self.client.post('/api/generate', json={
                'model_id': 'qwen-image-2.1',
                'prompt': '',
                'width': 1280,
                'height': 864,
                'input_mode': 'ref',
                'ref_images': [rel],
                'outpaint': {'enabled': True, 'directions': ['left', 'right'], 'auto_prompt': True},
            })
            self.assertEqual(resp_ok.status_code, 200)
            self.assertTrue(resp_ok.json['ok'])
            called_params = start_mock.call_args[0][0]
            self.assertTrue(called_params['outpaint'])
            self.assertIn('<image1>', called_params['prompt'])
            self.assertEqual(called_params['width'], 1280)
            self.assertEqual(called_params['height'], 864)

    def test_use_output_as_source_creates_independent_copy(self):
        generated = self.output / 'gen_001.png'
        generated.write_bytes(b'png-bytes-123')
        image_id = self.add_image(generated.name)

        resp = self.client.post('/api/use-output-as-source', json={'id': image_id})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json['ok'])
        rel_src = resp.json['filename']
        copied_file = self.root / rel_src
        self.assertTrue(copied_file.exists())
        self.assertEqual(copied_file.read_bytes(), b'png-bytes-123')

        # Supprimer l'image de l'historique ne supprime pas la copie dans source_images/
        self.client.post('/api/delete-image', json={'id': image_id})
        self.assertFalse(generated.exists())
        self.assertTrue(copied_file.exists())

        # Tentative de traversée de chemin -> 400
        bad_resp = self.client.post('/api/use-output-as-source', json={'filename': '../app.py'})
        self.assertEqual(bad_resp.status_code, 400)


if __name__ == '__main__':
    unittest.main()
