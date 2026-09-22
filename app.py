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
        "source_image": data.get("source_image"),
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
            # dossier du batch si vide
            if fp.parent != config.OUTPUT_DIR and not any(fp.parent.iterdir()):
                fp.parent.rmdir()
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
    """Upload une image source pour img2img/edition. Renvoie le path relatif."""
    if "image" not in request.files:
        return jsonify({"ok": False, "error": "Aucune image fournie."}), 400
    f = request.files["image"]
    if not f.filename or not f.filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
        return jsonify({"ok": False, "error": "Format non supporté. Utilisez PNG, JPG ou WEBP."}), 400
    ext = Path(f.filename).suffix.lower()
    unique_name = f"{uuid.uuid4().hex[:12]}{ext}"
    dest = config.SOURCE_IMAGES_DIR / unique_name
    f.save(str(dest))
    rel = dest.relative_to(config.ROOT).as_posix()
    return jsonify({"ok": True, "filename": rel, "url": f"/source-images/{unique_name}"})

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
    print(f"\n  ➜  Local Image Studio : http://127.0.0.1:{port}\n")
    # use_reloader=False : évite de relancer deux fois les téléchargements/threads
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)
