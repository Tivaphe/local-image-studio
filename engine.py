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
from pathlib import Path
from urllib.request import urlopen, Request

from config import (ROOT, BIN_DIR, DIFFUSION_DIR, OUTPUT_DIR, find_sd_cli)
from registry import (MODELS, DEPS, DEP_QUANT_PRIORITY, resolve_dep_gguf,
                      load_manifest, save_manifest, build_command)


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


def _model_present(model_id, quant) -> bool:
    m = MODELS[model_id]
    ok = (DIFFUSION_DIR / m["file_for_quant"][quant]).exists()
    if "uncond_file_for_quant" in m:
        ok = ok and (DIFFUSION_DIR / m["uncond_file_for_quant"][quant]).exists()
    return ok


def _dep_present(dep_id) -> bool:
    """Une dépendance est présente si elle est dans le manifeste ET le fichier existe."""
    mf = load_manifest()
    info = mf.get(dep_id) or {}
    return bool(info.get("path") and Path(info["path"]).exists())


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


def download_model(model_id, quant, token, msg_cb=None):
    """Télécharge le modèle GGUF (choisi) + ses dépendances."""
    m = MODELS[model_id]
    # 1) dépendances
    for d in m["deps"]:
        ensure_dep(d, token, msg_cb)
    # 2) transformer principal
    if not _model_present(model_id, quant):
        file = m["file_for_quant"][quant]
        if msg_cb:
            msg_cb(f"Téléchargement du modèle {file}")
        _hf_download_file(m["repo"], file,
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
                          "done": False, "result": None}

    def is_busy(self):
        with self._lock:
            return self.state["busy"]

    def snapshot(self):
        with self._lock:
            return dict(self.state)

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

    def start_generate(self, params):
        if self.is_busy():
            raise RuntimeError("Une tâche est déjà en cours.")
        self._reset("generate")
        self._cancel = False
        t = threading.Thread(target=self._run_generate, args=(params,), daemon=True)
        self._thread = t
        t.start()

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

            # Vérification spécifique pour Qwen-Image-2.1 avec édition
            if model_id == "qwen-image-2.1" and p.get("source_image"):
                mmproj_path = _dep_path(manifest, "mmproj_qwen3vl_8b")
                if not mmproj_path or not Path(mmproj_path).exists():
                    raise RuntimeError(
                        "Pour éditer avec Qwen-Image-2.1, le fichier mmproj est requis. "
                        "Il n'est pas dans les dépendances standard. "
                        "Téléchargez-le manuellement depuis: "
                        "https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct-GGUF/resolve/main/mmproj-Qwen3VL-8B-Instruct-F16.gguf "
                        "dans le dossier models/llm/"
                    )
                # Vérifier que l'image source existe
                source_path = Path(p["source_image"])
                if not source_path.exists():
                    raise RuntimeError(f"Image source introuvable: {p['source_image']}")

            batch = max(1, min(4, int(p["batch"])))
            batch_id = f"{int(time.time())}_{model_id}"
            out_prefix = OUTPUT_DIR / batch_id
            out_prefix.mkdir(parents=True, exist_ok=True)
            out_tmpl = str(out_prefix / "img_%03d.png")
            seed = int(p["seed"]) if p.get("seed") not in (None, "") else int(time.time()) % 1000000

            cmd = build_command(
                model_id, quant, p["prompt"], p.get("negative", ""),
                int(p["width"]), int(p["height"]), int(p["steps"]), float(p["cfg"]),
                seed, batch, out_tmpl, str(sd), manifest,
                source_image=p.get("source_image"),
                lora_dir=p.get("lora_dir"),
                strength=p.get("strength"))

            self._set(log="Démarrage de la génération…",
                      total_steps=int(p["steps"]), step=0)

            creationflags = 0
            if os.name == "nt":
                creationflags = subprocess.CREATE_NO_WINDOW

            t_start = time.time()          # FIX 3 : chrono du moment où on lance
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
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

            self._proc.wait()
            self._proc = None
            t_end = time.time()
            total_seconds = t_end - t_start
            denoise_seconds = (t_end - t_first_step) if t_first_step else total_seconds
            per_step = (denoise_seconds / max(1, last_step_seen)) if last_step_seen else 0

            if self._cancel:
                self._set(log="Génération annulée.", done=True, busy=False,
                          result={"type": "generate", "cancelled": True, "images": []})
                return

            # collecte des images produites
            produced = sorted(out_prefix.glob("img_*.png"))
            if not produced:
                # fallback : n'importe quel png récent dans le dossier
                produced = sorted(out_prefix.glob("*.png"))
            images = []
            for i, fp in enumerate(produced):
                rel = fp.relative_to(OUTPUT_DIR).as_posix()
                db.add_image(
                    batch_id=batch_id, idx=i, model_id=model_id, model_name=m["name"],
                    quant=quant, prompt=p["prompt"], negative=p.get("negative", ""),
                    seed=seed + i, width=int(p["width"]), height=int(p["height"]),
                    steps=int(p["steps"]), cfg=float(p["cfg"]),
                    sampler=m["defaults"]["sampler"], filename=rel, batch_size=batch,
                    gen_time=round(total_seconds / max(1, len(produced)), 1))
                images.append({"url": f"/output/{rel}", "filename": rel,
                               "seed": seed + i, "id": None})

            # récupère les ids depuis la DB (derniers insérés du batch)
            rows = db.list_images(limit=len(produced))
            for img, row in zip(images, rows):
                img["id"] = row["id"]

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
                      progress=1.0, done=True, busy=False,
                      result={"type": "generate", "images": images,
                              "batch_id": batch_id, "cancelled": False,
                              "stats": stats})
        except Exception as e:
            self._set(error=str(e), log=f"Erreur: {e}", done=True, busy=False)


# instance globale
tasks = TaskManager()
