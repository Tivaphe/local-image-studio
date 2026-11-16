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
        # migration : favoris ⭐ (protection contre suppression accidentelle)
        try:
            conn.execute("SELECT favorite FROM images LIMIT 1")
        except Exception:
            conn.execute("ALTER TABLE images ADD COLUMN favorite INTEGER DEFAULT 0")
        # migration : corbeille (suppression douce) + dossiers de tri
        try:
            conn.execute("SELECT deleted_at FROM images LIMIT 1")
        except Exception:
            conn.execute("ALTER TABLE images ADD COLUMN deleted_at TEXT")
        try:
            conn.execute("SELECT folder_id FROM images LIMIT 1")
        except Exception:
            conn.execute("ALTER TABLE images ADD COLUMN folder_id INTEGER")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS folders (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            created     TEXT
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS generation_errors (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            created     TEXT,
            model_name  TEXT,
            prompt      TEXT,
            error       TEXT,
            kind        TEXT
        )
        """)
        # styles personnalisés (page Gestion des styles)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS user_styles (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            prompt      TEXT NOT NULL,
            applies_to  TEXT NOT NULL DEFAULT 'both',
            models      TEXT NOT NULL DEFAULT 'all',
            created     TEXT,
            updated     TEXT
        )
        """)
        conn.commit()


def add_image(batch_id, idx, model_id, model_name, quant, prompt, negative,
              seed, width, height, steps, cfg, sampler, filename, batch_size,
              gen_time=0, source_images=None):
    """`source_images` : liste de chemins relatifs (canvas en premier) ou None."""
    src = None
    if source_images:
        src = json.dumps(list(source_images), ensure_ascii=False)
    with _lock, _connect() as conn:
        cur = conn.execute("""
            INSERT INTO images (created, batch_id, idx, model, model_name, quant,
                                prompt, negative, seed, width, height, steps, cfg,
                                sampler, filename, batch_size, gen_time, source_images)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (datetime.now().isoformat(timespec="seconds"), batch_id, idx,
              model_id, model_name, quant, prompt, negative, seed, width,
              height, steps, cfg, sampler, filename, batch_size, gen_time, src))
        conn.commit()
        return cur.lastrowid


def _decode_row(row):
    """Ajoute `source_images_list` (liste de chemins relatifs) et normalise `favorite`."""
    raw = row.get("source_images")
    try:
        row["source_images_list"] = json.loads(raw) if raw else []
    except Exception:
        row["source_images_list"] = []
    row["favorite"] = bool(row.get("favorite", 0))
    return row


def list_images(limit=200, offset=0, model_id=None, search_query=None, favorites_only=False,
                trash=False, folder_id=None):
    clauses = []
    params = []
    clauses.append("deleted_at IS NOT NULL" if trash else "deleted_at IS NULL")
    if model_id:
        clauses.append("model = ?")
        params.append(model_id)
    if folder_id is not None:
        clauses.append("folder_id = ?")
        params.append(int(folder_id))
    if favorites_only:
        clauses.append("COALESCE(favorite, 0) = 1")
    if search_query and str(search_query).strip():
        q_like = f"%{str(search_query).strip()}%"
        clauses.append("(prompt LIKE ? OR model_name LIKE ? OR CAST(seed AS TEXT) LIKE ? OR quant LIKE ?)")
        params.extend([q_like, q_like, q_like, q_like])
    where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"SELECT * FROM images {where_sql} ORDER BY id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    with _lock, _connect() as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
        return [_decode_row(dict(r)) for r in rows]


def get_image(img_id):
    with _lock, _connect() as conn:
        cur = conn.execute("SELECT * FROM images WHERE id=?", (img_id,))
        r = cur.fetchone()
        return _decode_row(dict(r)) if r else None


def toggle_favorite(img_id, value=None):
    """Bascule ou force l'état favori (⭐) d'une image. Renvoie le nouvel état booléen ou None."""
    with _lock, _connect() as conn:
        cur = conn.execute("SELECT favorite FROM images WHERE id=?", (img_id,))
        r = cur.fetchone()
        if not r:
            return None
        new_val = (1 if bool(value) else 0) if value is not None else (0 if r["favorite"] else 1)
        conn.execute("UPDATE images SET favorite=? WHERE id=?", (new_val, img_id))
        conn.commit()
        return bool(new_val)


def _favorite_guard(row, force):
    if row["favorite"] and not force:
        raise PermissionError("Cette image est marquée en Favori ⭐. Retirez-la des favoris avant de la supprimer.")


def _orphaned_filename(conn, filename):
    # Les anciennes générations peuvent partager un nom de fichier (partagé y compris avec la poubelle).
    row = conn.execute("SELECT 1 FROM images WHERE filename=? LIMIT 1", (filename,)).fetchone()
    return None if row else filename


# --------------------------------------------------------------------------- #
#  Dossiers (tri manuel de l'historique)
# --------------------------------------------------------------------------- #
def list_folders():
    with _lock, _connect() as conn:
        rows = conn.execute("""
            SELECT f.id, f.name,
                   COUNT(i.id) AS count
            FROM folders f
            LEFT JOIN images i ON i.folder_id = f.id AND i.deleted_at IS NULL
            GROUP BY f.id, f.name
            ORDER BY f.name COLLATE NOCASE
        """).fetchall()
        return [{"id": r["id"], "name": r["name"], "count": r["count"]} for r in rows]


def _folder_name_valid(name):
    name = (name or "").strip()
    if not name or len(name) > 60:
        raise ValueError("Le nom du dossier doit faire entre 1 et 60 caractères.")
    return name


def create_folder(name):
    name = _folder_name_valid(name)
    with _lock, _connect() as conn:
        row = conn.execute("SELECT id FROM folders WHERE lower(name) = lower(?)", (name,)).fetchone()
        if row:
            raise ValueError("Un dossier porte déjà ce nom.")
        cur = conn.execute("INSERT INTO folders (name, created) VALUES (?,?)",
                           (name, datetime.now().isoformat(timespec="seconds")))
        conn.commit()
        return cur.lastrowid


def rename_folder(folder_id, name):
    name = _folder_name_valid(name)
    with _lock, _connect() as conn:
        row = conn.execute("SELECT 1 FROM folders WHERE lower(name) = lower(?) AND id != ?",
                           (name, folder_id)).fetchone()
        if row:
            raise ValueError("Un dossier porte déjà ce nom.")
        cur = conn.execute("UPDATE folders SET name=? WHERE id=?", (name, folder_id))
        conn.commit()
        return cur.rowcount > 0


def delete_folder(folder_id):
    """Supprime le dossier ; ses images retournent à la racine (non supprimées)."""
    with _lock, _connect() as conn:
        conn.execute("UPDATE images SET folder_id=NULL WHERE folder_id=?", (folder_id,))
        cur = conn.execute("DELETE FROM folders WHERE id=?", (folder_id,))
        conn.commit()
        return cur.rowcount > 0


def set_images_folder(img_ids, folder_id):
    """Assigne un lot d'images à un dossier (folder_id=None → racine)."""
    ids = [int(i) for i in (img_ids or [])]
    if not ids:
        return 0
    with _lock, _connect() as conn:
        if folder_id is not None:
            row = conn.execute("SELECT 1 FROM folders WHERE id=?", (folder_id,)).fetchone()
            if not row:
                raise ValueError("Dossier introuvable.")
        marks = ",".join("?" * len(ids))
        cur = conn.execute(
            f"UPDATE images SET folder_id=? WHERE id IN ({marks})",
            (int(folder_id) if folder_id is not None else None, *ids))
        conn.commit()
        return cur.rowcount


def delete_image(img_id, force=False):
    """Suppression douce (poubelle) : le fichier reste sur disque, restaurable."""
    with _lock, _connect() as conn:
        cur = conn.execute("SELECT filename, COALESCE(favorite, 0) AS favorite, deleted_at FROM images WHERE id=?",
                           (img_id,))
        r = cur.fetchone()
        if not r:
            return None
        _favorite_guard(r, force)
        if not r["deleted_at"]:
            conn.execute("UPDATE images SET deleted_at=? WHERE id=?",
                         (datetime.now().isoformat(timespec="seconds"), img_id))
            conn.commit()
        return None  # suppression douce : le fichier n'est pas retiré du disque


def restore_image(img_id):
    with _lock, _connect() as conn:
        cur = conn.execute("UPDATE images SET deleted_at=NULL WHERE id=? AND deleted_at IS NOT NULL",
                           (img_id,))
        conn.commit()
        return cur.rowcount > 0


def purge_image(img_id, force=False):
    """Suppression définitive (poubelle) : retourne le nom de fichier orphelin, sinon None."""
    with _lock, _connect() as conn:
        cur = conn.execute("SELECT filename, COALESCE(favorite, 0) AS favorite FROM images WHERE id=?", (img_id,))
        r = cur.fetchone()
        if not r:
            return None
        _favorite_guard(r, force)
        conn.execute("DELETE FROM images WHERE id=?", (img_id,))
        conn.commit()
        return _orphaned_filename(conn, r["filename"])


def empty_trash():
    """Purge toute la poubelle. Retourne la liste des fichiers devenus orphelins."""
    with _lock, _connect() as conn:
        rows = conn.execute("SELECT id, filename FROM images WHERE deleted_at IS NOT NULL").fetchall()
        filenames = [r["filename"] for r in rows]
        conn.execute("DELETE FROM images WHERE deleted_at IS NOT NULL")
        conn.commit()
        return [f for f in dict.fromkeys(filenames) if _orphaned_filename(conn, f)]


def purge_deleted(days=30):
    """Purge automatique de la poubelle (entrées plus vieilles que `days` jours)."""
    from datetime import timedelta
    cutoff = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    with _lock, _connect() as conn:
        rows = conn.execute("SELECT filename FROM images WHERE deleted_at IS NOT NULL AND deleted_at < ?",
                            (cutoff,)).fetchall()
        conn.execute("DELETE FROM images WHERE deleted_at IS NOT NULL AND deleted_at < ?", (cutoff,))
        conn.execute("DELETE FROM generation_errors WHERE created < ?", (cutoff,))
        conn.commit()
        return [f for f in dict.fromkeys(r["filename"] for r in rows) if _orphaned_filename(conn, f)]


def count_trash():
    with _lock, _connect() as conn:
        return conn.execute("SELECT COUNT(*) AS c FROM images WHERE deleted_at IS NOT NULL").fetchone()["c"]


# --------------------------------------------------------------------------- #
#  Journal d'erreurs de génération (les échecs ne laissent pas d'image en base)
# --------------------------------------------------------------------------- #
def log_generation_error(model_name, prompt, error, kind="gen"):
    try:
        with _lock, _connect() as conn:
            conn.execute(
                "INSERT INTO generation_errors (created, model_name, prompt, error, kind) VALUES (?,?,?,?,?)",
                (datetime.now().isoformat(timespec="seconds"),
                 (model_name or "")[:120], (prompt or "")[:1000],
                 str(error or "")[:2000], (kind or "gen")[:30]))
            conn.commit()
    except Exception:
        pass  # le journal d'erreurs ne doit jamais casser la génération


def list_generation_errors(limit=50):
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT id, created, model_name, prompt, error, kind FROM generation_errors"
            " ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
        return [dict(r) for r in rows]


def count_generation_errors():
    with _lock, _connect() as conn:
        return conn.execute("SELECT COUNT(*) AS c FROM generation_errors").fetchone()["c"]


def clear_generation_errors():
    with _lock, _connect() as conn:
        cur = conn.execute("DELETE FROM generation_errors")
        conn.commit()
        return cur.rowcount


def source_is_referenced(path):
    """Une source utilisée par l'historique doit rester disponible."""
    with _lock, _connect() as conn:
        rows = conn.execute("SELECT source_images FROM images WHERE source_images IS NOT NULL")
        for row in rows:
            try:
                if path in json.loads(row["source_images"] or "[]"):
                    return True
            except (ValueError, TypeError):
                continue
    return False


def count_images():
    with _lock, _connect() as conn:
        cur = conn.execute("SELECT COUNT(*) AS c FROM images WHERE deleted_at IS NULL")
        return cur.fetchone()["c"]


# --------------------------------------------------------------------------- #
#  Statistiques
# --------------------------------------------------------------------------- #
def get_stats():
    """Retourne un dict avec toutes les statistiques agregrees."""
    with _lock, _connect() as conn:
        total = conn.execute("SELECT COUNT(*) AS c FROM images WHERE deleted_at IS NULL").fetchone()["c"]

        # Stats par modele
        per_model = conn.execute("""
            SELECT model, model_name,
                   COUNT(*) as img_count,
                   COUNT(DISTINCT batch_id) as gen_count,
                   ROUND(AVG(gen_time), 1) as avg_time,
                   ROUND(MIN(gen_time), 1) as min_time,
                   ROUND(MAX(gen_time), 1) as max_time,
                   ROUND(SUM(gen_time), 1) as total_time
            FROM images WHERE deleted_at IS NULL
            GROUP BY model
            ORDER BY img_count DESC
        """).fetchall()

        # Temps total cumule
        total_time_row = conn.execute(
            "SELECT ROUND(SUM(gen_time),1) as t FROM images WHERE deleted_at IS NULL"
        ).fetchone()
        total_time = total_time_row["t"] or 0

        # Avg global
        avg_row = conn.execute(
            "SELECT ROUND(AVG(gen_time),1) as a FROM images WHERE gen_time > 0 AND deleted_at IS NULL"
        ).fetchone()
        avg_time = avg_row["a"] or 0

        # Resolution la plus utilisee
        res_row = conn.execute("""
            SELECT width || 'x' || height as res, COUNT(*) as c
            FROM images WHERE deleted_at IS NULL GROUP BY res ORDER BY c DESC LIMIT 1
        """).fetchone()
        fav_res = res_row["res"] if res_row else "-"

        # 20 dernieres generations (pour un mini graphique)
        recent = conn.execute("""
            SELECT model_name, gen_time, created, model
            FROM images WHERE gen_time > 0 AND deleted_at IS NULL
            ORDER BY id DESC LIMIT 20
        """).fetchall()

        # Favoris
        favorites = conn.execute(
            "SELECT COUNT(*) AS c FROM images WHERE COALESCE(favorite, 0) = 1 AND deleted_at IS NULL"
        ).fetchone()["c"]

        # Generations sur les 7 derniers jours (approx., sur la date de creation)
        try:
            last7 = conn.execute("""
                SELECT COUNT(*) AS c FROM images
                WHERE date(created) >= date('now', '-6 days') AND deleted_at IS NULL
            """).fetchone()["c"]
        except Exception:
            last7 = 0

        return {
            "total_images": total,
            "total_generations": len(set(r["batch_id"] for r in
                  conn.execute("SELECT batch_id FROM images WHERE deleted_at IS NULL").fetchall())),
            "favorites": favorites,
            "last7_days": last7,
            "total_time_sec": total_time,
            "avg_time_sec": avg_time,
            "per_model": [dict(r) for r in per_model],
            "fav_resolution": fav_res,
            "recent": [dict(r) for r in recent],
        }


# --------------------------------------------------------------------------- #
#  Styles personnalisés (page Gestion des styles)
# --------------------------------------------------------------------------- #
_VALID_APPLIES = ("gen", "edit", "both")


def _style_row(r):
    d = dict(r)
    try:
        models = json.loads(d.get("models") or "\"all\"")
    except Exception:
        models = "all"
    if models != "all" and not isinstance(models, list):
        models = "all"
    d["models"] = models
    return d


def list_user_styles():
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM user_styles ORDER BY updated DESC, id DESC").fetchall()
        return [_style_row(r) for r in rows]


def user_styles_for(model_id, applies_to):
    """Styles personnalisés applicables à `model_id` pour 'gen' ou 'edit'."""
    with _lock, _connect() as conn:
        rows = conn.execute("SELECT * FROM user_styles").fetchall()
    out = []
    for r in rows:
        d = _style_row(r)
        if d["applies_to"] not in (applies_to, "both"):
            continue
        models = d["models"]
        if models != "all" and (not isinstance(models, list) or model_id not in models):
            continue
        out.append(d)
    return out


def create_user_style(name, prompt, applies_to="both", models="all"):
    name = (name or "").strip()[:80]
    prompt = (prompt or "").strip()
    if not name or not prompt:
        raise ValueError("Le nom et le prompt sont obligatoires.")
    if applies_to not in _VALID_APPLIES:
        raise ValueError("applies_to doit valoir gen, edit ou both.")
    if models != "all" and not isinstance(models, list):
        raise ValueError("models doit valoir 'all' ou une liste d'identifiants.")
    models_json = "all" if models == "all" else json.dumps([str(m) for m in models], ensure_ascii=False)
    now = datetime.now().isoformat(timespec="seconds")
    with _lock, _connect() as conn:
        cur = conn.execute(
            "INSERT INTO user_styles (name, prompt, applies_to, models, created, updated)"
            " VALUES (?,?,?,?,?,?)",
            (name, prompt, applies_to, models_json, now, now))
        conn.commit()
        return cur.lastrowid


def update_user_style(style_id, name, prompt, applies_to="both", models="all"):
    name = (name or "").strip()[:80]
    prompt = (prompt or "").strip()
    if not name or not prompt:
        raise ValueError("Le nom et le prompt sont obligatoires.")
    if applies_to not in _VALID_APPLIES:
        raise ValueError("applies_to doit valoir gen, edit ou both.")
    if models != "all" and not isinstance(models, list):
        raise ValueError("models doit valoir 'all' ou une liste d'identifiants.")
    models_json = "all" if models == "all" else json.dumps([str(m) for m in models], ensure_ascii=False)
    now = datetime.now().isoformat(timespec="seconds")
    with _lock, _connect() as conn:
        cur = conn.execute(
            "UPDATE user_styles SET name=?, prompt=?, applies_to=?, models=?, updated=? WHERE id=?",
            (name, prompt, applies_to, models_json, now, int(style_id)))
        conn.commit()
        return cur.rowcount > 0


def delete_user_style(style_id):
    with _lock, _connect() as conn:
        cur = conn.execute("DELETE FROM user_styles WHERE id=?", (int(style_id),))
        conn.commit()
        return cur.rowcount > 0
