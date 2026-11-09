# -*- coding: utf-8 -*-
"""
Local Image Studio — interface web simple pour générer des images en local
avec les modèles GGUF et certains checkpoints safetensors via stable-diffusion.cpp.

Démarrage :  python app.py   (le navigateur s'ouvre automatiquement sur http://127.0.0.1:7860)

Options :
  --no-browser  ne pas ouvrir de navigateur au démarrage
  --port N      changer le port d'écoute (défaut : 7860)
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from flask import (Flask, render_template, request, jsonify, send_from_directory,
                   redirect, url_for)

import config
import db
import engine
from engine import (tasks, load_settings, save_settings, hf_token, engine_ready,
                    model_status)
import browser_launch
from registry import (MODELS, DEPS, RATIOS, DEFAULT_NEGATIVE, input_modes,
                      max_ref_images, check_images_input, clamp_ref_max_pixels,
                      supports_outpainting, build_outpaint_prompt,
                      supports_inpainting, build_inpaint_prompt,
                      outpaint_prompt_presets, edit_prompt_presets, gen_prompt_presets,
                      UPSCALERS, ADETAILERS, upscaler_status, adetailer_status,
                      SEEDVR2, seedvr2_status,
                      TAESD, taesd_status, taesd_for_model,
                      PULID, pulid_status, list_portraits, supports_pulid,
                      pulid_weights_path,
                      PID, pid_status,
                      recommended_quant, quant_recommendations,
                      SAMPLERS_INFO, SCHEDULERS_INFO)
import metadata as _pngmeta
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
    search_query = request.args.get("q", "").strip()
    fav_only = request.args.get("fav", "") in ("1", "true", "yes")
    images = db.list_images(
        limit=300,
        model_id=(model_filter or None),
        search_query=(search_query or None),
        favorites_only=fav_only,
    )
    upscaler_ready = any(upscaler_status(uid)["downloaded"] for uid in UPSCALERS)
    repair_ready = any(adetailer_status(did)["downloaded"] for did in ADETAILERS)
    seedvr2_ready = seedvr2_status()["downloaded"]
    pid_ready = pid_status()["downloaded"]
    return render_template("history.html", images=images, models=MODELS,
                           model_filter=model_filter, search_query=search_query,
                           fav_only=fav_only, count=db.count_images(),
                           upscaler_ready=upscaler_ready,
                           repair_ready=repair_ready,
                           seedvr2_ready=seedvr2_ready,
                           pid_ready=pid_ready)


@app.route("/models")
def models_page():
    statuses = {mid: model_status(mid) for mid in MODELS}
    vram_mb, gpu_name = gpu_info.get_gpu_info()
    upscale_cards = [
        {**u, "status": upscaler_status(uid)} for uid, u in UPSCALERS.items()
    ]
    adetailer_cards = [
        {**d, "status": adetailer_status(did)} for did, d in ADETAILERS.items()
    ]
    seedvr2_card = {**SEEDVR2, "status": seedvr2_status()}
    pid_st = pid_status()
    pid_backbone_cards = [
        {**bb, "status": pid_st["backbones"][bb_id]}
        for bb_id, bb in PID["backbones"].items()
    ]
    pid_card = {**{k: v for k, v in PID.items() if k != "backbones"},
                "status": pid_st,
                "backbone_cards": pid_backbone_cards}
    taesd_cards = [
        {**t, "status": taesd_status(tid)} for tid, t in TAESD.items()
    ]
    pulid_card = {**PULID, "status": pulid_status(),
                  "portraits": list_portraits()}
    quant_recs = quant_recommendations(round(vram_mb / 1024, 1) if vram_mb else 0)
    return render_template("models.html", models=MODELS, deps=DEPS,
                           statuses=statuses, engine_ready=engine_ready(),
                           token_set=bool(hf_token()),
                           vram_gb=round(vram_mb/1024, 1) if vram_mb else 0,
                           gpu_name=gpu_name,
                           upscalers=upscale_cards, adetailers=adetailer_cards,
                           seedvr2=seedvr2_card, taesd=taesd_cards, pulid=pulid_card,
                           pid=pid_card,
                           quant_recs=quant_recs)


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
#  Aperçus en direct (fichiers temporaires écrits par sd-cli pendant l'échantillonnage)
# --------------------------------------------------------------------------- #
@app.route("/preview-cache/<path:filename>")
def serve_preview(filename):
    """Sert l'image d'aperçu la plus récente (rafraîchie par le front en polling)."""
    safe = Path(filename).name
    f = config.PREVIEW_DIR / safe
    if not f.exists():
        return "", 404
    resp = send_from_directory(str(config.PREVIEW_DIR), safe)
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


@app.route("/api/preview")
def api_preview():
    """Retourne l'aperçu le plus récent du job en cours (ou 404 s'il n'y en a pas encore)."""
    snap = tasks.state
    bid = snap.get("preview_batch_id")
    best = None
    try:
        candidates = list(config.PREVIEW_DIR.glob(
            f"live_{bid}_*.png" if bid else "live_*.png"))
    except Exception:
        candidates = []
    if candidates:
        best = max(candidates, key=lambda f: f.stat().st_mtime)
    if not best:
        # repli global : le fichier live_ le plus récent, quel que soit le batch
        try:
            candidates = list(config.PREVIEW_DIR.glob("live_*.png"))
            if candidates:
                best = max(candidates, key=lambda f: f.stat().st_mtime)
        except Exception:
            best = None
    if not best:
        return jsonify({"ok": False, "error": "Aperçu pas encore disponible."}), 404
    return jsonify({"ok": True, "url": f"/preview-cache/{best.name}",
                    "mtime": best.stat().st_mtime})


# --------------------------------------------------------------------------- #
#  Images sources uploadees (edition / img2img)
# --------------------------------------------------------------------------- #
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")


@app.route("/source-images/<path:filename>")
def serve_source_image(filename):
    """Sert les images sources (reaffichees dans l'historique et le studio d'edition)."""
    return send_from_directory(str(config.SOURCE_IMAGES_DIR), filename)


@app.route("/portraits/<path:filename>")
def serve_portrait(filename):
    """Sert les vignettes de portraits (fichiers .png/.jpg/.jpeg/.webp de portraits/)."""
    safe = Path(filename).name
    if Path(safe).suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
        return "", 404
    return send_from_directory(str(config.PORTRAITS_DIR), safe)


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
        "queue": snap.get("queue", []),
        "queue_size": snap.get("queue_size", 0),
        "preview_batch_id": snap.get("preview_batch_id"),
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
            "supports_outpainting": supports_outpainting(mid),
            "supports_inpainting": supports_inpainting(mid),
            "input_modes": input_modes(mid),
            "max_ref_images": max_ref_images(mid),
            "ref_tag_syntax": m.get("ref_tag_syntax"),
            "ref_needs_vlm": m.get("ref_needs_vlm", False),
            "ref_hint": m.get("ref_hint", ""),
            "ref_examples": m.get("ref_examples", []),
            "outpaint_presets": outpaint_prompt_presets(mid),
            "edit_presets": edit_prompt_presets(mid),
            "gen_presets": gen_prompt_presets(mid),
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
#  API : Qualité, Upscaling ×4 & ADetailer
# --------------------------------------------------------------------------- #
@app.route("/api/quality-info")
def api_quality_info():
    """Catalogue qualité : échantillonneurs, planificateurs, modèles ×4, détecteurs,
    SeedVR2, mini-VAE TAE, PuLID et PiD."""
    vram_mb, _gpu = gpu_info.get_gpu_info()
    vram_gb = round(vram_mb / 1024, 1) if vram_mb else 0
    pid_st = pid_status()
    pid_card = {**{k: v for k, v in PID.items() if k != "backbones"},
                "backbones": {
                    bb_id: {**bb, "status": pid_st["backbones"][bb_id]}
                    for bb_id, bb in PID["backbones"].items()
                },
                "status": pid_st}
    return jsonify({
        "ok": True,
        "engine_ready": engine_ready(),
        "vram_gb": vram_gb,
        "samplers": SAMPLERS_INFO,
        "schedulers": SCHEDULERS_INFO,
        "upscalers": [
            {**u, "status": upscaler_status(uid)} for uid, u in UPSCALERS.items()
        ],
        "adetailers": [
            {**d, "status": adetailer_status(did)} for did, d in ADETAILERS.items()
        ],
        "seedvr2": {**SEEDVR2, "status": seedvr2_status()},
        "taesd": [
            {**t, "status": taesd_status(tid)} for tid, t in TAESD.items()
        ],
        "pid": pid_card,
        "pulid": {**PULID, "status": pulid_status(),
                  "portraits": list_portraits()},
        "quant_recommendations": quant_recommendations(vram_gb),
    })


@app.route("/api/download-upscaler", methods=["POST"])
def api_download_upscaler():
    data = request.get_json(force=True)
    uid = data.get("upscaler_id", "")
    if uid not in UPSCALERS:
        return jsonify({"ok": False, "error": "Modèle d'agrandissement inconnu"}), 400
    try:
        tasks.start_upscaler_download(uid)
    except RuntimeError as e:
        return jsonify({"ok": False, "error": str(e)}), 409
    return jsonify({"ok": True})


@app.route("/api/download-adetailer", methods=["POST"])
def api_download_adetailer():
    data = request.get_json(force=True)
    did = data.get("detector_id", "")
    if did not in ADETAILERS:
        return jsonify({"ok": False, "error": "Détecteur ADetailer inconnu"}), 400
    try:
        tasks.start_adetailer_download(did)
    except RuntimeError as e:
        return jsonify({"ok": False, "error": str(e)}), 409
    return jsonify({"ok": True})


@app.route("/api/upscale", methods=["POST"])
def api_upscale():
    """Agrandit ×4 une image déjà générée (sorties de output/ ou entrée de l'historique)."""
    data = request.get_json(force=True)
    uid = (data.get("upscaler_id") or "").strip()
    if uid and uid not in UPSCALERS:
        return jsonify({"ok": False, "error": "Modèle d'agrandissement inconnu."}), 400
    if not uid:
        # Choix automatique : le premier modèle ×4 installé (ordre du registre).
        uid = next((k for k in UPSCALERS if upscaler_status(k)["downloaded"]), None)
        if not uid:
            return jsonify({"ok": False, "error": (
                "Aucun modèle d'agrandissement n'est installé. Téléchargez-en un dans "
                "l'onglet Modèles, section « 🔍 Upscaling ×4 » (quelques dizaines de Mo)."
            )}), 400
    elif not upscaler_status(uid)["downloaded"]:
        return jsonify({"ok": False, "error": (
            f"« {UPSCALERS[uid]['name']} » n'est pas installé. Téléchargez-le dans "
            "l'onglet Modèles, section « 🔍 Upscaling ×4 »."
        )}), 400

    # Résolution de l'image source : identifiant d'historique, ou chemin dans output/.
    if data.get("image_id") is not None:
        try:
            img = db.get_image(int(data["image_id"]))
        except Exception:
            img = None
        if not img:
            return jsonify({"ok": False, "error": "Image introuvable dans l'historique."}), 404
        fn = img["filename"]
        if not (config.OUTPUT_DIR / fn).exists():
            return jsonify({"ok": False,
                            "error": "Le fichier image n'existe plus sur le disque."}), 404
        src_rel = str(Path("output") / fn)
    else:
        raw = str(data.get("path") or "").strip().lstrip("/")
        if raw.startswith("output/"):
            raw = raw[len("output/"):]
        cand = config.OUTPUT_DIR / raw
        try:
            cand.resolve().relative_to(config.OUTPUT_DIR.resolve())
        except Exception:
            return jsonify({"ok": False, "error": "Chemin d'image invalide."}), 400
        if not raw or not cand.exists():
            return jsonify({"ok": False, "error": "Image introuvable sur le disque."}), 404
        src_rel = str(Path("output") / raw)

    params = {
        "task_kind": "upscale",
        "upscaler_id": uid,
        "source_image": src_rel,
    }
    try:
        q_info = tasks.enqueue_generate(params)
        return jsonify({"ok": True, "upscaler_id": uid, **q_info})
    except RuntimeError as e:
        return jsonify({"ok": False, "error": str(e)}), 409


def _resolve_source_image(data):
    """Résout l'image source d'une opération sur fichier : (src_rel, erreur_json_ou_None)."""
    if data.get("image_id") is not None:
        try:
            img = db.get_image(int(data["image_id"]))
        except Exception:
            img = None
        if not img:
            return None, (jsonify({"ok": False,
                                   "error": "Image introuvable dans l'historique."}), 404)
        fn = img["filename"]
        if not (config.OUTPUT_DIR / fn).exists():
            return None, (jsonify({"ok": False,
                                   "error": "Le fichier image n'existe plus sur le disque."}), 404)
        return str(Path("output") / fn), None
    raw = str(data.get("path") or "").strip().lstrip("/")
    if raw.startswith("output/"):
        raw = raw[len("output/"):]
    cand = config.OUTPUT_DIR / raw
    try:
        cand.resolve().relative_to(config.OUTPUT_DIR.resolve())
    except Exception:
        return None, (jsonify({"ok": False, "error": "Chemin d'image invalide."}), 400)
    if not raw or not cand.exists():
        return None, (jsonify({"ok": False, "error": "Image introuvable sur le disque."}), 404)
    return str(Path("output") / raw), None


@app.route("/api/download-seedvr2", methods=["POST"])
def api_download_seedvr2():
    try:
        tasks.start_seedvr2_download()
    except RuntimeError as e:
        return jsonify({"ok": False, "error": str(e)}), 409
    return jsonify({"ok": True})


@app.route("/api/download-pid", methods=["POST"])
def api_download_pid():
    """Télécharge le socle PiD (Gemma 2 2B + tokenizer non-gated) + le backbone choisi."""
    data = request.get_json(silent=True) or {}
    backbone = (data.get("backbone") or "").strip()
    if backbone not in PID["backbones"]:
        return jsonify({"ok": False, "error": f"Backbone PiD inconnu : {backbone or '?'}. "
                        f"Choix : {', '.join(PID['backbones'])}"}), 400
    try:
        tasks.start_pid_download(backbone)
    except RuntimeError as e:
        return jsonify({"ok": False, "error": str(e)}), 409
    return jsonify({"ok": True, "backbone": backbone})


@app.route("/api/download-taesd", methods=["POST"])
def api_download_taesd():
    data = request.get_json(silent=True) or {}
    ta_id = (data.get("taesd_id") or "").strip()
    if ta_id not in TAESD:
        return jsonify({"ok": False, "error": "Mini-VAE inconnu."}), 400
    try:
        tasks.start_taesd_download(ta_id)
    except RuntimeError as e:
        return jsonify({"ok": False, "error": str(e)}), 409
    return jsonify({"ok": True})


@app.route("/api/download-pulid", methods=["POST"])
def api_download_pulid():
    try:
        tasks.start_pulid_download()
    except RuntimeError as e:
        return jsonify({"ok": False, "error": str(e)}), 409
    return jsonify({"ok": True})


@app.route("/api/repair", methods=["POST"])
def api_repair():
    """Répare visages/mains d'une image existante (mode -M adetailer, ADetailer)."""
    data = request.get_json(force=True)
    did = (data.get("detector_id") or "").strip()
    if did and did not in ADETAILERS:
        return jsonify({"ok": False, "error": "Détecteur ADetailer inconnu."}), 400
    if not did:
        did = next((k for k in ADETAILERS if adetailer_status(k)["downloaded"]), None)
        if not did:
            return jsonify({"ok": False, "error": (
                "Aucun détecteur ADetailer n'est installé. Téléchargez-en un dans "
                "l'onglet Modèles, section « 🙂 ADetailer » (quelques Mo)."
            )}), 400
    elif not adetailer_status(did)["downloaded"]:
        return jsonify({"ok": False, "error": (
            f"« {ADETAILERS[did]['name']} » n'est pas installé. Téléchargez-le dans "
            "l'onglet Modèles, section « 🙂 ADetailer »."
        )}), 400

    src_rel, err = _resolve_source_image(data)
    if err:
        return err

    params = {
        "task_kind": "repair",
        "detector_id": did,
        "source_image": src_rel,
        "model_id": (data.get("model_id") or "").strip(),
        "quant": (data.get("quant") or "").strip(),
        "prompt": (data.get("prompt") or "").strip(),
        "ad_prompt": (data.get("ad_prompt") or "").strip(),
        "seed": data.get("seed"),
        "taesd_id": (data.get("taesd_id") or "").strip(),
        "sage_attn": bool(data.get("sage_attn")),
    }
    strength = data.get("strength")
    try:
        if strength is not None:
            strength = max(0.1, min(1.0, float(strength)))
    except (TypeError, ValueError):
        strength = None
    params["strength"] = strength
    try:
        q_info = tasks.enqueue_generate(params)
        return jsonify({"ok": True, "detector_id": did, **q_info})
    except RuntimeError as e:
        return jsonify({"ok": False, "error": str(e)}), 409


@app.route("/api/restore-x2", methods=["POST"])
def api_restore_x2():
    """Restauration ×2 par diffusion (SeedVR2, mode -M vid_upscale, ~6,8 Go)."""
    data = request.get_json(force=True)
    st = seedvr2_status()
    if not st["downloaded"]:
        return jsonify({"ok": False, "error": (
            "SeedVR2 n'est pas installé. Téléchargez-le dans l'onglet Modèles, "
            "section « 🩹 Restauration ×2 » (~6,8 Go)."
        )}), 400
    src_rel, err = _resolve_source_image(data)
    if err:
        return err
    params = {
        "task_kind": "restore_x2",
        "source_image": src_rel,
        "seed": data.get("seed"),
    }
    try:
        q_info = tasks.enqueue_generate(params)
        return jsonify({"ok": True, **q_info})
    except RuntimeError as e:
        return jsonify({"ok": False, "error": str(e)}), 409


@app.route("/api/pid-upscale", methods=["POST"])
def api_pid_upscale():
    """Super-résolution générative ×4 PiD (NVIDIA Pixel Diffusion, 1024→4096).

    Le backbone est choisi automatiquement : famille du modèle source (FLUX.1 /
    FLUX.2 / Qwen-Image) si elle est installée, sinon premier backbone prêt.
    Le prompt reprend celui de l'image source (historique) si non fourni."""
    data = request.get_json(force=True)
    st = pid_status()
    if not st["downloaded"]:
        return jsonify({"ok": False, "error": (
            "PiD n'est pas installé. Téléchargez-le dans l'onglet Modèles, "
            "section « ⬆️ PiD ×4 » (socle ~5,4 Go + ~1,6 Go par backbone)."
        )}), 400
    backbone = (data.get("backbone") or "").strip()
    if backbone and backbone not in PID["backbones"]:
        return jsonify({"ok": False, "error": f"Backbone PiD inconnu : {backbone}"}), 400
    if backbone and not st["backbones"][backbone]["ready"]:
        return jsonify({"ok": False, "error": (
            f"PiD ({backbone}) n'est pas complet. Finalisez l'installation dans "
            "l'onglet Modèles, section « ⬆️ PiD ×4 »."
        )}), 400
    src_rel, err = _resolve_source_image(data)
    if err:
        return err
    params = {
        "task_kind": "pid",
        "source_image": src_rel,
        "image_id": data.get("image_id"),
        "backbone": backbone,
        "prompt": (data.get("prompt") or "").strip(),
        "seed": data.get("seed"),
    }
    try:
        q_info = tasks.enqueue_generate(params)
        return jsonify({"ok": True, **q_info})
    except RuntimeError as e:
        return jsonify({"ok": False, "error": str(e)}), 409


@app.route("/api/image-meta", methods=["POST"])
def api_image_meta():
    """Lit le chunk « parameters » d'un PNG déposé (drag-drop) : retourne les
    réglages (prompt, seed, modèle…) pour les ré-appliquer au formulaire."""
    f = request.files.get("image")
    if f and f.filename:
        raw = f.read(64 * 1024 * 1024)  # 64 Mo max, large pour un PNG 4K retouché
        import io
        params = _pngmeta.read_params(io.BytesIO(raw))
    else:
        data = request.get_json(silent=True) or {}
        path = str(data.get("path") or "").strip()
        if not path:
            return jsonify({"ok": False, "error": "Aucun fichier fourni."}), 400
        p = Path(path)
        if not p.is_absolute():
            p = (config.ROOT / path).resolve()
        try:
            p.relative_to(config.ROOT.resolve())
        except Exception:
            return jsonify({"ok": False, "error": "Chemin invalide."}), 400
        if not p.exists():
            return jsonify({"ok": False, "error": "Fichier introuvable."}), 404
        params = _pngmeta.read_params(p)
    if not params:
        return jsonify({"ok": False, "error": (
            "Aucune métadonnée lisible dans cette image. Seuls les PNG tagués par "
            "Local Image Studio (ou par sd-cli) sont supportés pour la restauration des réglages."
        )}), 422
    form = _pngmeta.to_form_settings(params, MODELS)
    return jsonify({"ok": True, "params": params, "form": form})


@app.route("/api/batch", methods=["POST"])
def api_batch():
    """Génère N variantes d'un même réglage, une par ligne de prompt (une par job)."""
    data = request.get_json(force=True)
    lines = [l.strip() for l in str(data.get("prompts") or "").splitlines()]
    lines = [l for l in lines if l]
    if not lines:
        return jsonify({"ok": False, "error": "Aucun prompt fourni (une ligne par image)."}), 400
    if len(lines) > 16:
        return jsonify({"ok": False, "error": "Maximum 16 prompts par lot."}), 400
    mid = data.get("model_id")
    if mid not in MODELS:
        return jsonify({"ok": False, "error": "Modèle inconnu"}), 400

    # Réutilise la validation complète de /api/generate en injectant chaque prompt
    base = dict(data)
    base.pop("prompts", None)
    queued, errors = [], []
    for line in lines:
        payload = dict(base)
        payload["prompt"] = line
        payload["allow_queue"] = True
        # Appel interne : on rejoue la logique de api_generate via un mini-client
        with app.test_request_context("/api/generate", method="POST", json=payload):
            resp = api_generate()
        body = None
        try:
            if isinstance(resp, tuple):
                maybe_json = resp[0]
                body = maybe_json.get_json(silent=True) if hasattr(maybe_json, "get_json") else None
            elif hasattr(resp, "get_json"):
                body = resp.get_json(silent=True)
        except Exception:
            body = None
        if body and body.get("ok"):
            queued.append(line)
        else:
            msg = (body or {}).get("error", "échec inconnu")
            errors.append({"prompt": line[:80], "error": msg})
    return jsonify({"ok": bool(queued), "queued": len(queued), "errors": errors})


@app.route("/api/pulid-extract", methods=["POST"])
def api_pulid_extract():
    """Extrait l'empreinte d'identité d'un portrait via l'extracteur externe
    (script Python livré dans scripts/pulid_extract_id.py — pile PyTorch requise)."""
    data = request.get_json(force=True)
    portrait_rel = (data.get("portrait") or "").strip()
    name = (data.get("name") or "").strip()
    if not portrait_rel:
        return jsonify({"ok": False, "error": "Aucun portrait fourni."}), 400
    p = (config.SOURCE_IMAGES_DIR / Path(portrait_rel).name).resolve()
    if not p.exists():
        # Tolère un chemin absolu/relatif dans le dépôt (comme /api/use-output-as-source)
        cand = (config.ROOT / portrait_rel).resolve()
        try:
            cand.relative_to(config.ROOT.resolve())
            if cand.exists():
                p = cand
        except Exception:
            pass
    if not p.exists():
        return jsonify({"ok": False, "error": "Portrait introuvable sur le disque."}), 404
    base = re.sub(r"[^a-zA-Z0-9_\-]", "_", name)[:60].strip("_")
    if not base:
        base = re.sub(r"[^a-zA-Z0-9_\-]", "_", p.stem)[:60] or "portrait"
    out = config.PORTRAITS_DIR / f"{base}.pulidembd"
    script = config.ROOT / "scripts" / "pulid_extract_id.py"
    py = shutil.which("python3") or shutil.which("python") or sys.executable
    # Les poids PuLID sont requis par l'extracteur amont : explicites-le.
    wpath = pulid_weights_path()
    if not wpath.exists():
        return jsonify({"ok": False, "error": (
            "Les poids PuLID-FLUX sont requis pour l'extraction (~1,14 Go). "
            "Téléchargez-les d'abord dans l'onglet Modèles → « 🎭 Visage fidèle (PuLID) »."
        )}), 400
    cmd = [py, str(script), "--portrait", str(p), "--out", str(out),
           "--pulid-weights", str(wpath)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    except FileNotFoundError:
        return jsonify({"ok": False, "error": "Python introuvable pour l'extracteur."}), 500
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "error": "L'extraction a dépassé le temps imparti (15 min)."}), 500
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        detail = "\n".join(detail[-12:])
        return jsonify({"ok": False, "error": (
            "L'extracteur d'identité a échoué (la pile PyTorch est-elle installée ? "
            "voir scripts/pulid_extract_id.py) :\n" + detail
        )}), 500
    out_rel = str(Path("portraits") / out.name)
    return jsonify({"ok": True, "embedding": out.name, "path": out_rel,
                    "size_bytes": out.stat().st_size if out.exists() else 0})


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

    # --- Outpainting (extension de cadre pour les modeles compatibles) ---
    outpaint_cfg = data.get("outpaint")
    prompt_str = (data.get("prompt") or "").strip()
    if outpaint_cfg:
        if not supports_outpainting(mid):
            return jsonify({
                "ok": False,
                "error": f"{m['name']} ne supporte pas l'outpainting. "
                         "Choisissez Qwen-Image 2.1, FLUX.2 / FLUX.3 Klein ou Fibo 2.0."
            }), 400
        if not images:
            return jsonify({
                "ok": False,
                "error": "L'outpainting nécessite une image de départ (canvas)."
            }), 400
        directions = None
        auto_prompt = True
        if isinstance(outpaint_cfg, dict):
            directions = outpaint_cfg.get("directions")
            if "auto_prompt" in outpaint_cfg:
                auto_prompt = bool(outpaint_cfg.get("auto_prompt"))
        if auto_prompt or not prompt_str:
            prompt_str = build_outpaint_prompt(mid, prompt_str, directions)

    # --- Inpainting au pinceau (retouche locale sur zone peinte) ---
    inpaint_cfg = data.get("inpaint")
    mask_rel_path = None
    if inpaint_cfg and not outpaint_cfg:
        if not supports_inpainting(mid):
            return jsonify({
                "ok": False,
                "error": f"{m['name']} ne supporte pas le mode Inpainting."
            }), 400
        if not images:
            return jsonify({
                "ok": False,
                "error": "L'inpainting nécessite une image de départ (canvas)."
            }), 400
        bbox = None
        auto_inpaint_prompt = True
        if isinstance(inpaint_cfg, dict):
            bbox = inpaint_cfg.get("bbox")
            if "auto_prompt" in inpaint_cfg:
                auto_inpaint_prompt = bool(inpaint_cfg.get("auto_prompt"))
            raw_mask = inpaint_cfg.get("mask_image")
            if raw_mask and inpaint_cfg.get("use_cli_mask"):
                valid_masks = _existing_sources([raw_mask])
                if valid_masks:
                    mask_rel_path = valid_masks[0]
        if auto_inpaint_prompt or not prompt_str:
            prompt_str = build_inpaint_prompt(mid, prompt_str, bbox=bbox)

    params = {
        "model_id": mid,
        "quant": quant,
        "prompt": prompt_str,
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
        "outpaint": bool(outpaint_cfg),
        "inpaint": bool(inpaint_cfg),
        "mask_image": mask_rel_path,
    }

    # --- Options Qualité / Détails / Upscaling (validées côté serveur) ---
    valid_samplers = {s["id"] for s in SAMPLERS_INFO} | {m["defaults"]["sampler"] for m in MODELS.values()}
    valid_schedulers = {s["id"] for s in SCHEDULERS_INFO}
    sampler = (data.get("sampler") or "default").strip()
    if sampler not in valid_samplers:
        return jsonify({"ok": False, "error": f"Échantillonneur inconnu : {sampler}"}), 400
    scheduler = (data.get("scheduler") or "default").strip()
    if scheduler not in valid_schedulers:
        return jsonify({"ok": False, "error": f"Planificateur inconnu : {scheduler}"}), 400
    params["sampler"] = sampler
    params["scheduler"] = scheduler
    params["vae_tiling"] = bool(data.get("vae_tiling"))
    slg = data.get("slg_scale")
    if slg in ("", None):
        slg = None
    else:
        try:
            slg = float(slg)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "Valeur SLG invalide."}), 400
        slg = max(0.0, min(5.0, slg)) or None
    params["slg_scale"] = slg

    upscale_id = (data.get("upscale_id") or "").strip() or None
    if upscale_id:
        if upscale_id not in UPSCALERS:
            return jsonify({"ok": False, "error": "Modèle d'agrandissement inconnu."}), 400
        if not upscaler_status(upscale_id)["downloaded"]:
            return jsonify({"ok": False, "error": (
                f"« {UPSCALERS[upscale_id]['name']} » n'est pas installé. Téléchargez-le "
                "dans l'onglet Modèles (section « 🔍 Upscaling ×4 »)."
            )}), 400
    params["upscale_id"] = upscale_id

    adetailer_id = (data.get("adetailer_id") or "").strip() or None
    if adetailer_id:
        if adetailer_id not in ADETAILERS:
            return jsonify({"ok": False, "error": "Détecteur ADetailer inconnu."}), 400
        if not adetailer_status(adetailer_id)["downloaded"]:
            return jsonify({"ok": False, "error": (
                f"Le détecteur « {ADETAILERS[adetailer_id]['name']} » n'est pas installé. "
                "Téléchargez-le dans l'onglet Modèles (section « 🙂 ADetailer »)."
            )}), 400
    params["adetailer_id"] = adetailer_id

    # --- Options Performance : mini-VAE TAE, SageAttention, Aperçu direct, PuLID ---
    taesd_id = (data.get("taesd_id") or "").strip()
    if taesd_id and taesd_id != "auto":
        if taesd_id not in TAESD:
            return jsonify({"ok": False, "error": "Mini-VAE TAE inconnu."}), 400
        if not taesd_status(taesd_id)["downloaded"]:
            t = TAESD[taesd_id]
            return jsonify({"ok": False, "error": (
                f"« {t['name']} » n'est pas installé. Téléchargez-le "
                "dans l'onglet Modèles (section « ⚡ VAE rapide »)."
            )}), 400
    if taesd_id == "auto":
        auto_ta = taesd_for_model(mid)
        if auto_ta and taesd_status(auto_ta)["downloaded"]:
            taesd_id = auto_ta
        else:
            taesd_id = ""   # auto mais pas encore installé → on génère sans TAE
    params["taesd_id"] = taesd_id or ""
    params["sage_attn"] = bool(data.get("sage_attn"))

    preview = (data.get("preview") or "none").strip()
    if preview not in ("none", "proj", "tae", "vae"):
        return jsonify({"ok": False, "error": "Méthode d'aperçu inconnue."}), 400
    params["preview"] = preview
    try:
        params["preview_interval"] = max(1, min(10, int(data.get("preview_interval") or 3)))
    except (TypeError, ValueError):
        params["preview_interval"] = 3

    pulid_id = (data.get("pulid_id") or "").strip()
    if pulid_id:
        if not supports_pulid(mid):
            return jsonify({"ok": False, "error": (
                f"{m['name']} ne prend pas en charge PuLID. Choisissez FLUX.1 Schnell, "
                "FLUX.1 Dev ou FLUX.1 FHDR."
            )}), 400
        try:
            w = float(data.get("pulid_id_weight"))
        except (TypeError, ValueError):
            w = PULID["default_weight"]
        params["pulid_id"] = pulid_id
        params["pulid_id_weight"] = max(PULID["min_weight"], min(PULID["max_weight"], w))
    else:
        params["pulid_id"] = ""
        params["pulid_id_weight"] = PULID["default_weight"]

    # Hires Fix (2 passes) : uniquement en génération pure (jamais avec une image de départ)
    params["hires_fix"] = bool(data.get("hires_fix")) and not images and not mask_rel_path
    try:
        params["hires_strength"] = float(data.get("hires_strength") or 0.35)
    except (TypeError, ValueError):
        params["hires_strength"] = 0.35
    params["hires_strength"] = max(0.1, min(0.8, params["hires_strength"]))

    if not params["prompt"]:
        return jsonify({"ok": False, "error": "Le prompt est vide."}), 400
    allow_queue = bool(data.get("allow_queue", True))
    try:
        if allow_queue:
            q_info = tasks.enqueue_generate(params)
            return jsonify({"ok": True, "params": params, **q_info})
        else:
            tasks.start_generate(params)
            return jsonify({"ok": True, "params": params, "queued": False, "started": True})
    except RuntimeError as e:
        return jsonify({"ok": False, "error": str(e)}), 409


@app.route("/api/queue", methods=["GET"])
def api_queue_list():
    q = tasks.list_queue()
    return jsonify({"ok": True, "queue": q, "queue_size": len(q)})


@app.route("/api/queue/remove", methods=["POST"])
def api_queue_remove():
    data = request.get_json(silent=True) or {}
    qid = str(data.get("queue_id") or "").strip()
    if not qid:
        return jsonify({"ok": False, "error": "Identifiant de file manquant."}), 400
    removed = tasks.remove_from_queue(qid)
    q = tasks.list_queue()
    return jsonify({"ok": True, "removed": removed, "queue": q, "queue_size": len(q)})


@app.route("/api/queue/clear", methods=["POST"])
def api_queue_clear():
    cleared = tasks.clear_queue()
    return jsonify({"ok": True, "cleared": cleared, "queue": [], "queue_size": 0})


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
#  API : historique & favoris
# --------------------------------------------------------------------------- #
@app.route("/api/toggle-favorite", methods=["POST"])
def api_toggle_favorite():
    data = request.get_json(silent=True) or {}
    img_id = data.get("id")
    if img_id is None:
        return jsonify({"ok": False, "error": "Identifiant d'image manquant."}), 400
    val = data.get("favorite") if "favorite" in data else None
    new_state = db.toggle_favorite(int(img_id), value=val)
    if new_state is None:
        return jsonify({"ok": False, "error": "Image introuvable."}), 404
    return jsonify({"ok": True, "id": int(img_id), "favorite": new_state})


@app.route("/api/delete-image", methods=["POST"])
def api_delete_image():
    data = request.get_json(force=True)
    img_id = data.get("id")
    force = bool(data.get("force", False))
    try:
        fname = db.delete_image(img_id, force=force)
    except PermissionError as e:
        return jsonify({"ok": False, "protected": True, "error": str(e)}), 400
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
        patch = {"hf_token": (data.get("hf_token") or "").strip()}
        # Case « ouvrir le navigateur au démarrage » (Paramètres)
        if "open_browser" in data:
            patch["open_browser"] = bool(data.get("open_browser"))
        save_settings(patch)
        return jsonify({"ok": True, "token_set": bool(hf_token()),
                        "open_browser": bool(load_settings().get("open_browser", True))})
    return jsonify({"hf_token": hf_token(),
                    "open_browser": bool(load_settings().get("open_browser", True))})



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
    rel = _source_rel_path(target)
    # Les sources d'une génération en cours, en file d'attente ou enregistrée ne sont pas temporaires.
    if (tasks.is_busy() and tasks.snapshot().get("kind") == "generate") \
            or (rel in tasks.queued_source_paths()) \
            or db.source_is_referenced(rel):
        return jsonify({"ok": True, "deleted": False, "retained": True})
    existed = target.exists()
    if existed:
        try:
            target.unlink()
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": True, "deleted": existed})


@app.route("/api/use-output-as-source", methods=["POST"])
def api_use_output_as_source():
    """
    Copie une image générée (depuis output/) vers source_images/ pour pouvoir
    l'utiliser comme image source (canvas ou référence) dans le Studio d'édition
    ou en img2img, sans dépendre de la durée de vie de l'entrée d'historique.
    """
    import shutil
    data = request.get_json(silent=True) or {}
    rel_out = str(data.get("filename") or "").strip()
    if not rel_out and data.get("id") is not None:
        try:
            row = db.get_image(int(data["id"]))
        except (TypeError, ValueError):
            row = None
        if row:
            rel_out = row.get("filename") or ""
    if not rel_out:
        return jsonify({"ok": False, "error": "Aucune image indiquée."}), 400

    candidate = config.OUTPUT_DIR / rel_out
    try:
        resolved = candidate.resolve()
        resolved.relative_to(config.OUTPUT_DIR.resolve())
    except Exception:
        return jsonify({"ok": False, "error": "Chemin d'image refusé."}), 400

    if not resolved.exists() or not resolved.is_file():
        return jsonify({"ok": False, "error": "Fichier image introuvable dans output/."}), 404

    ext = resolved.suffix.lower()
    if ext not in IMAGE_EXTS:
        ext = ".png"
    unique_name = f"{uuid.uuid4().hex[:12]}{ext}"
    config.SOURCE_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    dest = config.SOURCE_IMAGES_DIR / unique_name
    shutil.copy2(str(resolved), str(dest))
    rel = _source_rel_path(dest)
    return jsonify({
        "ok": True,
        "filename": rel,
        "url": _source_url(rel),
        "name": resolved.name,
    })


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


@app.route("/api/quant-recommendation")
def api_quant_recommendation():
    """Quant recommandé par modèle pour la VRAM détectée (ou passée en paramètre)."""
    raw = request.args.get("vram_gb")
    if raw:
        try:
            vram_gb = float(raw)
        except ValueError:
            vram_gb = 0
    else:
        vram_mb, _n = gpu_info.get_gpu_info()
        vram_gb = round(vram_mb / 1024, 1) if vram_mb else 0
    model = (request.args.get("model_id") or "").strip()
    if model:
        if model not in MODELS:
            return jsonify({"ok": False, "error": "Modèle inconnu"}), 400
        return jsonify({"ok": True, "vram_gb": vram_gb,
                        "model_id": model,
                        "quant": recommended_quant(model, vram_gb)})
    return jsonify({"ok": True, "vram_gb": vram_gb,
                    "recommendations": quant_recommendations(vram_gb)})


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


def _parse_args(argv=None):
    """Options de démarrage (le navigateur s'ouvre par défaut : cf. browser_launch.py)."""
    parser = argparse.ArgumentParser(
        prog="app.py",
        description="Local Image Studio — interface web locale pour stable-diffusion.cpp",
    )
    parser.add_argument("--no-browser", action="store_true",
                        help="ne pas ouvrir le navigateur au démarrage")
    parser.add_argument("--port", type=int, default=7860,
                        help="port d'écoute (défaut : 7860)")
    return parser.parse_args(argv)


def _should_open_browser(args) -> bool:
    """Priorité : option --no-browser > variable LIS_NO_BROWSER > réglage enregistré."""
    if args.no_browser or browser_launch.browser_disabled():
        return False
    return bool(load_settings().get("open_browser", True))


if __name__ == "__main__":
    _args = _parse_args()
    port = _args.port
    url = f"http://127.0.0.1:{port}"
    print(f"\n  ➜  Local Image Studio : http://0.0.0.0:{port}\n")

    opened = {"done": False}

    def _report(result):
        opened["done"] = True
        if result == "chrome":
            msg = f"Ouverture dans Google Chrome : {url}"
        elif result == "default":
            msg = f"Chrome introuvable : ouverture dans le navigateur par défaut : {url}"
        elif result == "headless":
            msg = f"Pas d'écran détecté : ouvrez {url} manuellement."
        else:
            msg = f"Navigateur non ouvert : allez sur {url}"
        print(f"  ➜  {msg}", flush=True)

    if _should_open_browser(_args):
        # L'ouverture attend que le port écoute, dans un thread : Flask démarre tout de suite.
        browser_launch.schedule_open(url, port=port, on_done=_report)
    else:
        print(f"  ➜  Ouverture automatique du navigateur désactivée — allez sur {url}", flush=True)

    # use_reloader=False : évite de relancer deux fois les téléchargements/threads
    # (et d'ouvrir deux onglets).
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
