# -*- coding: utf-8 -*-
"""Base de donnees SQLite pour l'historique et les statistiques."""
import json
import sqlite3
import threading
from datetime import datetime

from config import DB_PATH

_lock = threading.Lock()


def _connect():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _lock, _connect() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS images (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            created     TEXT,
            batch_id    TEXT,
            idx         INTEGER,
            model       TEXT,
            model_name  TEXT,
            quant       TEXT,
            prompt      TEXT,
            negative    TEXT,
            seed        INTEGER,
            width       INTEGER,
            height      INTEGER,
            steps       INTEGER,
            cfg         REAL,
            sampler     TEXT,
            filename    TEXT,
            batch_size  INTEGER,
            gen_time    REAL DEFAULT 0,
            source_images TEXT
        )
        """)
        # migration : ajouter gen_time si absent (DB existante)
        try:
            conn.execute("SELECT gen_time FROM images LIMIT 1")
        except Exception:
            conn.execute("ALTER TABLE images ADD COLUMN gen_time REAL DEFAULT 0")
        # migration : images sources (edition / img2img) pour « Réutiliser »
        try:
            conn.execute("SELECT source_images FROM images LIMIT 1")
        except Exception:
            conn.execute("ALTER TABLE images ADD COLUMN source_images TEXT")
        conn.commit()


def add_image(batch_id, idx, model_id, model_name, quant, prompt, negative,
              seed, width, height, steps, cfg, sampler, filename, batch_size,
              gen_time=0, source_images=None):
    """`source_images` : liste de chemins relatifs (canvas en premier) ou None."""
    src = None
    if source_images:
        src = json.dumps(list(source_images), ensure_ascii=False)
    with _lock, _connect() as conn:
        conn.execute("""
            INSERT INTO images (created, batch_id, idx, model, model_name, quant,
                                prompt, negative, seed, width, height, steps, cfg,
                                sampler, filename, batch_size, gen_time, source_images)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (datetime.now().isoformat(timespec="seconds"), batch_id, idx,
              model_id, model_name, quant, prompt, negative, seed, width,
              height, steps, cfg, sampler, filename, batch_size, gen_time, src))
        conn.commit()


def _decode_row(row):
    """Ajoute `source_images_list` (liste de chemins relatifs) à une ligne brute."""
    raw = row.get("source_images")
    try:
        row["source_images_list"] = json.loads(raw) if raw else []
    except Exception:
        row["source_images_list"] = []
    return row


def list_images(limit=200, offset=0, model_id=None):
    with _lock, _connect() as conn:
        if model_id:
            cur = conn.execute(
                "SELECT * FROM images WHERE model=? ORDER BY id DESC LIMIT ? OFFSET ?",
                (model_id, limit, offset))
            rows = cur.fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM images ORDER BY id DESC LIMIT ? OFFSET ?",
                (limit, offset)).fetchall()
        return [_decode_row(dict(r)) for r in rows]


def get_image(img_id):
    with _lock, _connect() as conn:
        cur = conn.execute("SELECT * FROM images WHERE id=?", (img_id,))
        r = cur.fetchone()
        return _decode_row(dict(r)) if r else None


def delete_image(img_id):
    with _lock, _connect() as conn:
        cur = conn.execute("SELECT filename FROM images WHERE id=?", (img_id,))
        r = cur.fetchone()
        conn.execute("DELETE FROM images WHERE id=?", (img_id,))
        conn.commit()
        return r["filename"] if r else None


def count_images():
    with _lock, _connect() as conn:
        cur = conn.execute("SELECT COUNT(*) AS c FROM images")
        return cur.fetchone()["c"]


# --------------------------------------------------------------------------- #
#  Statistiques
# --------------------------------------------------------------------------- #
def get_stats():
    """Retourne un dict avec toutes les statistiques agregrees."""
    with _lock, _connect() as conn:
        total = conn.execute("SELECT COUNT(*) AS c FROM images").fetchone()["c"]

        # Stats par modele
        per_model = conn.execute("""
            SELECT model, model_name,
                   COUNT(*) as img_count,
                   COUNT(DISTINCT batch_id) as gen_count,
                   ROUND(AVG(gen_time), 1) as avg_time,
                   ROUND(MIN(gen_time), 1) as min_time,
                   ROUND(MAX(gen_time), 1) as max_time,
                   ROUND(SUM(gen_time), 1) as total_time
            FROM images
            GROUP BY model
            ORDER BY img_count DESC
        """).fetchall()

        # Temps total cumule
        total_time_row = conn.execute(
            "SELECT ROUND(SUM(gen_time),1) as t FROM images"
        ).fetchone()
        total_time = total_time_row["t"] or 0

        # Avg global
        avg_row = conn.execute(
            "SELECT ROUND(AVG(gen_time),1) as a FROM images WHERE gen_time > 0"
        ).fetchone()
        avg_time = avg_row["a"] or 0

        # Resolution la plus utilisee
        res_row = conn.execute("""
            SELECT width || 'x' || height as res, COUNT(*) as c
            FROM images GROUP BY res ORDER BY c DESC LIMIT 1
        """).fetchone()
        fav_res = res_row["res"] if res_row else "-"

        # 7 dernieres generations (pour un mini graphique)
        recent = conn.execute("""
            SELECT model_name, gen_time, created, model
            FROM images WHERE gen_time > 0
            ORDER BY id DESC LIMIT 20
        """).fetchall()

        return {
            "total_images": total,
            "total_generations": len(set(r["batch_id"] for r in
                  conn.execute("SELECT batch_id FROM images").fetchall())),
            "total_time_sec": total_time,
            "avg_time_sec": avg_time,
            "per_model": [dict(r) for r in per_model],
            "fav_resolution": fav_res,
            "recent": [dict(r) for r in recent],
        }
