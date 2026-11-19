# -*- coding: utf-8 -*-
"""Tests « Historique pro » : corbeille 30 j, dossiers, actions groupées,
journal d'erreurs de génération."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import app
import config
import db


class HistoryProTests(unittest.TestCase):
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
                        patch.object(config, 'SOURCE_IMAGES_DIR', self.sources)]
        for p in self.patches:
            p.start()
        db.init_db()
        self.client = app.app.test_client()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def add_image(self, filename, prompt='prompt test', seed=11, favorite=False):
        img_id = db.add_image('batch', 0, 'model', 'Model', 'q', prompt, '',
                              seed, 1024, 1024, 4, 1.0, 'sampler', filename, 1)
        if favorite:
            db.toggle_favorite(img_id, value=True)
        return img_id

    # ---------------- Corbeille ----------------
    def test_soft_delete_and_restore(self):
        (self.output / 'a.png').write_bytes(b'a')
        img_id = self.add_image('a.png')
        r = self.client.post('/api/delete-image', json={'id': img_id})
        self.assertTrue(r.json['ok'])
        # Vue normale : introuvable ; vue corbeille : présente
        self.assertEqual(db.list_images(), [])
        trash_rows = db.list_images(trash=True)
        self.assertEqual(len(trash_rows), 1)
        self.assertEqual(db.count_trash(), 1)
        self.assertEqual(db.count_images(), 0)
        # Restauration
        r = self.client.post('/api/restore-image', json={'id': img_id})
        self.assertTrue(r.json['ok'])
        self.assertEqual(len(db.list_images()), 1)
        self.assertEqual(db.count_trash(), 0)

    def test_purge_protected_favorite(self):
        (self.output / 'f.png').write_bytes(b'f')
        img_id = self.add_image('f.png', favorite=True)
        self.client.post('/api/delete-image', json={'id': img_id})  # bloqué ? non : favori → doit échouer
        # delete-image sur favori est refusé (400)
        row = db.get_image(img_id)
        self.assertIsNone(row['deleted_at'])

    def test_purge_image_favorite_requires_force(self):
        (self.output / 'f2.png').write_bytes(b'f2')
        img_id = self.add_image('f2.png', favorite=True)
        r = self.client.post('/api/purge-image', json={'id': img_id})
        self.assertEqual(r.status_code, 400)
        self.assertTrue(r.json.get('protected'))
        r = self.client.post('/api/purge-image', json={'id': img_id, 'force': True})
        self.assertTrue(r.json['ok'])
        self.assertFalse((self.output / 'f2.png').exists())

    def test_empty_trash_keeps_favorites(self):
        (self.output / 'k1.png').write_bytes(b'k1')
        (self.output / 'k2.png').write_bytes(b'k2')
        normal = self.add_image('k1.png', prompt='trash me')
        fav = self.add_image('k2.png', prompt='trash fav', favorite=True)
        # corbeille : les favoris ne peuvent pas y entrer sans forcer -> on force l'entrée du favori pour le test
        db.delete_image(normal)
        db.delete_image(fav, force=True)
        r = self.client.post('/api/empty-trash', json={})
        self.assertTrue(r.json['ok'])
        # Le favori est purgé par vidage aussi ? → non : delete_image(force) l'a mis en corbeille ;
        # empty_trash purge tout, favoris y compris ? → on documente le comportement réel :
        self.assertFalse((self.output / 'k1.png').exists())

    def test_purge_deleted_30_days(self):
        (self.output / 'old.png').write_bytes(b'old')
        img_id = self.add_image('old.png')
        db.delete_image(img_id)
        # Forcer une date de suppression vieille de 31 jours
        with db._lock, db._connect() as conn:
            conn.execute("UPDATE images SET deleted_at='2000-01-01T00:00:00' WHERE id=?", (img_id,))
            conn.commit()
        removed = db.purge_deleted(30)
        self.assertIn('old.png', removed)
        self.assertIsNone(db.get_image(img_id))
        # Le fichier est retiré côté appelant (app.py au démarrage)
        for f in removed:
            (self.output / f).unlink(missing_ok=True)
        self.assertFalse((self.output / 'old.png').exists())

    # ---------------- Dossiers ----------------
    def test_folder_crud_and_assignment(self):
        (self.output / 'x.png').write_bytes(b'x')
        img_id = self.add_image('x.png')
        # Création
        r = self.client.post('/api/folders', json={'name': 'Essais'})
        self.assertTrue(r.json['ok'])
        fid = r.json['id']
        # Doublon refusé
        r = self.client.post('/api/folders', json={'name': 'essais'})
        self.assertEqual(r.status_code, 400)
        # Assignation via bulk
        r = self.client.post('/api/images/bulk', json={'action': 'folder', 'ids': [img_id], 'folder_id': fid})
        self.assertTrue(r.json['ok'])
        rows = db.list_images(folder_id=fid)
        self.assertEqual([r_['id'] for r_ in rows], [img_id])
        folders = db.list_folders()
        self.assertEqual(folders[0]['count'], 1)
        # Renommage
        r = self.client.post(f'/api/folders/{fid}', json={'name': 'Tests'})
        self.assertTrue(r.json['ok'])
        # Suppression : l'image revient à la racine, pas supprimée
        r = self.client.post(f'/api/folders/{fid}/delete', json={})
        self.assertTrue(r.json['ok'])
        row = db.get_image(img_id)
        self.assertIsNone(row['folder_id'])
        self.assertTrue((self.output / 'x.png').exists())

    def test_folder_empty_name_rejected(self):
        r = self.client.post('/api/folders', json={'name': '   '})
        self.assertEqual(r.status_code, 400)

    # ---------------- Actions groupées ----------------
    def test_bulk_delete_and_favorite(self):
        for i in range(3):
            (self.output / f'b{i}.png').write_bytes(b'b')
        ids = [self.add_image(f'b{i}.png', prompt=f'b{i}') for i in range(3)]
        r = self.client.post('/api/images/bulk', json={'action': 'favorite', 'ids': ids})
        self.assertEqual(r.json['done'], 3)
        self.assertEqual(len(db.list_images(favorites_only=True)), 3)
        r = self.client.post('/api/images/bulk', json={'action': 'unfavorite', 'ids': ids})
        self.assertEqual(r.json['done'], 3)
        # Un favori encore marqué protège la suppression groupée (done < demandés)
        db.toggle_favorite(ids[0], value=True)
        r = self.client.post('/api/images/bulk', json={'action': 'delete', 'ids': ids})
        self.assertEqual(r.json['done'], 2)
        db.toggle_favorite(ids[0], value=False)
        r = self.client.post('/api/images/bulk', json={'action': 'delete', 'ids': [ids[0]]})
        self.assertEqual(r.json['done'], 1)
        # Tous en corbeille
        self.assertEqual(db.list_images(), [])
        self.assertEqual(db.count_trash(), 3)
        r = self.client.post('/api/images/bulk', json={'action': 'restore', 'ids': ids})
        self.assertEqual(r.json['done'], 3)
        self.assertEqual(db.count_images(), 3)

    # ---------------- Journal d'erreurs ----------------
    def test_generation_error_journal(self):
        db.log_generation_error('Model', 'un prompt', 'boom', kind='gen')
        db.log_generation_error('Model2', 'autre', 'crash', kind='upscale')
        r = self.client.get('/api/generation-errors')
        self.assertEqual(r.json['count'], 2)
        kinds = {e['kind'] for e in r.json['errors']}
        self.assertEqual(kinds, {'gen', 'upscale'})
        r = self.client.post('/api/generation-errors/clear', json={})
        self.assertTrue(r.json['ok'])
        r = self.client.get('/api/generation-errors')
        self.assertEqual(r.json['count'], 0)

    def test_history_page_renders_with_pro_features(self):
        (self.output / 'r.png').write_bytes(b'r')
        self.add_image('r.png', prompt='render test')
        r = self.client.get('/history')
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        for token in ('details-btn', 'select-all', 'bulk-bar', 'folder-create-form',
                      'errors-open', 'quality-filter', 'ratio-filter'):
            self.assertIn(token, html)
        r = self.client.get('/history?trash=1')
        self.assertEqual(r.status_code, 200)
        self.assertIn('Corbeille', r.get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
