# -*- coding: utf-8 -*-
"""
Local Image Studio — interface web simple pour générer des images en local
avec les modèles GGUF (FLUX schnell, Z-Image, ERNIE-Turbo, Ideogram 4, FHDR).

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
from registry import MODELS, DEPS, RATIOS, DEFAULT_NEGATIVE
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
            "deps": m["deps"],
            "presets": m.get("presets", {}),
            "status": st,
            # nouvelles capacites multi-images
            "supports_init": m.get("supports_init", m.get("supports_img2img", False)),
            "supports_ref": m.get("supports_ref", False),
            "max_ref_images": m.get("max_ref_images", 0),
            "supports_control": m.get("supports_control", False),
            "supports_mask": m.get("supports_mask", False),
            "supports_ip_adapter": m.get("supports_ip_adapter", False),
            "supports_transparency": m.get("supports_transparency", False),
            "supports_img2img": m.get("supports_img2img", False),
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

    # Normalisation des images : support legacy source_image + nouveau multi-images
    ref_images = data.get("ref_images")  # liste
    if isinstance(ref_images, str):
        ref_images = [ref_images]
    # Filtrer les valeurs vides
    if ref_images:
        ref_images = [x for x in ref_images if x]
        if not ref_images:
            ref_images = None
    # Pour compatibilité, si source_image est une liste, la traiter comme ref_images
    src = data.get("source_image")
    if isinstance(src, list):
        ref_images = (ref_images or []) + src
        src = None

    params = {
        "model_id": mid,
        "quant": quant,
        "prompt": (data.get("prompt") or "").strip(),
        "negative": (data.get("negative") or "").strip(),
        "width": w, "height": h,
        "steps": int(data.get("steps") or m["defaults"]["steps"]),
        "cfg": float(data.get("cfg") or m["defaults"]["cfg"]),
        "seed": data.get("seed"),
        "batch": max(1, min(4, int(data.get("batch") or 1))),
        # legacy
        "source_image": src,
        # nouveau multi-images
        "ref_images": ref_images,
        "init_image": data.get("init_image"),
        "control_image": data.get("control_image"),
        "mask_image": data.get("mask_image"),
        "ip_adapter_image": data.get("ip_adapter_image"),
        "strength": data.get("strength"),
        "control_strength": data.get("control_strength"),
        "ip_adapter_strength": data.get("ip_adapter_strength"),
        "lora_dir": data.get("lora_dir"),
    }
    if not params["prompt"]:
        return jsonify({"ok": False, "error": "Le prompt est vide."}), 400
    # Validation du nombre de ref_images selon le modèle
    max_ref = m.get("max_ref_images", 0)
    if ref_images and max_ref and len(ref_images) > max_ref:
        return jsonify({"ok": False, "error": f"Ce modèle supporte au maximum {max_ref} images de référence (reçu {len(ref_images)})."}), 400
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
#  API : téléchargement mmproj (pour édition Qwen-Image-2.1)
# --------------------------------------------------------------------------- #
@app.route("/api/download-mmproj", methods=["POST"])
def api_download_mmproj():
    """Télécharge le fichier mmproj pour l'édition Qwen-Image-2.1."""
    from registry import DEPS
    from registry import load_manifest
    from engine import ensure_dep, hf_token
    from pathlib import Path
    try:
        token = hf_token()
        ensure_dep("mmproj_qwen3vl_8b", token)
        manifest = load_manifest()
        info = manifest.get("mmproj_qwen3vl_8b", {})
        path = info.get("path")
        exists = path and Path(path).exists()
        if exists:
            return jsonify({"ok": True, "message": "mmproj téléchargé ✓", "status": "ready"})
        else:
            return jsonify({"ok": False, "error": "Téléchargement effectué mais fichier non trouvé"}, status=500)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/mmproj-status", methods=["GET"])
def api_mmproj_status():
    """Vérifie si mmproj est téléchargé."""
    from registry import load_manifest
    from pathlib import Path
    manifest = load_manifest()
    info = manifest.get("mmproj_qwen3vl_8b", {})
    path = info.get("path")
    exists = path and Path(path).exists()
    return jsonify({
        "downloaded": exists,
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
#  Fichiers source (images de référence, init, pose, etc.)
# --------------------------------------------------------------------------- #
@app.route("/source-images/<path:filename>")
def serve_source_images(filename):
    return send_from_directory(str(config.SOURCE_IMAGES_DIR), filename)


# --------------------------------------------------------------------------- #
#  API : upload d'images (multi-images pour Qwen-Image 2.1, FLUX.2, etc.)
# --------------------------------------------------------------------------- #
def _save_uploaded_image(file_storage):
    """Sauvegarde un fichier uploadé et renvoie (rel_path, url, filename)."""
    if not file_storage.filename or not file_storage.filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp")):
        raise ValueError("Format non supporté. Utilisez PNG, JPG, WEBP ou BMP.")
    ext = Path(file_storage.filename).suffix.lower() or ".png"
    unique_name = f"{uuid.uuid4().hex[:12]}{ext}"
    dest = config.SOURCE_IMAGES_DIR / unique_name
    file_storage.save(str(dest))
    rel = dest.relative_to(config.ROOT).as_posix()
    return rel, f"/source-images/{unique_name}", unique_name


@app.route("/api/upload-source-image", methods=["POST"])
def api_upload_source_image():
    """Upload une image source pour img2img/edition. Renvoie le path relatif. (legacy, 1 image)"""
    if "image" not in request.files:
        return jsonify({"ok": False, "error": "Aucune image fournie."}), 400
    try:
        rel, url, _ = _save_uploaded_image(request.files["image"])
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True, "filename": rel, "url": url})


@app.route("/api/upload-images", methods=["POST"])
def api_upload_images():
    """Upload multiple images (jusqu'à 10) pour édition multi-références.
    Accepte :
      - champ 'images' avec plusieurs fichiers
      - ou champ 'image' avec un seul fichier
    Renvoie liste de {filename, url}
    """
    files = []
    # Flask: getlist pour champ multiple
    if "images" in request.files:
        files = request.files.getlist("images")
    elif "image" in request.files:
        files = request.files.getlist("image")
    else:
        # fallback: tous les fichiers envoyés
        files = list(request.files.values())

    if not files:
        return jsonify({"ok": False, "error": "Aucune image fournie."}), 400

    if len(files) > 10:
        return jsonify({"ok": False, "error": "Maximum 10 images à la fois."}), 400

    results = []
    for f in files:
        if not f or not f.filename:
            continue
        try:
            rel, url, _ = _save_uploaded_image(f)
            results.append({"filename": rel, "url": url})
        except ValueError as e:
            return jsonify({"ok": False, "error": f"{f.filename}: {e}"}), 400

    if not results:
        return jsonify({"ok": False, "error": "Aucune image valide."}), 400

    return jsonify({"ok": True, "images": results, "count": len(results)})


@app.route("/api/upload-image", methods=["POST"])
def api_upload_single_generic():
    """Upload générique pour init, control, mask, ip_adapter.
    Param 'type' optionnel pour log (init, control, mask, ref, ip_adapter)
    """
    # Accepte 'image' ou 'file' ou premier fichier
    file_obj = None
    if "image" in request.files:
        file_obj = request.files["image"]
    elif "file" in request.files:
        file_obj = request.files["file"]
    else:
        # premier fichier quelconque
        vals = list(request.files.values())
        if vals:
            file_obj = vals[0]

    if not file_obj:
        return jsonify({"ok": False, "error": "Aucune image fournie."}), 400
    try:
        rel, url, _ = _save_uploaded_image(file_obj)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    img_type = request.form.get("type") or request.args.get("type") or "image"
    return jsonify({"ok": True, "filename": rel, "url": url, "type": img_type})

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
