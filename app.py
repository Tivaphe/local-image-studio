# -*- coding: utf-8 -*-
"""
Local Image Studio — interface web simple pour générer des images en local
avec les modèles GGUF et certains checkpoints safetensors via stable-diffusion.cpp.

Démarrage :  python app.py   (puis ouvrir http://127.0.0.1:7860)
"""
import sys
from pathlib import Path

from flask import (Flask, render_template, request, jsonify, send_from_directory,
                   redirect, url_for)

import config
import db
import engine
from engine import (tasks, load_settings, save_settings, hf_token, engine_ready,
                    model_status)
from registry import (MODELS, DEPS, RATIOS, DEFAULT_NEGATIVE, input_modes,
                      max_ref_images, check_images_input, clamp_ref_max_pixels)
import gpu_info
import uuid
try:
    import prompt_enhancer
    _ENHANCER_OK = True
except Exception as _e:
    print(f"[!] Module prompt_enhancer indisponible: {_e}")
    print("[!] L'enrichissement de prompt est desactive. Le reste fonctionne normalement.")
    _ENHANCER_OK = False

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False
# Flask >= 2.3 : c'est le provider JSON qui fait foi (la config ci-dessus est ignoree).
# `sort_keys=False` conserve l'ordre du registre dans /api/models (le plus pertinent d'abord),
# `ensure_ascii=False` laisse les accents lisibles dans les messages d'erreur.
app.json.sort_keys = False
app.json.ensure_ascii = False

db.init_db()


# --------------------------------------------------------------------------- #
#  Pages
# --------------------------------------------------------------------------- #
@app.route("/")
def index():
    return redirect(url_for("generate"))


@app.route("/generate")
def generate():
    return render_template("generate.html", models=MODELS, ratios=RATIOS)


@app.route("/edit")
def edit():
    """Studio d'edition : canvas + references multiples (modeles d'edition semantique)."""
    return render_template("edit.html", models=MODELS, ratios=RATIOS)


@app.route("/history")
def history():
    model_filter = request.args.get("model", "")
    images = db.list_images(limit=300, model_id=(model_filter or None))
    return render_template("history.html", images=images, models=MODELS,
                           model_filter=model_filter, count=db.count_images())


@app.route("/models")
def models_page():
    statuses = {mid: model_status(mid) for mid in MODELS}
    vram_mb, gpu_name = gpu_info.get_gpu_info()
    return render_template("models.html", models=MODELS, deps=DEPS,
                           statuses=statuses, engine_ready=engine_ready(),
                           token_set=bool(hf_token()),
                           vram_gb=round(vram_mb/1024, 1) if vram_mb else 0,
                           gpu_name=gpu_name)


@app.route("/settings")
def settings_page():
    return render_template("settings.html", settings=load_settings())


# --------------------------------------------------------------------------- #
#  Fichiers générés
# --------------------------------------------------------------------------- #
@app.route("/output/<path:filename>")
def serve_output(filename):
    return send_from_directory(str(config.OUTPUT_DIR), filename)


# --------------------------------------------------------------------------- #
#  Images sources uploadees (edition / img2img)
# --------------------------------------------------------------------------- #
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")


@app.route("/source-images/<path:filename>")
def serve_source_image(filename):
    """Sert les images sources (reaffichees dans l'historique et le studio d'edition)."""
    return send_from_directory(str(config.SOURCE_IMAGES_DIR), filename)


def _source_rel_path(dest: Path) -> str:
    """Chemin relatif stocke dans les params de generation (le moteur tourne a la racine)."""
    return dest.relative_to(config.ROOT).as_posix()


def _source_url(rel_path: str) -> str:
    return f"/source-images/{Path(rel_path).name}"


def _existing_sources(rel_paths):
    """Garde uniquement les fichiers qui existent vraiment, dans l'ordre donne."""
    out = []
    for p in rel_paths or []:
        p = str(p).strip()
        if not p:
            continue
        candidate = (config.ROOT / p) if not Path(p).is_absolute() else Path(p)
        try:
            resolved = candidate.resolve()
            resolved.relative_to(config.SOURCE_IMAGES_DIR.resolve())
        except Exception:
            # chemin hors du dossier attendu -> refuse
            continue
        if resolved.exists():
            out.append(_source_rel_path(resolved))
    return out


# --------------------------------------------------------------------------- #
#  API : état global
# --------------------------------------------------------------------------- #
@app.route("/api/status")
def api_status():
    snap = tasks.snapshot()
    # nettoyage du champ lourd pour le front (on garde log court)
    snap.pop("result_tail", None)
    # stats de generation (temps) depuis le resultat ou l'etat live
    stats = None
    result = snap.get("result")
    if result and isinstance(result, dict) and result.get("stats"):
        stats = result["stats"]
    return jsonify({
        "busy": snap["busy"],
        "kind": snap["kind"],
        "log": snap["log"],
        "progress": snap["progress"],
        "step": snap["step"],
        "total_steps": snap["total_steps"],
        "error": snap["error"],
        "done": snap["done"],
        "result": snap["result"],
        "engine_ready": engine_ready(),
        "elapsed": snap.get("elapsed", 0.0),
        "eta": snap.get("eta", 0.0),
        "stats": stats,
    })


# --------------------------------------------------------------------------- #
#  API : modèles
# --------------------------------------------------------------------------- #
@app.route("/api/models")
def api_models():
    out = {}
    for mid, m in MODELS.items():
        st = model_status(mid)
        out[mid] = {
            "id": mid,
            "name": m["name"], "desc": m["desc"], "arch": m["arch"],
            "repo": m["repo"],
            "license": m.get("license", ""),
            "hf_url": m.get("hf_url", ""),
            "vram_min_gb": m.get("vram_min_gb", 0),
            "quants": m["quants"],
            "default_quant": m["default_quant"],
            "size_gb": m["size_gb"], "supports_neg": m.get("supports_neg", False),
            "needs_token": m.get("needs_token", False),
            "defaults": m["defaults"],
            "min_steps": m.get("min_steps", 1), "max_steps": m.get("max_steps", 50),
            "fixed_steps": m.get("fixed_steps"), "fixed_cfg": m.get("fixed_cfg"),
            "deps": m["deps"],
            "supports_img2img": m.get("supports_img2img", False),
            "mmproj_dep": m.get("mmproj_dep"),
            "presets": m.get("presets", {}),
            # --- Capacites d'entree image (edition / img2img) ---
            "supports_ref_images": m.get("supports_ref_images", False),
            "input_modes": input_modes(mid),
            "max_ref_images": max_ref_images(mid),
            "ref_tag_syntax": m.get("ref_tag_syntax"),
            "ref_needs_vlm": m.get("ref_needs_vlm", False),
            "ref_hint": m.get("ref_hint", ""),
            "ref_examples": m.get("ref_examples", []),
            "status": st,
        }
    return jsonify(out)


@app.route("/api/download-model", methods=["POST"])
def api_download_model():
    data = request.get_json(force=True)
    mid = data.get("model_id")
    quant = data.get("quant") or MODELS[mid]["default_quant"]
    if mid not in MODELS:
        return jsonify({"ok": False, "error": "Modèle inconnu"}), 400
    if MODELS[mid].get("needs_token") and not hf_token():
        return jsonify({"ok": False,
                        "error": "Ce modèle est protégé (gated). Ajoutez un token Hugging Face dans Paramètres."}), 400
    try:
        tasks.start_download(mid, quant)
    except RuntimeError as e:
        return jsonify({"ok": False, "error": str(e)}), 409
    return jsonify({"ok": True})


@app.route("/api/download-engine", methods=["POST"])
def api_download_engine():
    try:
        tasks.start_engine_install()
    except RuntimeError as e:
        return jsonify({"ok": False, "error": str(e)}), 409
    return jsonify({"ok": True})


# --------------------------------------------------------------------------- #
#  API : génération
# --------------------------------------------------------------------------- #
@app.route("/api/generate", methods=["POST"])
def api_generate():
    data = request.get_json(force=True)
    mid = data.get("model_id")
    if mid not in MODELS:
        return jsonify({"ok": False, "error": "Modèle inconnu"}), 400
    m = MODELS[mid]
    quant = data.get("quant") or m["default_quant"]
    ratio = data.get("ratio", "1:1")
    w, h = RATIOS.get(ratio, RATIOS["1:1"])
    if data.get("width") and data.get("height"):
        w, h = int(data["width"]), int(data["height"])

    # --- Images fournies : refs (edition) ou image de depart (img2img) ---
    raw_images = data.get("ref_images")
    if not raw_images:
        legacy = data.get("source_image")
        raw_images = [legacy] if legacy else []
    if isinstance(raw_images, str):
        raw_images = [raw_images]
    images = _existing_sources(raw_images)
    missing = len([p for p in raw_images if str(p).strip()]) - len(images)
    if missing > 0:
        return jsonify({"ok": False,
                        "error": f"{missing} image(s) source(s) introuvable(s) sur le disque. "
                                 "Ré-uploadez-les."}), 400
    images, input_mode, err = check_images_input(mid, images, data.get("input_mode"))
    if err:
        return jsonify({"ok": False, "error": err}), 400

    params = {
        "model_id": mid,
        "quant": quant,
        "prompt": (data.get("prompt") or "").strip(),
        "negative": (data.get("negative") or "").strip(),
        "width": w, "height": h,
        "steps": int(m.get("fixed_steps", data.get("steps") or m["defaults"]["steps"])),
        "cfg": float(m.get("fixed_cfg", data.get("cfg") or m["defaults"]["cfg"])),
        "seed": data.get("seed"),
        "batch": max(1, min(4, int(data.get("batch") or 1))),
        "ref_images": images,
        "input_mode": input_mode,
        "ref_max_pixels": clamp_ref_max_pixels(data.get("ref_max_pixels")),
        "source_image": images[0] if (images and input_mode == "init") else None,
        "strength": data.get("strength") if input_mode == "init" else None,
        "lora_dir": data.get("lora_dir"),
    }
    if not params["prompt"]:
        return jsonify({"ok": False, "error": "Le prompt est vide."}), 400
    try:
        tasks.start_generate(params)
    except RuntimeError as e:
        return jsonify({"ok": False, "error": str(e)}), 409
    return jsonify({"ok": True, "params": params})


@app.route("/api/cancel", methods=["POST"])
def api_cancel():
    tasks.cancel()
    return jsonify({"ok": True})


# --------------------------------------------------------------------------- #
#  API : téléchargement mmproj (pour l'édition des modèles Qwen-Image)
# --------------------------------------------------------------------------- #
def _mmproj_dep_for(model_id=None):
    """Dépendance mmproj attendue par un modèle (défaut : celle partagée par Qwen-Image)."""
    m = MODELS.get(model_id or "", {})
    return m.get("mmproj_dep") or "mmproj_qwen3vl_8b"


@app.route("/api/download-mmproj", methods=["POST"])
def api_download_mmproj():
    """Télécharge le fichier mmproj (encodeur visuel) requis pour l'édition."""
    from registry import load_manifest
    from engine import ensure_dep, hf_token
    from pathlib import Path
    data = request.get_json(silent=True) or {}
    dep_id = _mmproj_dep_for(data.get("model_id") or request.args.get("model_id"))
    try:
        ensure_dep(dep_id, hf_token())
        manifest = load_manifest()
        info = manifest.get(dep_id, {})
        path = info.get("path")
        exists = path and Path(path).exists()
        if exists:
            return jsonify({"ok": True, "message": "mmproj téléchargé ✓", "status": "ready",
                            "dep": dep_id})
        else:
            return jsonify({"ok": False, "error": "Téléchargement effectué mais fichier non trouvé"}, status=500)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/mmproj-status", methods=["GET"])
def api_mmproj_status():
    """Vérifie si mmproj est téléchargé (par modèle : ?model_id=qwen-image-2.1)."""
    from registry import load_manifest, _dep_path
    from pathlib import Path
    model_id = request.args.get("model_id")
    if model_id and model_id not in MODELS:
        return jsonify({"downloaded": False, "error": "Modèle inconnu"}), 400
    needs = bool(MODELS.get(model_id or "", {}).get("mmproj_dep")) if model_id else True
    dep_id = _mmproj_dep_for(model_id)
    path = _dep_path(load_manifest(), dep_id)
    exists = bool(path and Path(path).exists())
    return jsonify({
        "downloaded": exists,
        "required": needs,
        "dep": dep_id,
        "path": path if exists else None
    })


# --------------------------------------------------------------------------- #
#  API : historique
# --------------------------------------------------------------------------- #
@app.route("/api/delete-image", methods=["POST"])
def api_delete_image():
    data = request.get_json(force=True)
    img_id = data.get("id")
    fname = db.delete_image(img_id)
    if fname:
        # suppression du fichier sur disque
        fp = config.OUTPUT_DIR / fname
        try:
            fp.unlink(missing_ok=True)
        except Exception:
            pass
    return jsonify({"ok": True})


# --------------------------------------------------------------------------- #
#  API : paramètres (token HF)
# --------------------------------------------------------------------------- #
@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    if request.method == "POST":
        data = request.get_json(force=True)
        save_settings({"hf_token": (data.get("hf_token") or "").strip()})
        return jsonify({"ok": True, "token_set": bool(hf_token())})
    return jsonify({"hf_token": hf_token()})



# --------------------------------------------------------------------------- #
#  API : enrichissement de prompt (LLM)
# --------------------------------------------------------------------------- #
@app.route("/api/enhancer-status")
def api_enhancer_status():
    if not _ENHANCER_OK:
        return jsonify({"downloaded": False, "unavailable": True})
    return jsonify({"downloaded": prompt_enhancer.enhancer_available()})

@app.route("/api/download-enhancer", methods=["POST"])
def api_download_enhancer():
    # L'enrichisseur reutilise Qwen3-4B (deja telecharge avec Z-Image / FLUX.2-klein-4B)
    # Pas de telechargement separe necessaire.
    if not _ENHANCER_OK:
        return jsonify({"ok": False, "error": "Module prompt_enhancer manquant."}), 500
    if prompt_enhancer.enhancer_available():
        return jsonify({"ok": True, "message": "Deja disponible"})
    return jsonify({"ok": False,
                    "error": "Telechargez d'abord Z-Image ou FLUX.2-klein-4B dans l'onglet Modeles. "
                             "Ils incluent Qwen3-4B qui sert aussi d'enrichisseur de prompt."}), 400

@app.route("/api/enrich", methods=["POST"])
def api_enrich():
    data = request.get_json(force=True)
    user_prompt = (data.get("prompt") or "").strip()
    mode = data.get("mode", "enrich")
    if not user_prompt:
        return jsonify({"ok": False, "error": "Prompt vide."}), 400
    if not _ENHANCER_OK or not prompt_enhancer.enhancer_available():
        return jsonify({"ok": False,
                        "error": "Le modele d'enrichissement n'est pas telecharge. Allez dans Parametres."}), 400
    try:
        result = prompt_enhancer.enrich_prompt(user_prompt, mode=mode)
        return jsonify({"ok": True, "prompt": result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500




# --------------------------------------------------------------------------- #
#  API : upload d'image source (pour img2img / edition)
# --------------------------------------------------------------------------- #
@app.route("/api/upload-source-image", methods=["POST"])
def api_upload_source_image():
    """
    Upload une ou plusieurs images sources (edition / img2img).

    - `image`  : un seul fichier (comportement historique)
    - `images` : plusieurs fichiers, dans l'ordre desire (le premier = canvas edite)
    Renvoie `files: [{filename, url, name}]` + `filename`/`url` pour la retro-compatibilite.
    """
    files = request.files.getlist("images") or request.files.getlist("image")
    if not files:
        return jsonify({"ok": False, "error": "Aucune image fournie."}), 400

    mid = request.form.get("model_id")
    limit = max_ref_images(mid, request.form.get("input_mode")) if mid in MODELS else 10

    saved, errors = [], []
    for f in files[:max(1, limit)]:
        if not f.filename or not f.filename.lower().endswith(IMAGE_EXTS):
            errors.append(f"{f.filename or 'fichier sans nom'} : format non supporté "
                          f"(PNG, JPG, WEBP)")
            continue
        ext = Path(f.filename).suffix.lower()
        unique_name = f"{uuid.uuid4().hex[:12]}{ext}"
        dest = config.SOURCE_IMAGES_DIR / unique_name
        f.save(str(dest))
        rel = _source_rel_path(dest)
        saved.append({"filename": rel, "url": _source_url(rel), "name": f.filename})
    if len(files) > len(saved):
        if len(files) > max(1, limit):
            errors.append(f"Seules les {max(1, limit)} premières images ont été gardées "
                          f"({len(files)} fournies).")
    if not saved:
        return jsonify({"ok": False, "error": "\n".join(errors) or "Aucune image valide."}), 400
    return jsonify({"ok": True, "files": saved,
                    "error": "\n".join(errors) if errors else None,
                    "filename": saved[0]["filename"], "url": saved[0]["url"]})


@app.route("/api/delete-source-image", methods=["POST"])
def api_delete_source_image():
    """Supprime une image source uploadee mais non utilisee."""
    data = request.get_json(force=True)
    rel = str(data.get("filename") or "").strip()
    if not rel:
        return jsonify({"ok": False, "error": "Aucun fichier indiqué."}), 400
    target = config.ROOT / rel
    try:
        target = target.resolve()
        target.relative_to(config.SOURCE_IMAGES_DIR.resolve())
    except Exception:
        return jsonify({"ok": False, "error": "Chemin refusé."}), 400
    existed = target.exists()
    if existed:
        try:
            target.unlink()
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": True, "deleted": existed})


@app.route("/api/image/<int:img_id>")
def api_image(img_id):
    """Parametres complets d'une image de l'historique (pour rejouer une edition)."""
    row = db.get_image(img_id)
    if not row:
        return jsonify({"ok": False, "error": "Image inconnue."}), 404
    sources = []
    for rel in row.get("source_images_list") or []:
        if (config.ROOT / rel).exists():
            sources.append({"filename": rel, "url": _source_url(rel)})
    return jsonify({"ok": True, "image": {
        "id": row["id"], "model": row["model"], "model_name": row["model_name"],
        "quant": row["quant"], "prompt": row["prompt"], "negative": row["negative"],
        "steps": row["steps"], "cfg": row["cfg"], "seed": row["seed"],
        "width": row["width"], "height": row["height"],
        "source_images": sources,
    }})

# --------------------------------------------------------------------------- #
#  API : statistiques
# --------------------------------------------------------------------------- #
@app.route("/api/stats")
def api_stats():
    return jsonify(db.get_stats())


# --------------------------------------------------------------------------- #
#  API : infos GPU / VRAM
# --------------------------------------------------------------------------- #
@app.route("/api/gpu-info")
def api_gpu_info():
    vram_mb, name = gpu_info.get_gpu_info()
    return jsonify({"vram_mb": vram_mb, "vram_gb": round(vram_mb/1024, 1),
                    "gpu_name": name})


# --------------------------------------------------------------------------- #
#  API : traduction de prompt
# --------------------------------------------------------------------------- #
@app.route("/api/translate", methods=["POST"])
def api_translate():
    data = request.get_json(force=True)
    user_prompt = (data.get("prompt") or "").strip()
    if not user_prompt:
        return jsonify({"ok": False, "error": "Prompt vide."}), 400
    if not _ENHANCER_OK or not prompt_enhancer.enhancer_available():
        return jsonify({"ok": False, "error": "Traduction indisponible. Telechargez Z-Image ou FLUX.2-klein-4B."}), 400
    try:
        result = prompt_enhancer.translate_prompt(user_prompt)
        return jsonify({"ok": True, "prompt": result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# --------------------------------------------------------------------------- #
#  API : negative prompt par defaut
# --------------------------------------------------------------------------- #
@app.route("/api/default-negative")
def api_default_negative():
    return jsonify({"negative": DEFAULT_NEGATIVE})


# --------------------------------------------------------------------------- #
#  Page statistiques
# --------------------------------------------------------------------------- #
@app.route("/stats")
def stats_page():
    return render_template("stats.html")


if __name__ == "__main__":
    port = 7860
    print(f"\n  ➜  Local Image Studio : http://0.0.0.0:{port}\n")
    # use_reloader=False : évite de relancer deux fois les téléchargements/threads
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
