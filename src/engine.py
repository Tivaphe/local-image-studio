# -*- coding: utf-8 -*-
"""
Moteur d'exécution :
  - téléchargement de l'exécutable stable-diffusion.cpp (sd-cli)
  - téléchargement des modèles GGUF et de leurs dépendances (huggingface_hub)
  - lancement d'une génération (subprocess) + analyse de la progression
  - gestion asynchrone des tâches (téléchargements / générations)
"""
import io
import json
import os
import re
import shutil
import subprocess
import threading
import time
import zipfile
import uuid
from pathlib import Path
from urllib.request import urlopen, Request

from config import (ROOT, BIN_DIR, DIFFUSION_DIR, OUTPUT_DIR, UPSCALE_DIR,
                    ADETAILER_DIR, SEEDVR2_DIR, TAESD_DIR, PREVIEW_DIR, PID_DIR,
                    find_sd_cli)
from registry import (MODELS, DEPS, DEP_QUANT_PRIORITY, resolve_dep_gguf,
                      load_manifest, save_manifest, build_command, _dep_path,
                      check_images_input, UPSCALERS, ADETAILERS,
                      upscaler_path, adetailer_path, build_upscale_command,
                      build_adetailer_command, build_seedvr2_command,
                      SEEDVR2, seedvr2_paths, seedvr2_status,
                      TAESD, taesd_path, taesd_status, taesd_for_model,
                      PULID, pulid_weights_path, pulid_status,
                      portrait_embedding, supports_pulid, round16,
                      PID, pid_status, pid_gemma_path, pid_tokenizer_path,
                      pid_model_path, pid_vae_path, pid_backbone_for_arch,
                      pid_default_prompt, build_pid_command)
import metadata as _pngmeta


# =========================================================================== #
#  Réglages (token HF pour les dépôts gated comme FHDR)
# =========================================================================== #
_SETTINGS = {}
_SETTINGS_LOCK = threading.Lock()
_SETTINGS_PATH = ROOT / "settings.json"


def load_settings():
    global _SETTINGS
    with _SETTINGS_LOCK:
        if not _SETTINGS:
            if _SETTINGS_PATH.exists():
                try:
                    _SETTINGS = json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
                except Exception:
                    _SETTINGS = {}
            _SETTINGS.setdefault("hf_token", "")
            # Ouvrir le navigateur au démarrage du serveur (case dans Paramètres)
            _SETTINGS.setdefault("open_browser", True)
            # --- Performance & Apercu (valeurs par defaut) ---
            # sage_attn : acceleration CUDA SageAttention (ignoree si non supportee)
            _SETTINGS.setdefault("sage_attn", False)
            # preview : méthode d'apercu live ("none"|"proj"|"tae"|"vae")
            _SETTINGS.setdefault("preview", "none")
            # preview_interval : une image d'apercu toutes les N etapes
            _SETTINGS.setdefault("preview_interval", 3)
        return _SETTINGS


def save_settings(d):
    with _SETTINGS_LOCK:
        _SETTINGS.update(d)
        _SETTINGS_PATH.write_text(json.dumps(_SETTINGS, indent=2, ensure_ascii=False),
                                  encoding="utf-8")


def hf_token():
    return load_settings().get("hf_token", "").strip()


# =========================================================================== #
#  Téléchargement de l'exécutable sd-cli (stable-diffusion.cpp)
# =========================================================================== #
SDCPP_REPO_API = "https://api.github.com/repos/leejet/stable-diffusion.cpp/releases/latest"
# Binaire principal (Windows CUDA 12) + runtime CUDA (cudart) fourni à part.
BINARY_ASSET_END = "-bin-win-cuda12-x64.zip"
CUDART_ASSET_START = "cudart-sd-bin-win-cu12-x64.zip"


def _gh_get(url):
    req = Request(url, headers={"Accept": "application/vnd.github+json",
                                "User-Agent": "local-image-studio"})
    return json.loads(urlopen(req, timeout=30).read())


def latest_sdcli_assets():
    """Renvoie (binary_url, cudart_url) pour la dernière release Windows CUDA."""
    data = _gh_get(SDCPP_REPO_API)
    binary_url = cudart_url = None
    for a in data.get("assets", []):
        name = a.get("name", "")
        if name.endswith(BINARY_ASSET_END):
            binary_url = a.get("browser_download_url")
        elif name == CUDART_ASSET_START or (name.startswith("cudart") and name.endswith(".zip")):
            cudart_url = a.get("browser_download_url")
    # fallback CPU si pas de build CUDA
    if not binary_url:
        for a in data.get("assets", []):
            if a.get("name", "").endswith("-bin-win-avx2-x64.zip"):
                binary_url = a.get("browser_download_url")
    return binary_url, cudart_url


def _download(url, dest: Path, progress_cb=None):
    """Télécharge un fichier avec suivi de progression (callback(done, total))."""
    req = Request(url, headers={"User-Agent": "local-image-studio"})
    with urlopen(req, timeout=60) as r:
        total = int(r.headers.get("Content-Length", 0))
        done = 0
        chunk = 1 << 20  # 1 Mo
        tmp = dest.with_suffix(dest.suffix + ".part")
        with open(tmp, "wb") as f:
            while True:
                buf = r.read(chunk)
                if not buf:
                    break
                f.write(buf)
                done += len(buf)
                if progress_cb:
                    progress_cb(done, total)
        tmp.replace(dest)


def install_engine(progress_cb=None):
    """Télécharge et extrait sd-cli (binaire + runtime CUDA) dans bin/."""
    binary_url, cudart_url = latest_sdcli_assets()
    if not binary_url:
        raise RuntimeError("Impossible de trouver le binaire sd-cli Windows CUDA.")

    def _dl_asset(url, label):
        name = url.rsplit("/", 1)[-1]
        dest = BIN_DIR / name
        if progress_cb:
            progress_cb(0, 1)
        if progress_cb:
            progress_cb(0, 0)  # signal « démarrage »
        _download(url, dest, progress_cb)
        with zipfile.ZipFile(dest) as z:
            z.extractall(BIN_DIR)
        dest.unlink(missing_ok=True)
        if progress_cb:
            progress_cb(1, 1)

    # 1) runtime CUDA (cudart/cublas) — requis au démarrage de sd-cli.exe
    if cudart_url:
        if progress_cb:
            progress_cb(0, 0)
        _dl_asset(cudart_url, "cudart")
    # 2) binaire sd-cli
    _dl_asset(binary_url, "binary")
    return find_sd_cli()


def engine_ready() -> bool:
    return find_sd_cli() is not None


# =========================================================================== #
#  Téléchargement des modèles + dépendances (huggingface_hub)
# =========================================================================== #
def _import_hf():
    try:
        from huggingface_hub import hf_hub_download, list_repo_files
        return hf_hub_download, list_repo_files
    except ImportError as e:
        raise RuntimeError("huggingface_hub n'est pas installé. Lancez: pip install huggingface_hub") from e


def _hf_download_file(repo, filename, dest: Path, token, msg_cb=None):
    hf_hub_download, _ = _import_hf()
    if msg_cb:
        msg_cb(f"Téléchargement de {filename} ({repo})")
    # téléchargement dans un dossier tampon puis déplacement (aplatit les sous-dossiers)
    staging = dest.parent / ".staging"
    staging.mkdir(parents=True, exist_ok=True)
    cached = hf_hub_download(repo_id=repo, filename=filename,
                             local_dir=str(staging), token=(token or None))
    shutil.move(cached, dest)
    # nettoyage du dossier tampon
    try:
        shutil.rmtree(staging, ignore_errors=True)
    except Exception:
        pass


def _png_size(path: Path):
    """Lit rapidement les dimensions (largeur, hauteur) d'un PNG via son en-tête IHDR."""
    try:
        with open(path, "rb") as f:
            head = f.read(26)
        if head[:8] == b"\x89PNG\r\n\x1a\n" and head[12:16] == b"IHDR":
            w = int.from_bytes(head[16:20], "big")
            h = int.from_bytes(head[20:24], "big")
            return w, h
    except Exception:
        pass
    return None


def _model_present(model_id, quant) -> bool:
    m = MODELS[model_id]
    ok = (DIFFUSION_DIR / m["file_for_quant"][quant]).exists()
    if "uncond_file_for_quant" in m:
        ok = ok and (DIFFUSION_DIR / m["uncond_file_for_quant"][quant]).exists()
    return ok


def _dep_present(dep_id) -> bool:
    """Une dépendance est présente si elle est dans le manifeste ET le fichier existe, ou si présente à l'emplacement standard."""
    mf = load_manifest()
    p = _dep_path(mf, dep_id)
    return bool(p and Path(p).exists())


def model_status(model_id):
    """Renvoie l'état (quant dispo, téléchargées, deps manquantes)."""
    m = MODELS[model_id]
    quants_ok = {}
    for q in m["quants"]:
        quants_ok[q] = _model_present(model_id, q)
    deps_ok = {d: _dep_present(d) for d in m["deps"]}
    ready = any(quants_ok.values()) and all(deps_ok.values())
    return {
        "quants": quants_ok,
        "deps": deps_ok,
        "ready": ready,
    }


def ensure_dep(dep_id, token, msg_cb=None):
    """Télécharge une dépendance partagée si absente, met à jour le manifeste."""
    if _dep_present(dep_id):
        return
    dep = DEPS[dep_id]
    manifest = load_manifest()
    if dep["type"] == "exact":
        dest = dep["dest"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        _hf_download_file(dep["repo"], dep["filename"], dest, token, msg_cb)
        manifest[dep_id] = {"repo": dep["repo"], "filename": dep["filename"],
                            "path": str(dest)}
    else:  # gguf
        _, list_repo_files = _import_hf()
        files = list_repo_files(dep["repo"], token=(token or None))
        fname = resolve_dep_gguf(dep_id, files)
        if not fname:
            raise RuntimeError(f"Aucun GGUF trouvé pour {dep['repo']}")
        dest = dep["dest_dir"] / fname
        dest.parent.mkdir(parents=True, exist_ok=True)
        _hf_download_file(dep["repo"], fname, dest, token, msg_cb)
        manifest[dep_id] = {"repo": dep["repo"], "filename": fname,
                            "path": str(dest)}
    save_manifest(manifest)


def download_upscaler(upscaler_id, msg_cb=None, progress_cb=None):
    """Télécharge un modèle d'agrandissement ESRGAN/MoSR (URL directe, ~17-64 Mo)."""
    u = UPSCALERS[upscaler_id]
    dest = UPSCALE_DIR / u["filename"]
    if dest.exists() and dest.stat().st_size > 1024 * 100:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    if msg_cb:
        msg_cb(f"Téléchargement de {u['name']} (~{u['size_mb']} Mo)…")
    _download(u["url"], dest, progress_cb)


def download_adetailer(detector_id, token, msg_cb=None):
    """Télécharge un détecteur ADetailer YOLOv8 (safetensors) depuis Hugging Face."""
    d = ADETAILERS[detector_id]
    dest = ADETAILER_DIR / d["filename"]
    if dest.exists() and dest.stat().st_size > 16 * 1024:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    if msg_cb:
        msg_cb(f"Téléchargement du détecteur {d['name']} (~{d['size_mb']} Mo)…")
    _hf_download_file(d["repo"], d["filename"], dest, token, msg_cb)


def download_seedvr2(token, msg_cb=None):
    """Télécharge les deux poids SeedVR2 (diffusion int8 + VAE fp16)."""
    for key in ("diffusion", "vae"):
        info = SEEDVR2["files"][key]
        dest = SEEDVR2_DIR / info["filename"]
        if dest.exists() and dest.stat().st_size > 1024 * 1024:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        if msg_cb:
            msg_cb(f"Téléchargement SeedVR2 — {info['filename']} (~{info['size_mb']} Mo)…")
        _hf_download_file(SEEDVR2["repo"], info["filename"], dest, token, msg_cb)


def download_pid(backbone, token, msg_cb=None):
    """Télécharge le nécessaire pour PiD (une fois) : socle commun Gemma 2 2B
    (encodeur bf16 + tokenizer non-gated) puis le modèle int8 du backbone choisi
    + son VAE (réutilise le dépôt déjà utilisé par les modèles de la famille)."""
    if backbone not in PID["backbones"]:
        raise ValueError(f"Backbone PiD inconnu : {backbone}")
    PID_DIR.mkdir(parents=True, exist_ok=True)

    # 1) Socle commun (une seule fois, partagé par les 3 backbones)
    gemma = PID["gemma"]
    gemma_dest = pid_gemma_path()
    if not (gemma_dest.exists() and gemma_dest.stat().st_size > 1024 * 1024 * 1024):
        if msg_cb:
            msg_cb(f"Téléchargement PiD — encodeur Gemma 2 2B bf16 (~{gemma['size_mb']} Mo, ~5 Go)…")
        _hf_download_file(gemma["repo"], gemma["filename"], gemma_dest, token, msg_cb)

    tok = PID["tokenizer"]
    tok_dest = pid_tokenizer_path()
    if not (tok_dest.exists() and tok_dest.stat().st_size > 1024 * 1024):
        if msg_cb:
            msg_cb(f"Téléchargement PiD — tokenizer Gemma 2 (miroir non-gated {tok['repo']}, ~{tok['size_mb']} Mo)…")
        _hf_download_file(tok["repo"], tok["filename"], tok_dest, token, msg_cb)

    # 2) Modèle PiD 1.5 du backbone (int8_convrot, 1024→4096, 4 étapes)
    bb = PID["backbones"][backbone]
    model_dest = pid_model_path(backbone)
    if not (model_dest.exists() and model_dest.stat().st_size > 512 * 1024 * 1024):
        if msg_cb:
            msg_cb(f"Téléchargement PiD — {bb['filename']} (~{bb['size_mb']} Mo)…")
        _hf_download_file(PID["repo"], bb["repo_filename"], model_dest, token, msg_cb)

    # 3) VAE du backbone (réutilise DEPS ; best effort : souvent déjà installé)
    try:
        ensure_dep(bb["vae_dep"], token, msg_cb)
    except Exception as e:
        if msg_cb:
            msg_cb(f"⚠️ VAE « {bb['vae_dep']} » non téléchargé ({e}). "
                   "Installez d'abord le modèle correspondant dans l'onglet Modèles.")


def download_taesd(ta_id, token, msg_cb=None):
    """Télécharge un mini-VAE TAE (~2 Mo) depuis Hugging Face."""
    t = TAESD[ta_id]
    dest = TAESD_DIR / t["filename"]
    if dest.exists() and dest.stat().st_size > 50 * 1024:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    if msg_cb:
        msg_cb(f"Téléchargement du mini-VAE {t['name']} (~{t['size_mb']} Mo)…")
    _hf_download_file(t["repo"], t.get("repo_filename", t["filename"]), dest, token, msg_cb)


def download_pulid(token, msg_cb=None):
    """Télécharge les poids PuLID-FLUX (guozinan/PuLID, ~1.14 Go)."""
    dest = pulid_weights_path()
    if dest.exists() and dest.stat().st_size > 100 * 1024 * 1024:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    if msg_cb:
        msg_cb(f"Téléchargement des poids PuLID-FLUX (~{PULID['weights_size_mb']} Mo)…")
    _hf_download_file(PULID["weights_repo"], PULID["weights_filename"], dest, token, msg_cb)


def download_model(model_id, quant, token, msg_cb=None):
    """Télécharge le modèle GGUF (choisi) + ses dépendances."""
    m = MODELS[model_id]
    # 1) dépendances
    for d in m["deps"]:
        ensure_dep(d, token, msg_cb)
    # 2) transformer principal
    if not _model_present(model_id, quant):
        file = m["file_for_quant"][quant]
        # Nom dans le dépôt distant (peut contenir un sous-dossier, ex. "TURBO/...").
        remote = m.get("remote_file_for_quant", {}).get(quant, file)
        if msg_cb:
            msg_cb(f"Téléchargement du modèle {file}")
        _hf_download_file(m["repo"], remote,
                          DIFFUSION_DIR / file, token, msg_cb)
        # uncond pour ideogram
        uncond = m.get("uncond_file_for_quant", {}).get(quant)
        if uncond and not (DIFFUSION_DIR / uncond).exists():
            if msg_cb:
                msg_cb(f"Téléchargement du modèle uncond {uncond}")
            _hf_download_file(m["repo"], uncond,
                              DIFFUSION_DIR / uncond, token, msg_cb)


# =========================================================================== #
#  Gestionnaire de tâches asynchrones (téléchargements + générations)
# =========================================================================== #
class TaskManager:
    """Exécute une tâche à la fois dans un thread d'arrière-plan."""

    def __init__(self):
        self._lock = threading.Lock()
        self._thread = None
        self._queue = []
        self.state = {
            "busy": False,
            "kind": None,          # "download" | "generate" | "engine"
            "log": "",             # dernière ligne de log
            "progress": 0.0,       # 0..1
            "step": 0, "total_steps": 0,
            "error": None,
            "done": False,
            "result": None,        # infos résultat (images, etc.)
            "elapsed": 0.0,        # FIX 3 : temps écoulé depuis le départ
            "eta": 0.0,            # FIX 3 : temps restant estimé
        }

    def _reset(self, kind):
        with self._lock:
            self.state = {"busy": True, "kind": kind, "log": "", "progress": 0.0,
                          "step": 0, "total_steps": 0, "error": None,
                          "done": False, "result": None, "preview_batch_id": None}

    def is_busy(self):
        with self._lock:
            return self.state["busy"]

    def _serialize_queue_locked(self):
        return [
            {
                "queue_id": item["queue_id"],
                "position": idx + 1,
                **item["summary"],
            }
            for idx, item in enumerate(self._queue)
        ]

    def list_queue(self):
        with self._lock:
            return self._serialize_queue_locked()

    def remove_from_queue(self, queue_id):
        with self._lock:
            before = len(self._queue)
            self._queue = [it for it in self._queue if it["queue_id"] != queue_id]
            return len(self._queue) < before

    def clear_queue(self):
        with self._lock:
            count = len(self._queue)
            self._queue.clear()
            return count

    def queued_source_paths(self):
        """Retourne l'ensemble des chemins d'images sources utilisés par la file d'attente."""
        with self._lock:
            paths = set()
            for item in self._queue:
                p = item.get("params") or {}
                if p.get("source_image"):
                    paths.add(str(p["source_image"]))
                if p.get("mask_image"):
                    paths.add(str(p["mask_image"]))
                for r in (p.get("ref_images") or []):
                    if r:
                        paths.add(str(r))
            return paths

    def snapshot(self):
        with self._lock:
            snap = dict(self.state)
            snap["queue"] = self._serialize_queue_locked()
            snap["queue_size"] = len(self._queue)
            return snap

    def _set(self, **kw):
        with self._lock:
            self.state.update(kw)

    def start_download(self, model_id, quant):
        if self.is_busy():
            raise RuntimeError("Une tâche est déjà en cours.")
        token = hf_token()
        self._reset("download")
        t = threading.Thread(target=self._run_download,
                             args=(model_id, quant, token), daemon=True)
        self._thread = t
        t.start()

    def _run_download(self, model_id, quant, token):
        try:
            def msg(s):
                self._set(log=s)
            download_model(model_id, quant, token, msg_cb=msg)
            self._set(log="Téléchargement terminé ✓", progress=1.0,
                      done=True, busy=False,
                      result={"type": "download", "model_id": model_id, "quant": quant})
        except Exception as e:
            self._set(error=str(e), log=f"Erreur: {e}", done=True, busy=False)

    def start_upscaler_download(self, upscaler_id):
        """Télécharge un modèle d'agrandissement ×4 (ESRGAN/MoSR, URL directe)."""
        if upscaler_id not in UPSCALERS:
            raise RuntimeError("Modèle d'agrandissement inconnu.")
        if self.is_busy():
            raise RuntimeError("Une tâche est déjà en cours.")
        self._reset("download")

        def work():
            def msg(s):
                self._set(log=s)
            def prog(done, total):
                if total:
                    self._set(progress=done / total,
                              log=f"{UPSCALERS[upscaler_id]['name']} : "
                                  f"{done // (1 << 20)}/{total // (1 << 20)} Mo")
            download_upscaler(upscaler_id, msg_cb=msg, progress_cb=prog)
            self._set(log="Modèle d'agrandissement téléchargé ✓", progress=1.0,
                      done=True, busy=False,
                      result={"type": "download", "upscaler_id": upscaler_id})

        t = threading.Thread(target=self._safe_aux_run, args=(work,), daemon=True)
        self._thread = t
        t.start()

    def start_adetailer_download(self, detector_id):
        """Télécharge un détecteur ADetailer YOLOv8 (safetensors, Hugging Face)."""
        if detector_id not in ADETAILERS:
            raise RuntimeError("Détecteur ADetailer inconnu.")
        if self.is_busy():
            raise RuntimeError("Une tâche est déjà en cours.")
        token = hf_token()
        self._reset("download")

        def work():
            def msg(s):
                self._set(log=s)
            download_adetailer(detector_id, token, msg_cb=msg)
            self._set(log="Détecteur ADetailer téléchargé ✓", progress=1.0,
                      done=True, busy=False,
                      result={"type": "download", "detector_id": detector_id})

        t = threading.Thread(target=self._safe_aux_run, args=(work,), daemon=True)
        self._thread = t
        t.start()

    def start_seedvr2_download(self):
        """Télécharge les poids SeedVR2 (restauration ×2, ~6.8 Go depuis HF)."""
        if self.is_busy():
            raise RuntimeError("Une tâche est déjà en cours.")
        token = hf_token()
        self._reset("download")

        def work():
            def msg(s):
                self._set(log=s)
            download_seedvr2(token, msg_cb=msg)
            self._set(log="SeedVR2 téléchargé ✓", progress=1.0, done=True, busy=False,
                      result={"type": "download", "seedvr2": True})

        t = threading.Thread(target=self._safe_aux_run, args=(work,), daemon=True)
        self._thread = t
        t.start()

    def start_pid_download(self, backbone):
        """Télécharge le socle PiD (Gemma 2 2B + tokenizer, une seule fois) puis
        le modèle int8 du backbone choisi (~1,6 Go) + son VAE."""
        if backbone not in PID["backbones"]:
            raise RuntimeError(f"Backbone PiD inconnu : {backbone}")
        if self.is_busy():
            raise RuntimeError("Une tâche est déjà en cours.")
        token = hf_token()
        self._reset("download")

        def work():
            def msg(s):
                self._set(log=s)
            download_pid(backbone, token, msg_cb=msg)
            self._set(log=f"PiD ({backbone}) installé ✓", progress=1.0, done=True, busy=False,
                      result={"type": "download", "pid": backbone})

        t = threading.Thread(target=self._safe_aux_run, args=(work,), daemon=True)
        self._thread = t
        t.start()

    def start_taesd_download(self, ta_id):
        """Télécharge un mini-VAE TAE (~2 Mo, quasi instantané)."""
        if ta_id not in TAESD:
            raise RuntimeError("Mini-VAE inconnu.")
        if self.is_busy():
            raise RuntimeError("Une tâche est déjà en cours.")
        token = hf_token()
        self._reset("download")

        def work():
            def msg(s):
                self._set(log=s)
            download_taesd(ta_id, token, msg_cb=msg)
            self._set(log="Mini-VAE téléchargé ✓", progress=1.0, done=True, busy=False,
                      result={"type": "download", "taesd_id": ta_id})

        t = threading.Thread(target=self._safe_aux_run, args=(work,), daemon=True)
        self._thread = t
        t.start()

    def start_pulid_download(self):
        """Télécharge les poids PuLID-FLUX (~1.14 Go depuis HF)."""
        if self.is_busy():
            raise RuntimeError("Une tâche est déjà en cours.")
        token = hf_token()
        self._reset("download")

        def work():
            def msg(s):
                self._set(log=s)
            download_pulid(token, msg_cb=msg)
            self._set(log="Poids PuLID téléchargés ✓", progress=1.0, done=True, busy=False,
                      result={"type": "download", "pulid": True})

        t = threading.Thread(target=self._safe_aux_run, args=(work,), daemon=True)
        self._thread = t
        t.start()

    def _safe_aux_run(self, work):
        try:
            work()
        except Exception as e:
            self._set(error=str(e), log=f"Erreur: {e}", done=True, busy=False)

    def start_engine_install(self):
        if self.is_busy():
            raise RuntimeError("Une tâche est déjà en cours.")
        self._reset("engine")
        t = threading.Thread(target=self._run_engine, daemon=True)
        self._thread = t
        t.start()

    def _run_engine(self):
        try:
            def cb(done, total):
                if total:
                    self._set(progress=done / total,
                              log=f"Téléchargement du moteur… {done//(1<<20)}/{total//(1<<20)} Mo")
            install_engine(progress_cb=cb)
            self._set(log="Moteur installé ✓", progress=1.0, done=True, busy=False,
                      result={"type": "engine"})
        except Exception as e:
            self._set(error=str(e), log=f"Erreur: {e}", done=True, busy=False)

    # --- Génération ---
    _proc = None
    _cancel = False

    def _build_queue_item(self, params):
        from registry import MODELS as _MODELS
        model_id = params.get("model_id", "")
        m = _MODELS.get(model_id, {})
        if params.get("task_kind") == "upscale":
            u = UPSCALERS.get(params.get("upscaler_id", ""), {})
            src_name = Path(params.get("source_image") or "?").name
            return {
                "queue_id": uuid.uuid4().hex[:8],
                "params": dict(params),
                "summary": {
                    "model_id": f"upscale:{params.get('upscaler_id', '')}",
                    "model_name": f"🔍 {u.get('name', params.get('upscaler_id', '?'))}",
                    "quant": f"×{u.get('scale', 4)}",
                    "prompt": f"Agrandissement de {src_name}",
                    "batch": 1,
                    "width": 0,
                    "height": 0,
                },
                "created_at": time.time(),
            }
        if params.get("task_kind") == "repair":
            d = ADETAILERS.get(params.get("detector_id", ""), {})
            src_name = Path(params.get("source_image") or "?").name
            return {
                "queue_id": uuid.uuid4().hex[:8],
                "params": dict(params),
                "summary": {
                    "model_id": f"repair:{params.get('detector_id', '')}",
                    "model_name": f"🙂 {d.get('name', params.get('detector_id', '?'))}",
                    "quant": "",
                    "prompt": f"Réparation visages/mains de {src_name}",
                    "batch": 1,
                    "width": 0,
                    "height": 0,
                },
                "created_at": time.time(),
            }
        if params.get("task_kind") == "restore_x2":
            src_name = Path(params.get("source_image") or "?").name
            return {
                "queue_id": uuid.uuid4().hex[:8],
                "params": dict(params),
                "summary": {
                    "model_id": "seedvr2",
                    "model_name": "🩹 SeedVR2 (Restauration ×2)",
                    "quant": "×2",
                    "prompt": f"Restauration de {src_name}",
                    "batch": 1,
                    "width": 0,
                    "height": 0,
                },
                "created_at": time.time(),
            }
        if params.get("task_kind") == "pid":
            bb = (params.get("backbone") or "").strip() or "auto"
            bb_label = (PID.get("backbones", {}).get(bb, {}) or {}).get("label", bb)
            src_name = Path(params.get("source_image") or "?").name
            return {
                "queue_id": uuid.uuid4().hex[:8],
                "params": dict(params),
                "summary": {
                    "model_id": f"pid_{bb}",
                    "model_name": f"⬆️ PiD ×4 ({bb_label})",
                    "quant": "×4",
                    "prompt": f"Super-résolution PiD de {src_name}",
                    "batch": 1,
                    "width": 4096,
                    "height": 4096,
                },
                "created_at": time.time(),
            }
        return {
            "queue_id": uuid.uuid4().hex[:8],
            "params": dict(params),
            "summary": {
                "model_id": model_id,
                "model_name": m.get("name", model_id),
                "quant": params.get("quant", ""),
                "prompt": (params.get("prompt") or "")[:90],
                "batch": int(params.get("batch") or 1),
                "width": int(params.get("width") or 1024),
                "height": int(params.get("height") or 1024),
            },
            "created_at": time.time(),
        }

    def enqueue_generate(self, params):
        """
        Si aucune tâche n'est en cours, démarre immédiatement la génération.
        Sinon (si une génération est déjà en cours), l'ajoute à la file d'attente.
        """
        with self._lock:
            if self.state["busy"] and self.state.get("kind") in ("download", "engine"):
                raise RuntimeError("Un téléchargement est en cours. Patientez avant de lancer une génération.")
            if self.state["busy"]:
                item = self._build_queue_item(params)
                self._queue.append(item)
                return {
                    "queued": True,
                    "started": False,
                    "queue_id": item["queue_id"],
                    "position": len(self._queue),
                    "queue_size": len(self._queue),
                    "queue": self._serialize_queue_locked(),
                }
        self.start_generate(params)
        return {
            "queued": False,
            "started": True,
            "queue_id": None,
            "position": 0,
            "queue_size": len(self.list_queue()),
            "queue": self.list_queue(),
        }

    @staticmethod
    def _kind_of(params):
        tk = params.get("task_kind")
        if tk in ("upscale", "repair", "restore_x2", "pid"):
            return tk
        return "generate"

    def start_generate(self, params):
        if self.is_busy():
            raise RuntimeError("Une tâche est déjà en cours.")
        self._reset(self._kind_of(params))
        self._cancel = False
        t = threading.Thread(target=self._run_generate_loop, args=(params,), daemon=True)
        self._thread = t
        t.start()

    def _run_generate_loop(self, first_params):
        current_params = first_params
        while current_params is not None:
            tk = current_params.get("task_kind")
            if tk == "upscale":
                self._run_upscale(current_params)
            elif tk == "repair":
                self._run_repair(current_params)
            elif tk == "restore_x2":
                self._run_seedvr2(current_params)
            elif tk == "pid":
                self._run_pid(current_params)
            else:
                self._run_generate(current_params)
            with self._lock:
                if self._queue:
                    next_item = self._queue.pop(0)
                    current_params = next_item["params"]
                    self.state = {
                        "busy": True,
                        "kind": self._kind_of(current_params),
                        "log": f"Démarrage de la tâche suivante en file ({len(self._queue)} restante(s))…",
                        "progress": 0.0,
                        "step": 0,
                        "total_steps": 0,
                        "error": None,
                        "done": False,
                        "result": self.state.get("result"),
                        "elapsed": 0.0,
                        "eta": 0.0,
                    }
                    self._cancel = False
                else:
                    current_params = None

    def cancel(self):
        self._cancel = True
        p = self._proc
        if p:
            try:
                p.terminate()
            except Exception:
                pass

    def _run_generate(self, p):
        try:
            import db
            from registry import MODELS as _MODELS
            model_id = p["model_id"]
            quant = p["quant"]
            m = _MODELS[model_id]
            manifest = load_manifest()

            # vérifs
            sd = find_sd_cli()
            if not sd:
                raise RuntimeError("Le moteur sd-cli n'est pas installé. Allez dans l'onglet Modèles.")
            if not _model_present(model_id, quant):
                raise RuntimeError(f"Le modèle {model_id} ({quant}) n'est pas téléchargé.")
            missing = [d for d in m["deps"] if not _dep_present(d)]
            if missing:
                raise RuntimeError("Dépendances manquantes: " + ", ".join(missing))

            # --- Images fournies (refs multiples ou image de depart) ---
            input_images = [str(x) for x in (p.get("ref_images") or []) if x]
            if not input_images and p.get("source_image"):
                input_images = [str(p["source_image"])]
            input_mode = p.get("input_mode")
            input_images, input_mode, err = check_images_input(model_id, input_images, input_mode)
            if err:
                raise RuntimeError(err)
            missing_files = [x for x in input_images if not (ROOT / x).exists()]
            if missing_files:
                raise RuntimeError(
                    f"{len(missing_files)} image(s) source(s) introuvable(s) sur le disque : "
                    + ", ".join(Path(x).name for x in missing_files[:3])
                )
            has_refs = input_mode == "ref" and bool(input_images)

            # Certains modeles Qwen-VL exigent le mmproj pour traiter des references.
            mmproj_dep = m.get("mmproj_dep")
            if mmproj_dep and has_refs:
                mmproj_path = _dep_path(manifest, mmproj_dep)
                if not mmproj_path or not Path(mmproj_path).exists():
                    raise RuntimeError(
                        f"Pour éditer avec {m['name']}, le fichier mmproj est requis "
                        "(encodeur visuel du VLM). Téléchargez-le depuis le bouton "
                        "'Télécharger mmproj' dans l'interface."
                    )

            batch = max(1, min(4, int(p["batch"])))
            batch_id = uuid.uuid4().hex  # identifiant unique, même pour deux lancements rapprochés
            seed = int(p["seed"]) if p.get("seed") not in (None, "") else int(time.time()) % 1000000

            # Générer des noms de fichiers intelligents et sûrs
            # Format: model_motsprompt_001.png (dans output/ directement)
            model_name = re.sub(r'[^a-zA-Z0-9_]', '_', m["name"].lower())
            prompt_words = (p["prompt"] or "").strip().lower()
            clean_prompt = re.sub(r'[^a-zA-Z0-9]', '_', prompt_words)
            words = [w for w in clean_prompt.split('_') if w][:3]
            prompt_part = "_".join(words)[:30] if words else "generation"

            # Template de sortie directement dans OUTPUT_DIR
            output_prefix = f"{model_name}_{prompt_part}_{batch_id}"
            out_tmpl = str(OUTPUT_DIR / f"{output_prefix}_%03d.png")

            # --- Options Qualité / Détails / Upscaling ---
            sampler = p.get("sampler")
            if sampler in ("", "default"):
                sampler = None
            scheduler = p.get("scheduler")
            if scheduler in ("", "default"):
                scheduler = None
            vae_tiling = bool(p.get("vae_tiling"))
            slg_scale = p.get("slg_scale")
            try:
                slg_scale = float(slg_scale) if slg_scale not in (None, "", 0, "0") else None
            except (TypeError, ValueError):
                slg_scale = None
            if slg_scale is not None and slg_scale <= 0:
                slg_scale = None
            chosen_sampler = sampler or m["defaults"]["sampler"]

            # Upscaling ×4 pendant la génération (ESRGAN/MoSR natif sd-cli)
            upscale_path = None
            upscale_id = p.get("upscale_id")
            if upscale_id:
                u = UPSCALERS.get(upscale_id)
                if not u:
                    raise RuntimeError("Modèle d'agrandissement inconnu. Choisissez-en un dans la section Qualité.")
                cand = upscaler_path(upscale_id)
                if not cand or not cand.exists():
                    raise RuntimeError(
                        f"« {u['name']} » n'est pas téléchargé. Ouvrez l'onglet Modèles "
                        "→ section « 🔍 Upscaling ×4 » pour le télécharger (quelques dizaines de Mo)."
                    )
                upscale_path = str(cand)

            # ADetailer : détecteur YOLOv8 pour retoucher automatiquement visages/mains
            adetailer_path_resolved = None
            adetailer_id = p.get("adetailer_id")
            if adetailer_id:
                d = ADETAILERS.get(adetailer_id)
                if not d:
                    raise RuntimeError("Détecteur ADetailer inconnu.")
                cand = adetailer_path(adetailer_id)
                if not cand or not cand.exists():
                    raise RuntimeError(
                        f"Le détecteur « {d['name']} » n'est pas téléchargé. Ouvrez l'onglet "
                        "Modèles → section « 🙂 ADetailer » pour le télécharger (quelques Mo)."
                    )
                adetailer_path_resolved = str(cand)

            # --- Performance : mini-VAE TAE (decodage accélère, modeles Qwen-Image) ---
            taesd_file = None
            ta_id = p.get("taesd_id") or ""
            if ta_id:
                if ta_id == "auto":
                    ta_id = taesd_for_model(model_id) or ""
                t = TAESD.get(ta_id)
                if t:
                    cand = taesd_path(ta_id)
                    if t["vae_dep"] != (m.get("vae_dep") or ("vae_qwen" if m.get("arch") == "qwen_image" else None)):
                        # TAE incompatible avec le VAE du modele : ignore proprement
                        t = None
                    elif cand and cand.exists():
                        taesd_file = str(cand)
                    else:
                        raise RuntimeError(
                            f"« {t['name']} » n'est pas téléchargé. Ouvrez l'onglet Modèles "
                            "→ section « ⚡ VAE rapide (TAE) » pour l'installer (~2 Mo).")

            # --- Performance : SageAttention CUDA ---
            sage_attn = bool(p.get("sage_attn")) or bool(load_settings().get("sage_attn"))

            # --- Apercu en direct pendant l'echantillonnage ---
            preview_method = (p.get("preview") or load_settings().get("preview") or "none").strip()
            preview_interval = int(p.get("preview_interval") or load_settings().get("preview_interval") or 3)
            preview_path = None
            if preview_method not in ("", "none"):
                if preview_method == "tae" and not taesd_file:
                    # La methode « tae » exige un mini-VAE TAE pour ce modele : repli sur proj
                    self._set(log="Aperçu « tae » indisponible (mini-VAE TAE absent) — repli sur « proj ».")
                    preview_method = "proj"
                # Nettoie les anciens aperçus pour ne pas accumuler
                try:
                    for _old in PREVIEW_DIR.glob("live_*.png"):
                        try:
                            _old.unlink()
                        except OSError:
                            pass
                except Exception:
                    pass
                preview_path = str(PREVIEW_DIR / f"live_{batch_id}_%03d.png")
                self._set(preview_batch_id=batch_id)

            # --- PuLID-FLUX : conservation du visage depuis un portrait ---
            pulid_w_path = None
            pulid_emb_path = None
            pulid_w = None
            if p.get("pulid_id"):
                if not supports_pulid(model_id):
                    raise RuntimeError(
                        f"{m['name']} ne prend pas en charge PuLID. Choisissez FLUX.1 Schnell, "
                        "FLUX.1 Dev ou FHDR (arch FLUX) pour conserver un visage de photo.")
                if not pulid_status()["downloaded"]:
                    raise RuntimeError(
                        "Les poids PuLID-FLUX ne sont pas installés (~1,14 Go). Ouvrez l'onglet "
                        "Modèles → section « 🙂 Visage fidèle (PuLID) ».")
                emb = portrait_embedding(p.get("pulid_id"))
                if not emb:
                    raise RuntimeError(
                        "Empreinte de portrait introuvable. Créez-la avec l'extracteur "
                        "d'identité (bouton « 🙂 Visage fidèle » de l'onglet Modèles, outil Python).")
                pulid_w_path = str(pulid_weights_path())
                pulid_emb_path = str(emb)
                try:
                    pulid_w = float(p.get("pulid_id_weight"))
                except (TypeError, ValueError):
                    pulid_w = PULID["default_weight"]

            # Hires Fix : 2e passe img2img à haute résolution (uniquement en génération
            # pure, sans image de départ, avec un modèle compatible img2img).
            hires_on = bool(p.get("hires_fix")) and not input_images and m.get("supports_img2img", False)
            hires_strength = 0.35
            try:
                hires_strength = float(p.get("hires_strength") or 0.35)
            except (TypeError, ValueError):
                hires_strength = 0.35
            hires_strength = max(0.1, min(0.8, hires_strength))

            final_quality = {}   # options appliquées sur l'image finale (passe 1 simple ou passe 2 Hires Fix)
            if not hires_on:
                if upscale_path:
                    final_quality["upscale_model"] = upscale_path
                if adetailer_path_resolved:
                    final_quality["adetailer_model"] = adetailer_path_resolved

            cmd = build_command(
                model_id, quant, p["prompt"], p.get("negative", ""),
                int(p["width"]), int(p["height"]), int(p["steps"]), float(p["cfg"]),
                seed, batch, out_tmpl, str(sd), manifest,
                source_image=(input_images[0] if (input_mode == "init" and input_images) else None),
                lora_dir=p.get("lora_dir"),
                strength=p.get("strength"),
                ref_images=input_images if has_refs else None,
                input_mode=input_mode,
                ref_max_pixels=p.get("ref_max_pixels"),
                mask_image=(str(ROOT / p["mask_image"]) if p.get("mask_image") else None),
                sampler=sampler, scheduler=scheduler, vae_tiling=vae_tiling,
                slg_scale=slg_scale,
                taesd_path=taesd_file, sage_attn=sage_attn,
                preview_method=preview_method, preview_path=preview_path,
                preview_interval=preview_interval,
                pulid_weights=pulid_w_path, pulid_id_embedding=pulid_emb_path,
                pulid_id_weight=pulid_w,
                **final_quality)

            # Vérifier qu'aucun argument n'est None
            for idx_arg, arg_val in enumerate(cmd):
                if arg_val is None:
                    raise RuntimeError(f"Erreur interne : l'argument de commande #{idx_arg} est None.")

            input_label = ""
            if has_refs:
                input_label = (f" · {len(input_images)} références" if len(input_images) > 1
                             else " · 1 référence")
            elif input_images:
                input_label = " · image de départ (img2img)"
            self._set(log=f"Démarrage de la génération…{input_label}",
                      total_steps=int(p["steps"]), step=0, error=None)

            creationflags = 0
            if os.name == "nt":
                creationflags = subprocess.CREATE_NO_WINDOW

            t_start = time.time()          # FIX 3 : chrono du moment où on lance

            def run_cli(cmd_args):
                """Lance sd-cli avec suivi de progression.
                Renvoie (code_retour, t_premiere_etape, derniere_etape_vue, dernieres_lignes)."""
                self._proc = subprocess.Popen(
                    cmd_args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace",
                    bufsize=1, creationflags=creationflags)
                step_re = re.compile(r"step\s+(\d+)\s+(?:of|/)\s+(\d+)", re.I)
                pct_re = re.compile(r"(\d+(?:\.\d+)?)\s*%")
                last_lines = []
                t_first_step = None
                last_step_seen = 0
                for line in self._proc.stdout:
                    if self._cancel:
                        break
                    line = line.rstrip()
                    if not line:
                        continue
                    last_lines.append(line)
                    last_lines = last_lines[-400:]
                    prog = self.state.get("progress", 0.0)
                    sm = step_re.search(line)
                    if sm:
                        s, tot = int(sm.group(1)), int(sm.group(2))
                        if t_first_step is None and s == 1:
                            t_first_step = time.time()   # debut du denoising
                        last_step_seen = max(last_step_seen, s)
                        prog = s / max(1, tot)
                        elapsed = time.time() - t_start
                        # estimation du temps restant
                        eta = (elapsed / s * tot - elapsed) if s > 0 else 0
                        self._set(step=s, total_steps=tot, progress=prog,
                                  log=line, result_tail="\n".join(last_lines[-6:]),
                                  elapsed=elapsed, eta=max(0, eta))
                    else:
                        pm = pct_re.search(line)
                        if pm:
                            prog = float(pm.group(1)) / 100.0
                        self._set(log=line, progress=prog,
                                  elapsed=time.time() - t_start)
                ret = self._proc.wait()
                self._proc = None
                return ret, t_first_step, last_step_seen, last_lines

            def extract_err_summary(last_lines):
                err_lines = [l for l in last_lines if any(k in l.lower() for k in ("error", "exception", "failed", "unknown", "invalid", "cuda", "cannot", "abort"))]
                if err_lines:
                    return "\n".join(err_lines[-6:])
                return "\n".join(last_lines[-8:]) if last_lines else "Aucun message du moteur."

            ret_code, t_first_step, last_step_seen, last_lines = run_cli(cmd)

            if self._cancel:
                self._set(log="Génération annulée.", done=True, busy=False,
                          result={"type": "generate", "cancelled": True, "images": []})
                return

            # Vérification du code de retour du processus
            if ret_code != 0:
                err_summary = extract_err_summary(last_lines)
                raise RuntimeError(f"Le moteur sd-cli s'est arrêté avec le code d'erreur {ret_code} :\n{err_summary}")

            # Ne collecter que les fichiers de ce lancement : jamais les autres PNG.
            produced = sorted(OUTPUT_DIR.glob(f"{output_prefix}_*.png"))
            produced = [fp for fp in produced if "_hires_" not in fp.name]

            if not produced:
                produced = [
                    f for f in OUTPUT_DIR.glob("*.png")
                    if f.stat().st_mtime >= t_start - 2
                    and "_hires_" not in f.name and "upscale_" not in f.name
                ]

            if not produced:
                err_summary = extract_err_summary(last_lines)
                raise RuntimeError(f"Aucune image n'a été produite par le moteur sd-cli :\n{err_summary}")

            # ---------- Hires Fix : 2e passe d'enrichissement des détails ----------
            # La passe 1 définit la composition ; la passe 2 re-détaille chaque image en
            # haute résolution (img2img doux, force ~0.35) comme en 1 clic dans A1111.
            if hires_on and produced:
                hr_scale = min(2.0, 2048.0 / float(max(int(p["width"]), int(p["height"]))))
                if hr_scale < 1.25:
                    self._set(log="Hires Fix ignoré : l'image finale dépasse déjà ~2048 px.")
                else:
                    hw = round16(int(p["width"]) * hr_scale)
                    hh = round16(int(p["height"]) * hr_scale)
                    hires_kwargs = {}
                    if upscale_path:
                        hires_kwargs["upscale_model"] = upscale_path
                    if adetailer_path_resolved:
                        hires_kwargs["adetailer_model"] = adetailer_path_resolved
                    if pulid_w_path and pulid_emb_path:
                        hires_kwargs["pulid_weights"] = pulid_w_path
                        hires_kwargs["pulid_id_embedding"] = pulid_emb_path
                        hires_kwargs["pulid_id_weight"] = pulid_w
                    if sage_attn:
                        hires_kwargs["sage_attn"] = True
                    final_files = []
                    for hf_i, fp in enumerate(produced):
                        self._set(log=(f"🔍 Hires Fix — passe 2/2 (image {hf_i + 1}/{len(produced)}) : "
                                       f"enrichissement des détails à {hw}×{hh}…"),
                                  progress=0.0, step=0)
                        out_tmpl_hr = str(OUTPUT_DIR / f"{output_prefix}_hires_{hf_i:03d}_%03d.png")
                        cmd_hr = build_command(
                            model_id, quant, p["prompt"], p.get("negative", ""),
                            hw, hh, int(p["steps"]), float(p["cfg"]),
                            seed + hf_i, 1, out_tmpl_hr, str(sd), manifest,
                            source_image=str(fp), strength=hires_strength,
                            input_mode="init",
                            lora_dir=p.get("lora_dir"),
                            sampler=sampler, scheduler=scheduler,
                            vae_tiling=True,  # décodage VAE par tuiles en HR : évite les pics de VRAM
                            slg_scale=slg_scale, **hires_kwargs)
                        for idx_arg, arg_val in enumerate(cmd_hr):
                            if arg_val is None:
                                raise RuntimeError(f"Erreur interne : argument Hires Fix #{idx_arg} est None.")
                        ret_hr, _t_first_hr, last_step_hr, last_lines_hr = run_cli(cmd_hr)
                        last_lines = last_lines_hr
                        if last_step_hr:
                            last_step_seen += last_step_hr
                        if self._cancel:
                            self._set(log="Génération annulée.", done=True, busy=False,
                                      result={"type": "generate", "cancelled": True, "images": []})
                            return
                        hr_files = sorted(OUTPUT_DIR.glob(f"{output_prefix}_hires_{hf_i:03d}_*.png"))
                        if ret_hr != 0 or not hr_files:
                            # Passe 2 en échec : on garde l'image de la passe 1 plutôt que tout perdre.
                            self._set(log=(f"⚠️ Passe 2 Hires Fix en échec pour l'image {hf_i + 1} "
                                           f"(code {ret_hr}) — résultat de la passe 1 conservé."))
                            final_files.append(fp)
                            continue
                        try:
                            fp.unlink(missing_ok=True)  # supprime le brouillon basse résolution
                        except Exception:
                            pass
                        final_files.append(hr_files[0])
                    produced = final_files

            # ---------- Metadonnees PNG : injection pour les anciens PNG ----------
            # Les PNG recents portent deja le chunk « parameters » ecrit par sd-cli.
            # Pour les autres, on injecte la fiche minimale (prompt, seed, modele)
            # a partir des reglages de cette generation — jamais d'ecrasement.
            for i, fp in enumerate(produced):
                try:
                    txt = _pngmeta.build_webui_text(
                        prompt=p["prompt"], negative=p.get("negative", ""),
                        steps=int(p["steps"]), cfg=float(p["cfg"]),
                        seed=seed + i,
                        width=None, height=None, sampler=chosen_sampler,
                        model_id=model_id)
                    _pngmeta.embed_params(fp, txt, only_if_missing=True)
                except Exception:
                    pass

            t_end = time.time()
            total_seconds = t_end - t_start
            denoise_seconds = (t_end - t_first_step) if t_first_step else total_seconds
            per_step = (denoise_seconds / max(1, last_step_seen)) if last_step_seen else 0

            images = []
            for i, fp in enumerate(produced):
                rel = fp.relative_to(OUTPUT_DIR).as_posix()
                dims = _png_size(fp)  # dimensions réelles (prises en compte du Hires Fix/x4)
                out_w, out_h = dims if dims else (int(p["width"]), int(p["height"]))
                if upscale_path and not hires_on:
                    out_w, out_h = int(p["width"]) * 4, int(p["height"]) * 4
                image_id = db.add_image(
                    batch_id=batch_id, idx=i, model_id=model_id, model_name=m["name"],
                    quant=quant, prompt=p["prompt"], negative=p.get("negative", ""),
                    seed=seed + i, width=out_w, height=out_h,
                    steps=int(p["steps"]), cfg=float(p["cfg"]),
                    sampler=chosen_sampler, filename=rel, batch_size=batch,
                    gen_time=round(total_seconds / max(1, len(produced)), 1),
                    source_images=input_images)
                images.append({"url": f"/output/{rel}", "filename": rel,
                               "seed": seed + i, "id": image_id})

            stats = {
                "total_seconds": round(total_seconds, 1),
                "denoise_seconds": round(denoise_seconds, 1),
                "per_step_seconds": round(per_step, 2),
                "steps": last_step_seen,
                "batch": batch,
                "sec_per_image": round(total_seconds / max(1, len(images)), 1),
                "it_s": round(last_step_seen / denoise_seconds, 2) if denoise_seconds > 0 else 0,
            }
            self._set(log=f"Génération terminée ✓ ({len(images)} image(s) en {total_seconds:.1f}s)",
                      progress=1.0, done=True, busy=False, error=None,
                      result={"type": "generate", "images": images,
                              "batch_id": batch_id, "cancelled": False,
                              "stats": stats})
        except Exception as e:
            self._set(error=str(e), log=f"Erreur: {e}", done=True, busy=False,
                      result={"type": "generate", "images": [], "error": str(e), "cancelled": False})

    # --- Agrandissement ×4 autonome (mode -M upscale de sd-cli) ---
    def _run_upscale(self, p):
        try:
            import db
            uid = p.get("upscaler_id", "")
            u = UPSCALERS.get(uid)
            if not u:
                raise RuntimeError("Modèle d'agrandissement inconnu.")
            up_path = upscaler_path(uid)
            if not up_path or not up_path.exists():
                raise RuntimeError(
                    f"« {u['name']} » n'est pas téléchargé. Ouvrez l'onglet Modèles "
                    "→ section « 🔍 Upscaling ×4 » pour le télécharger.")
            sd = find_sd_cli()
            if not sd:
                raise RuntimeError("Le moteur sd-cli n'est pas installé. Allez dans l'onglet Modèles.")
            src_rel = p.get("source_image")
            src = (ROOT / src_rel) if src_rel else None
            if not src or not src.exists():
                raise RuntimeError("Image source introuvable sur le disque.")

            scale = int(u.get("scale", 4))
            src_dims = _png_size(src)
            stem = re.sub(r"[^a-zA-Z0-9_]", "_", src.stem.lower())[:40] or "image"
            out_name = f"upscale_x{scale}_{stem}_{uuid.uuid4().hex[:6]}.png"
            out_path = OUTPUT_DIR / out_name
            cmd = build_upscale_command(str(sd), str(src), str(out_path), up_path)

            self._set(log=f"🔍 Agrandissement ×{scale} de « {src.name} » avec {u['name']}…",
                      progress=0.02, step=0, total_steps=0, error=None, done=False)

            creationflags = 0
            if os.name == "nt":
                creationflags = subprocess.CREATE_NO_WINDOW

            t_start = time.time()
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                bufsize=1, creationflags=creationflags)

            pct_re = re.compile(r"(\d+(?:\.\d+)?)\s*%")
            last_lines = []
            for line in self._proc.stdout:
                if self._cancel:
                    break
                line = line.rstrip()
                if not line:
                    continue
                last_lines.append(line)
                last_lines = last_lines[-400:]
                prog = self.state.get("progress", 0.0)
                pm = pct_re.search(line)
                if pm:
                    prog = float(pm.group(1)) / 100.0
                self._set(log=line, progress=prog, elapsed=time.time() - t_start)

            ret_code = self._proc.wait()
            self._proc = None
            total_seconds = time.time() - t_start

            if self._cancel:
                out_path.unlink(missing_ok=True)
                self._set(log="Agrandissement annulé.", done=True, busy=False,
                          result={"type": "upscale", "cancelled": True, "images": []})
                return

            def _err_summary():
                err_lines = [l for l in last_lines if any(k in l.lower() for k in (
                    "error", "exception", "failed", "unknown", "invalid", "cannot", "abort"))]
                if err_lines:
                    return "\n".join(err_lines[-6:])
                return "\n".join(last_lines[-8:]) if last_lines else "Aucun message du moteur."

            if ret_code != 0:
                raise RuntimeError(
                    f"Le moteur sd-cli s'est arrêté avec le code d'erreur {ret_code} :\n"
                    f"{_err_summary()}")
            if not out_path.exists() or out_path.stat().st_size < 16 * 1024:
                raise RuntimeError(
                    f"Aucune image agrandie n'a été produite par le moteur sd-cli :\n{_err_summary()}")

            out_dims = _png_size(out_path)
            if out_dims:
                out_w, out_h = out_dims
            elif src_dims:
                out_w, out_h = src_dims[0] * scale, src_dims[1] * scale
            else:
                out_w = out_h = 0

            image_id = db.add_image(
                batch_id=uuid.uuid4().hex, idx=0,
                model_id=f"upscale:{uid}", model_name=f"🔍 {u['name']}",
                quant=f"×{scale}",
                prompt=f"Agrandissement ×{scale} de {src.name}",
                negative="", seed=0, width=out_w, height=out_h,
                steps=0, cfg=0.0, sampler="upscale", filename=out_name,
                batch_size=1, gen_time=round(total_seconds, 1),
                source_images=[src_rel])
            label = (f"Agrandissement terminé ✓ ({src.name} → {out_w}×{out_h}"
                     if out_w else "Agrandissement terminé ✓")
            self._set(log=f"{label} en {total_seconds:.1f}s)", progress=1.0,
                      done=True, busy=False, error=None,
                      result={"type": "upscale",
                              "images": [{"url": f"/output/{out_name}", "filename": out_name,
                                          "seed": 0, "id": image_id,
                                          "upscaled": True, "scale": scale}],
                              "cancelled": False})
        except Exception as e:
            self._set(error=str(e), log=f"Erreur: {e}", done=True, busy=False,
                      result={"type": "upscale", "images": [], "error": str(e),
                              "cancelled": False})

    # --- Reparation visages/mains autonome (mode -M adetailer) ---
    def _run_repair(self, p):
        try:
            import db
            did = p.get("detector_id", "")
            d = ADETAILERS.get(did)
            if not d:
                raise RuntimeError("Détecteur ADetailer inconnu.")
            det_path = adetailer_path(did)
            if not det_path or not det_path.exists():
                raise RuntimeError(
                    f"Le détecteur « {d['name']} » n'est pas téléchargé. Ouvrez l'onglet "
                    "Modèles → section « 🙂 ADetailer » pour l'installer (quelques Mo).")
            sd = find_sd_cli()
            if not sd:
                raise RuntimeError("Le moteur sd-cli n'est pas installé. Allez dans l'onglet Modèles.")
            src_rel = p.get("source_image")
            src = (ROOT / src_rel) if src_rel else None
            if not src or not src.exists():
                raise RuntimeError("Image source introuvable sur le disque.")

            # Modele de generation charge pour re-detailler les zones detectees :
            # celui de la demande, sinon le meilleur modele pret disponible
            # (ordre de preference optimise pour la retouche).
            model_id = p.get("model_id") or ""
            quant = p.get("quant") or ""
            if model_id not in MODELS:
                model_id = ""
            if not model_id:
                for cand in ("flux-schnell", "flux-dev", "sd3.5-medium", "sd3.5-large",
                             "chroma", "qwen-image-2512", "flux-kontext-dev"):
                    if cand in MODELS and model_status(cand)["ready"]:
                        model_id = cand
                        break
            if not model_id:
                raise RuntimeError(
                    "Aucun modèle de génération prêt n'est installé pour la retouche. "
                    "Téléchargez-en un (ex. FLUX.1 Schnell) dans l'onglet Modèles.")
            m = MODELS[model_id]
            if not quant or quant not in m["quants"] or not _model_present(model_id, quant):
                quant = next((q for q in m["quants"] if _model_present(model_id, q)), None)
            if not quant:
                raise RuntimeError(f"Aucun poids de {m['name']} n'est téléchargé.")
            missing = [d_ for d_ in m["deps"] if not _dep_present(d_)]
            if missing:
                raise RuntimeError(
                    f"Dépendances manquantes pour {m['name']} : " + ", ".join(missing))

            seed = p.get("seed") or 42
            try:
                seed = int(seed)
            except (TypeError, ValueError):
                seed = 42
            strength = p.get("strength")
            try:
                strength = max(0.1, min(1.0, float(strength))) if strength not in (None, "") else 0.4
            except (TypeError, ValueError):
                strength = 0.4

            stem = re.sub(r"[^a-zA-Z0-9_]", "_", src.stem.lower())[:40] or "image"
            out_name = f"repair_{stem}_{uuid.uuid4().hex[:6]}.png"
            out_path = OUTPUT_DIR / out_name

            manifest = load_manifest()
            cmd = build_adetailer_command(
                model_id, quant, str(src), str(out_path), str(sd), manifest,
                det_path, prompt=(p.get("prompt") or "").strip() or None,
                seed=seed, ad_prompt=(p.get("ad_prompt") or "").strip() or None,
                denoise=strength,
                taesd_path=(str(taesd_path(taesd_for_model(model_id)))
                            if p.get("taesd_id") and taesd_for_model(model_id)
                               and taesd_path(taesd_for_model(model_id))
                               and taesd_path(taesd_for_model(model_id)).exists() else None),
                sage_attn=bool(p.get("sage_attn")) or bool(load_settings().get("sage_attn")),
                lora_dir=None)

            self._set(log=f"🙂 Réparation {d['name']} de « {src.name} » avec {m['name']}…",
                      progress=0.02, step=0, total_steps=int(m["defaults"]["steps"]),
                      error=None, done=False)

            creationflags = 0
            if os.name == "nt":
                creationflags = subprocess.CREATE_NO_WINDOW
            t_start = time.time()
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                bufsize=1, creationflags=creationflags)

            step_re = re.compile(r"step\s+(\d+)\s+(?:of|/)\s+(\d+)", re.I)
            pct_re = re.compile(r"(\d+(?:\.\d+)?)\s*%")
            last_lines = []
            for line in self._proc.stdout:
                if self._cancel:
                    break
                line = line.rstrip()
                if not line:
                    continue
                last_lines.append(line)
                last_lines = last_lines[-400:]
                prog = self.state.get("progress", 0.0)
                sm = step_re.search(line)
                if sm:
                    s, tot = int(sm.group(1)), int(sm.group(2))
                    self._set(step=s, total_steps=tot,
                              progress=min(1.0, s / max(1, tot)),
                              log=line, elapsed=time.time() - t_start)
                else:
                    pm = pct_re.search(line)
                    if pm:
                        prog = max(prog, float(pm.group(1)) / 100.0)
                    self._set(log=line, progress=prog, elapsed=time.time() - t_start)

            ret_code = self._proc.wait()
            self._proc = None
            total_seconds = time.time() - t_start

            if self._cancel:
                out_path.unlink(missing_ok=True)
                self._set(log="Réparation annulée.", done=True, busy=False,
                          result={"type": "repair", "cancelled": True, "images": []})
                return

            def _err_summary():
                err_lines = [l for l in last_lines if any(k in l.lower() for k in (
                    "error", "exception", "failed", "unknown", "invalid", "cannot", "abort"))]
                if err_lines:
                    return "\n".join(err_lines[-6:])
                return "\n".join(last_lines[-8:]) if last_lines else "Aucun message du moteur."

            if ret_code != 0:
                raise RuntimeError(
                    f"Le moteur sd-cli s'est arrêté avec le code d'erreur {ret_code} :\n"
                    f"{_err_summary()}")
            if not out_path.exists() or out_path.stat().st_size < 16 * 1024:
                raise RuntimeError(
                    f"Aucune image retouchée n'a été produite :\n{_err_summary()}")

            # Metadonnees : injecter une fiche minimale si le PNG n'en a pas
            try:
                txt = _pngmeta.build_webui_text(
                    prompt=(p.get("prompt") or "").strip(),
                    negative="", steps=int(m["defaults"]["steps"]), cfg=float(m["defaults"]["cfg"]),
                    seed=seed, sampler=m["defaults"].get("sampler", "euler"),
                    model_id=model_id)
                _pngmeta.embed_params(out_path, txt, only_if_missing=True)
            except Exception:
                pass

            out_dims = _png_size(out_path) or (0, 0)
            image_id = db.add_image(
                batch_id=uuid.uuid4().hex, idx=0,
                model_id=f"repair:{did}", model_name=f"🙂 {d['name']} · {m['name']}",
                quant=quant, prompt=(p.get("prompt") or "").strip(),
                negative="", seed=seed,
                width=out_dims[0], height=out_dims[1],
                steps=int(m["defaults"]["steps"]), cfg=float(m["defaults"]["cfg"]),
                sampler="adetailer", filename=out_name, batch_size=1,
                gen_time=round(total_seconds, 1), source_images=[src_rel])
            self._set(log=f"Réparation terminée ✓ ({src.name}) en {total_seconds:.1f}s",
                      progress=1.0, done=True, busy=False, error=None,
                      result={"type": "repair",
                              "images": [{"url": f"/output/{out_name}", "filename": out_name,
                                          "seed": seed, "id": image_id,
                                          "repaired": True}],
                              "cancelled": False})
        except Exception as e:
            self._set(error=str(e), log=f"Erreur: {e}", done=True, busy=False,
                      result={"type": "repair", "images": [], "error": str(e),
                              "cancelled": False})

    # --- Restauration ×2 par diffusion (mode -M vid_upscale, SeedVR2) ---
    def _run_seedvr2(self, p):
        try:
            import db
            st = seedvr2_status()
            if not st["downloaded"]:
                raise RuntimeError(
                    "SeedVR2 n'est pas installé. Ouvrez l'onglet Modèles → section "
                    "« 🩹 Restauration ×2 » (~6,8 Go).")
            sd = find_sd_cli()
            if not sd:
                raise RuntimeError("Le moteur sd-cli n'est pas installé. Allez dans l'onglet Modèles.")
            src_rel = p.get("source_image")
            src = (ROOT / src_rel) if src_rel else None
            if not src or not src.exists():
                raise RuntimeError("Image source introuvable sur le disque.")
            diff_path, vae_path = seedvr2_paths()

            seed = p.get("seed") or 42
            try:
                seed = int(seed)
            except (TypeError, ValueError):
                seed = 42

            stem = re.sub(r"[^a-zA-Z0-9_]", "_", src.stem.lower())[:40] or "image"
            out_name = f"restore_x2_{stem}_{uuid.uuid4().hex[:6]}.png"
            out_path = OUTPUT_DIR / out_name
            cmd = build_seedvr2_command(str(sd), str(src), str(out_path),
                                        diff_path, vae_path, upscale_factor=2, seed=seed)

            self._set(log=f"🩹 Restauration ×2 de « {src.name} » avec SeedVR2 (lent, ~6.8 Go de modèle)…",
                      progress=0.02, step=0, total_steps=0, error=None, done=False)

            creationflags = 0
            if os.name == "nt":
                creationflags = subprocess.CREATE_NO_WINDOW
            t_start = time.time()
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                bufsize=1, creationflags=creationflags)

            step_re = re.compile(r"step\s+(\d+)\s+(?:of|/)\s+(\d+)", re.I)
            pct_re = re.compile(r"(\d+(?:\.\d+)?)\s*%")
            last_lines = []
            for line in self._proc.stdout:
                if self._cancel:
                    break
                line = line.rstrip()
                if not line:
                    continue
                last_lines.append(line)
                last_lines = last_lines[-400:]
                prog = self.state.get("progress", 0.0)
                sm = step_re.search(line)
                if sm:
                    s, tot = int(sm.group(1)), int(sm.group(2))
                    self._set(step=s, total_steps=tot,
                              progress=min(1.0, s / max(1, tot)),
                              log=line, elapsed=time.time() - t_start)
                else:
                    pm = pct_re.search(line)
                    if pm:
                        prog = max(prog, float(pm.group(1)) / 100.0)
                    self._set(log=line, progress=prog, elapsed=time.time() - t_start)

            ret_code = self._proc.wait()
            self._proc = None
            total_seconds = time.time() - t_start

            if self._cancel:
                out_path.unlink(missing_ok=True)
                self._set(log="Restauration annulée.", done=True, busy=False,
                          result={"type": "restore_x2", "cancelled": True, "images": []})
                return

            def _err_summary():
                err_lines = [l for l in last_lines if any(k in l.lower() for k in (
                    "error", "exception", "failed", "unknown", "invalid", "cannot", "abort"))]
                if err_lines:
                    return "\n".join(err_lines[-6:])
                return "\n".join(last_lines[-8:]) if last_lines else "Aucun message du moteur."

            if ret_code != 0:
                raise RuntimeError(
                    f"Le moteur sd-cli s'est arrêté avec le code d'erreur {ret_code} :\n"
                    f"{_err_summary()}")
            if not out_path.exists() or out_path.stat().st_size < 16 * 1024:
                raise RuntimeError(
                    f"Aucune image restaurée n'a été produite :\n{_err_summary()}")

            try:
                txt = _pngmeta.build_webui_text(
                    prompt=f"Restauration ×2 de {src.name} (SeedVR2)", negative="",
                    steps=None, cfg=None, seed=seed, sampler="seedvr2",
                    model_id="seedvr2-3b")
                _pngmeta.embed_params(out_path, txt, only_if_missing=True)
            except Exception:
                pass

            out_dims = _png_size(out_path) or (0, 0)
            image_id = db.add_image(
                batch_id=uuid.uuid4().hex, idx=0,
                model_id="seedvr2", model_name="🩹 SeedVR2 (Restauration ×2)",
                quant="×2", prompt=f"Restauration ×2 de {src.name}",
                negative="", seed=seed,
                width=out_dims[0], height=out_dims[1],
                steps=0, cfg=0.0, sampler="seedvr2", filename=out_name, batch_size=1,
                gen_time=round(total_seconds, 1), source_images=[src_rel])
            self._set(log=f"Restauration ×2 terminée ✓ ({src.name}) en {total_seconds:.1f}s",
                      progress=1.0, done=True, busy=False, error=None,
                      result={"type": "restore_x2",
                              "images": [{"url": f"/output/{out_name}", "filename": out_name,
                                          "seed": seed, "id": image_id,
                                          "upscaled": True, "scale": 2}],
                              "cancelled": False})
        except Exception as e:
            self._set(error=str(e), log=f"Erreur: {e}", done=True, busy=False,
                      result={"type": "restore_x2", "images": [], "error": str(e),
                              "cancelled": False})

    def _run_pid(self, p):
        try:
            import db
            st = pid_status()
            if not st["downloaded"]:
                raise RuntimeError(
                    "PiD n'est pas installé. Ouvrez l'onglet Modèles → section "
                    "« ⬆️ PiD ×4 » (socle commun ~5,4 Go + ~1,6 Go par backbone).")
            sd = find_sd_cli()
            if not sd:
                raise RuntimeError("Le moteur sd-cli n'est pas installé. Allez dans l'onglet Modèles.")
            src_rel = p.get("source_image")
            src = (ROOT / src_rel) if src_rel else None
            if not src or not src.exists():
                raise RuntimeError("Image source introuvable sur le disque.")

            # --- Retrouve l'image d'origine dans l'historique (prompt + famille) ---
            img_id = p.get("image_id")
            src_image = None
            if img_id not in (None, ""):
                try:
                    src_image = db.get_image(int(img_id))
                except Exception:
                    src_image = None

            # --- Choix du backbone : explicite > famille du modèle source > premier dispo ---
            backbone = (p.get("backbone") or "").strip()
            if backbone and backbone not in PID["backbones"]:
                raise RuntimeError(f"Backbone PiD inconnu : {backbone}")
            ready = st["ready_backbones"]
            if backbone:
                if not st["backbones"][backbone]["ready"]:
                    bb = st["backbones"][backbone]
                    missing = []
                    if not st["shared"]["ready"]:
                        missing.append("socle commun (Gemma 2 2B + tokenizer)")
                    if not bb["model"]:
                        missing.append("modèle int8 du backbone")
                    if not bb["vae"]:
                        missing.append(f"VAE « {bb['vae_dep']} »")
                    raise RuntimeError(
                        "PiD (" + backbone + ") n'est pas complet : il manque "
                        + ", ".join(missing) + ". Ouvrez l'onglet Modèles → « ⬆️ PiD ×4 ».")
            else:
                arch = None
                if src_image:
                    src_model = MODELS.get(src_image.get("model_id") or "")
                    arch = (src_model or {}).get("arch")
                pref = pid_backbone_for_arch(arch)
                backbone = pref if (pref and pref in ready) else (ready[0] if ready else None)
                if not backbone:
                    raise RuntimeError(
                        "Aucun backbone PiD utilisable n'est installé. Ouvrez l'onglet Modèles → « ⬆️ PiD ×4 ».")

            bb = PID["backbones"][backbone]
            vae_path = pid_vae_path(backbone)
            if not vae_path or not vae_path.exists() or vae_path.stat().st_size < 1024 * 1024:
                raise RuntimeError(
                    f"VAE requis introuvable : {vae_path}. Relancez le téléchargement « ⬆️ PiD ×4 » "
                    "dans l'onglet Modèles (ou installez le modèle de la famille correspondante).")

            # --- Prompt : celui de l'image source (historique) sinon défaut qualité ---
            prompt = (p.get("prompt") or "").strip()
            if not prompt and src_image:
                prompt = (src_image.get("prompt") or "").strip()
            if not prompt:
                prompt = pid_default_prompt()

            seed = p.get("seed") or 42
            try:
                seed = int(seed)
            except (TypeError, ValueError):
                seed = 42

            out_size = int(PID.get("output_size") or 4096)
            stem = re.sub(r"[^a-zA-Z0-9_]", "_", src.stem.lower())[:40] or "image"
            out_name = f"pid_{backbone}_{stem}_{uuid.uuid4().hex[:6]}.png"
            out_path = OUTPUT_DIR / out_name
            cmd = build_pid_command(str(sd), str(src), str(out_path),
                                    pid_model_path(backbone), pid_gemma_path(),
                                    pid_tokenizer_path(), vae_path,
                                    bb["vae_format"], prompt, seed=seed,
                                    width=out_size, height=out_size)

            self._set(log=f"⬆️ PiD ×4 de « {src.name} » ({bb['label']}, 4 étapes, sortie {out_size}×{out_size})…",
                      progress=0.02, step=0, total_steps=0, error=None, done=False)

            creationflags = 0
            if os.name == "nt":
                creationflags = subprocess.CREATE_NO_WINDOW
            t_start = time.time()
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                bufsize=1, creationflags=creationflags)

            step_re = re.compile(r"step\s+(\d+)\s+(?:of|/)\s+(\d+)", re.I)
            pct_re = re.compile(r"(\d+(?:\.\d+)?)\s*%")
            last_lines = []
            for line in self._proc.stdout:
                if self._cancel:
                    break
                line = line.rstrip()
                if not line:
                    continue
                last_lines.append(line)
                last_lines = last_lines[-400:]
                prog = self.state.get("progress", 0.0)
                sm = step_re.search(line)
                if sm:
                    s, tot = int(sm.group(1)), int(sm.group(2))
                    self._set(step=s, total_steps=tot,
                              progress=min(1.0, s / max(1, tot)),
                              log=line, elapsed=time.time() - t_start)
                else:
                    pm = pct_re.search(line)
                    if pm:
                        prog = max(prog, float(pm.group(1)) / 100.0)
                    self._set(log=line, progress=prog, elapsed=time.time() - t_start)

            ret_code = self._proc.wait()
            self._proc = None
            total_seconds = time.time() - t_start

            if self._cancel:
                out_path.unlink(missing_ok=True)
                self._set(log="PiD annulée.", done=True, busy=False,
                          result={"type": "pid", "cancelled": True, "images": []})
                return

            def _err_summary():
                err_lines = [l for l in last_lines if any(k in l.lower() for k in (
                    "error", "exception", "failed", "unknown", "invalid", "cuda", "cannot", "abort"))]
                if err_lines:
                    return "\n".join(err_lines[-6:])
                return "\n".join(last_lines[-8:]) if last_lines else "Aucun message du moteur."

            if ret_code != 0:
                raise RuntimeError(
                    f"Le moteur sd-cli s'est arrêté avec le code d'erreur {ret_code} :\n"
                    f"{_err_summary()}\n\n💡 PiD décode en {out_size}×{out_size} (pixel-space) : "
                    "si la VRAM est insuffisante, utilisez plutôt 🩹 Restaurer ×2 (SeedVR2) ou 🔍 Agrandir ×4.")
            if not out_path.exists() or out_path.stat().st_size < 16 * 1024:
                raise RuntimeError(
                    f"Aucune image PiD n'a été produite :\n{_err_summary()}")

            try:
                txt = _pngmeta.build_webui_text(
                    prompt=prompt, negative="",
                    steps=4, cfg=1.0, seed=seed, sampler="pid",
                    model_id=f"pid_{backbone}")
                _pngmeta.embed_params(out_path, txt, only_if_missing=True)
            except Exception:
                pass

            out_dims = _png_size(out_path) or (out_size, out_size)
            image_id = db.add_image(
                batch_id=uuid.uuid4().hex, idx=0,
                model_id=f"pid_{backbone}", model_name=f"⬆️ PiD ×4 ({bb['label']})",
                quant="×4", prompt=prompt,
                negative="", seed=seed,
                width=out_dims[0], height=out_dims[1],
                steps=4, cfg=1.0, sampler="pid", filename=out_name, batch_size=1,
                gen_time=round(total_seconds, 1), source_images=[src_rel])
            self._set(log=f"PiD ×4 terminée ✓ ({src.name} → {bb['label']}) en {total_seconds:.1f}s",
                      progress=1.0, done=True, busy=False, error=None,
                      result={"type": "pid",
                              "backbone": backbone,
                              "images": [{"url": f"/output/{out_name}", "filename": out_name,
                                          "seed": seed, "id": image_id,
                                          "upscaled": True, "scale": 4}],
                              "cancelled": False})
        except Exception as e:
            self._set(error=str(e), log=f"Erreur: {e}", done=True, busy=False,
                      result={"type": "pid", "images": [], "error": str(e),
                              "cancelled": False})


# instance globale
tasks = TaskManager()
