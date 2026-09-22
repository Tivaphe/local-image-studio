# -*- coding: utf-8 -*-
"""
Configuration des chemins du projet Local Image Studio.
Tous les chemins sont relatifs au dossier du projet.
"""
import os
import platform
from pathlib import Path

# Racine du projet = dossier contenant ce fichier
ROOT = Path(__file__).resolve().parent

# --- Dossiers ---
BIN_DIR        = ROOT / "bin"            # exécutable sd-cli.exe + DLLs
MODELS_DIR     = ROOT / "models"         # poids des modèles
DIFFUSION_DIR  = MODELS_DIR / "diffusion"
VAE_DIR        = MODELS_DIR / "vae"
TEXTENC_DIR    = MODELS_DIR / "textenc"
LLM_DIR        = MODELS_DIR / "llm"
LORAS_DIR      = MODELS_DIR / "loras"    # poids LoRA (safetensors)
SOURCE_IMAGES_DIR = ROOT / "source_images"  # images pour img2img
OUTPUT_DIR     = ROOT / "output"         # images générées (auto-save)

DB_PATH        = ROOT / "history.db"
SETTINGS_PATH  = ROOT / "settings.json"
MANIFEST_PATH  = MODELS_DIR / "manifest.json"

# --- Exécutable stable-diffusion.cpp ---
_IS_WIN = platform.system() == "Windows"
if _IS_WIN:
    SD_CLI_NAMES = ["sd-cli.exe", "sd.exe"]
else:
    SD_CLI_NAMES = ["sd-cli", "sd"]


def find_sd_cli() -> Path | None:
    """Retourne le chemin de l'exécutable sd-cli s'il est présent dans bin/."""
    for name in SD_CLI_NAMES:
        p = BIN_DIR / name
        if p.exists():
            return p
    # recherche récursive dans bin/ (au cas où l'archive aurait un sous-dossier)
    if BIN_DIR.exists():
        for name in SD_CLI_NAMES:
            hits = list(BIN_DIR.rglob(name))
            if hits:
                return hits[0]
    return None


# Création des dossiers de base
for _d in (BIN_DIR, MODELS_DIR, DIFFUSION_DIR, VAE_DIR, TEXTENC_DIR, LLM_DIR, LORAS_DIR, SOURCE_IMAGES_DIR, OUTPUT_DIR):
    _d.mkdir(parents=True, exist_ok=True)
