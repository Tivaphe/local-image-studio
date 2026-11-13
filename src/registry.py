# -*- coding: utf-8 -*-
"""
Registre des modeles + dependances partagees.
- Chaque modele indique ses fichiers de poids par variante (GGUF ou safetensors).
- Les dependances (VAE, encodeurs de texte) sont telechargees une seule fois.
- build_command() construit la ligne de commande sd-cli adaptee a chaque modele.
"""
import json
import re
from pathlib import Path

from config import (DIFFUSION_DIR, VAE_DIR, TEXTENC_DIR, LLM_DIR, UPSCALE_DIR,
                    ADETAILER_DIR, SEEDVR2_DIR, TAESD_DIR, PULID_DIR,
                    PORTRAITS_DIR, PID_DIR, MANIFEST_PATH)


# --------------------------------------------------------------------------- #
#  Modeles d'Upscaling (Super-Resolution ESRGAN / MoSR pour sd-cli)
# --------------------------------------------------------------------------- #
UPSCALERS = {
    "realesrgan-x4plus": {
        "id": "realesrgan-x4plus",
        "name": "RealESRGAN ×4 Plus (Photo & Généraliste)",
        "short_label": "📸 Photo & Généraliste ×4 (RealESRGAN)",
        "filename": "RealESRGAN_x4plus.pth",
        "url": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth",
        "size_mb": 64,
        "scale": 4,
        "desc": (
            "Modèle ×4 polyvalent de référence (64 Mo) : multiplie la résolution par 4 "
            "(ex. 1024×1024 → 4096×4096) et renforce la netteté des photos, portraits et paysages."
        ),
    },
    "4x-nomos2-hq": {
        "id": "4x-nomos2-hq",
        "name": "4× Nomos2 HQ MoSR (Textures naturelles)",
        "short_label": "✨ Textures naturelles ×4 (Nomos2 MoSR)",
        "filename": "4xNomos2_hq_mosr.pth",
        "url": "https://github.com/Phhofm/models/releases/download/4xNomos2_hq_mosr/4xNomos2_hq_mosr.pth",
        "size_mb": 35,
        "scale": 4,
        "desc": (
            "Architecture MoSR PixelShuffle prise en charge nativement par sd-cli (35 Mo) : "
            "préserve le grain de peau, les cheveux, le tissu et les micro-détails sans effet plastique."
        ),
    },
    "4x-ultrasharp": {
        "id": "4x-ultrasharp",
        "name": "4× UltraSharp (Détails & netteté)",
        "short_label": "🔪 UltraSharp ×4 (détails & netteté)",
        "filename": "4x-UltraSharp.pth",
        "url": "https://huggingface.co/Kim2091/UltraSharp/resolve/main/4x-UltraSharp.pth",
        "size_mb": 64,
        "scale": 4,
        "desc": (
            "Le plus populaire des agrandisseurs « détails » (64 Mo, Kim2091) : micro-textures "
            "(peau, tissu, cheveux, artefacts de compression JPEG) — idéal sur photos et rendus IA. "
            "Licence CC-BY-NC-SA-4.0 : usage privé/non-commercial."
        ),
    },
    "4x-ultramix-balanced": {
        "id": "4x-ultramix-balanced",
        "name": "4× UltraMix Balanced (UltraSharp adouci)",
        "short_label": "⚖️ UltraMix Balanced ×4 (UltraSharp adouci)",
        "filename": "4x-UltraMix_Balanced.pth",
        "url": "https://huggingface.co/Kim2091/UltraSharp/resolve/main/Interpolations/4x-UltraMix_Balanced.pth",
        "size_mb": 64,
        "scale": 4,
        "desc": (
            "Variante interpolée « équilibrée » d'UltraSharp (64 Mo, Kim2091) : moins agressive que "
            "l'UltraSharp — moins de micro-textures fantasques, bon compromis pour portraits et scènes "
            "denses. Licence CC-BY-NC-SA-4.0 : usage privé/non-commercial."
        ),
    },
    "4x-remacri": {
        "id": "4x-remacri",
        "name": "4× Remacri (Photo — grain naturel)",
        "short_label": "🎞️ Remacri ×4 (grain naturel)",
        "filename": "4x_foolhardy_Remacri.gguf",
        "url": "https://huggingface.co/wbruna/upscalers-sdcpp-gguf/resolve/main/4x_foolhardy_Remacri.gguf",
        "size_mb": 64,
        "scale": 4,
        "desc": (
            "Le préféré des photographes pour garder un grain crédible (64 Mo, FoolhardyVEVO) : "
            "peau, tissu et ciel sans aspect « plastique ». Fourni en GGUF converti par "
            "stable-diffusion.cpp lui-même — poids inchangés, licence CC-BY-NC-SA-4.0 conservée "
            "(usage privé/non-commercial)."
        ),
    },
    "realesrgan-anime-6b": {
        "id": "realesrgan-anime-6b",
        "name": "RealESRGAN ×4 Anime 6B (Illustration & Dessin)",
        "short_label": "🎨 Illustration & Anime ×4 (Anime 6B)",
        "filename": "RealESRGAN_x4plus_anime_6B.pth",
        "url": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth",
        "size_mb": 17,
        "scale": 4,
        "desc": (
            "Ultra-léger (17 Mo) et très rapide : idéal pour les illustrations, l'anime, "
            "le concept art, les bandes dessinées et les affiches à contours nets."
        ),
    },
}


def upscaler_path(upscaler_id: str) -> Path | None:
    u = UPSCALERS.get(upscaler_id)
    if not u:
        return None
    return UPSCALE_DIR / u["filename"]


def upscaler_status(upscaler_id: str) -> dict:
    u = UPSCALERS.get(upscaler_id)
    if not u:
        return {"downloaded": False, "path": None}
    p = UPSCALE_DIR / u["filename"]
    ok = p.exists() and p.is_file() and p.stat().st_size > 1024 * 100
    return {"downloaded": ok, "path": str(p) if ok else None}


# --------------------------------------------------------------------------- #
#  Detecteurs ADetailer (YOLOv8 convertis en safetensors pour sd-cli)
#  Repo HF exeterminal/adetailer-yolov8-safetensors : poids Bingsu/adetailer
#  convertis avec scripts/convert_yolov8_to_safetensors.py de stable-diffusion.cpp.
# --------------------------------------------------------------------------- #
ADETAILERS = {
    "face_yolov8n": {
        "id": "face_yolov8n",
        "name": "Visages (YOLOv8n — rapide)",
        "short_label": "😊 Visages (rapide)",
        "filename": "face_yolov8n.safetensors",
        "repo": "exeterminal/adetailer-yolov8-safetensors",
        "size_mb": 6,
        "desc": (
            "Détecteur de visages léger (~6 Mo) : repère chaque visage de l'image puis "
            "le re-détaille avec votre modèle pour corriger les yeux, les dents et les sourires."
        ),
    },
    "face_yolov8s": {
        "id": "face_yolov8s",
        "name": "Visages (YOLOv8s — précis)",
        "short_label": "😊 Visages (précis)",
        "filename": "face_yolov8s.safetensors",
        "repo": "exeterminal/adetailer-yolov8-safetensors",
        "size_mb": 22,
        "desc": (
            "Version « small » plus fiable (~22 Mo) : à préférer pour les portraits de loin, "
            "les groupes de personnes ou les visages partiellement cachés."
        ),
    },
    "hand_yolov8n": {
        "id": "hand_yolov8n",
        "name": "Mains (YOLOv8n)",
        "short_label": "🖐 Mains",
        "filename": "hand_yolov8n.safetensors",
        "repo": "exeterminal/adetailer-yolov8-safetensors",
        "size_mb": 6,
        "desc": (
            "Détecteur de mains (~6 Mo) : corrige doigts et proportions, le point faible "
            "classique des modèles de génération."
        ),
    },
}


def adetailer_path(detector_id: str) -> Path | None:
    d = ADETAILERS.get(detector_id)
    if not d:
        return None
    return ADETAILER_DIR / d["filename"]


def adetailer_status(detector_id: str) -> dict:
    d = ADETAILERS.get(detector_id)
    if not d:
        return {"downloaded": False, "path": None}
    p = ADETAILER_DIR / d["filename"]
    ok = p.exists() and p.is_file() and p.stat().st_size > 16 * 1024
    return {"downloaded": ok, "path": str(p) if ok else None}


# --------------------------------------------------------------------------- #
#  Restauration SeedVR2 (super-resolution par diffusion, mode -M vid_upscale)
#  Poids officiels Comfy-Org/SeedVR2 ; operation autonome sur une image (x2).
#  Experimental : resultats plus « naturels » qu'ESRGAN sur les photos vieilles
#  ou degradees, mais beaucoup plus lourd (plusieurs Go, modele DiT 3B).
# --------------------------------------------------------------------------- #
SEEDVR2 = {
    "id": "seedvr2-3b",
    "name": "SeedVR2 3B (Restauration ×2)",
    "short_label": "🩹 SeedVR2 ×2 (restauration photo)",
    "scale": 2,
    "size_gb": 6.8,
    "desc": (
        "Modèle de restauration par diffusion (ByteDance SeedVR2, ~6.8 Go) : agrandit ×2 "
        "en reconstruisant de la matière crédible — visages, grain de peau, tissus — là où "
        "un ESRGAN classique se contente de « lisser ». Idéal pour sauver les vieilles photos "
        "et les images très compressées. Expérimental : plus lent et plus lourd qu'un ×4 classique."
    ),
    "repo": "Comfy-Org/SeedVR2",
    "hf_url": "https://huggingface.co/Comfy-Org/SeedVR2",
    "needs_token": False,
    "files": {
        "diffusion": {"filename": "seedvr2_3b_int8_convrot.safetensors", "size_mb": 4000},
        "vae":       {"filename": "seedvr2_ema_vae_fp16.safetensors",   "size_mb": 300},
    },
}


def seedvr2_paths() -> list[Path]:
    """Chemins attendus [diffusion, vae] des poids SeedVR2 (telecharges ou non)."""
    return [SEEDVR2_DIR / SEEDVR2["files"]["diffusion"]["filename"],
            SEEDVR2_DIR / SEEDVR2["files"]["vae"]["filename"]]


def seedvr2_status() -> dict:
    diff_p, vae_p = seedvr2_paths()
    diff_ok = diff_p.exists() and diff_p.stat().st_size > 1024 * 1024
    vae_ok = vae_p.exists() and vae_p.stat().st_size > 1024 * 1024
    return {"downloaded": diff_ok and vae_ok,
            "diffusion": diff_ok,
            "vae": vae_ok,
            "paths": [str(p) for p in (diff_p, vae_p)] if (diff_ok and vae_ok) else None}


# --------------------------------------------------------------------------- #
#  PiD — NVIDIA Pixel Diffusion (super-résolution GÉNÉRATIVE ×4, 1024 → 4096)
#  PiD ré-encode l'image avec le VAE du backbone puis la décode directement en
#  pixels 4096×4096 en 4 étapes (diffusion pixel-space conditionnée par le
#  prompt). sd-cli ≥ 2026-05-31 requis (docs/pid.md : -r <image> + --vae-format).
#
#  Poids : safetensors du dépôt NON-gated Comfy-Org/PixelDiT (repack des
#  checkpoints officiels nvidia/PiD). Le tokenizer Gemma 2 (tokenizer.json)
#  provient du miroir NON-gated unsloth/gemma-2-2b-it (le dépôt officiel
#  google/gemma-2-2b est gated — connexion Google requise, évitée ici).
#  ⚠️ Licence NSCLv1 : recherche / évaluation NON-commerciale uniquement.
# --------------------------------------------------------------------------- #
PID = {
    "id": "pid",
    "name": "PiD 1.5 (NVIDIA Pixel Diffusion ×4)",
    "short_label": "⬆️ PiD ×4 (super-résolution générative)",
    "license": "NSCLv1 — non-commerciale (recherche / usage personnel)",
    "repo": "Comfy-Org/PixelDiT",
    "hf_url": "https://huggingface.co/Comfy-Org/PixelDiT",
    "tokenizer_repo": "unsloth/gemma-2-2b-it",
    "steps": 4,
    "cfg": 1.0,
    "output_size": 4096,
    "desc": (
        "Super-résolution générative conditionnée par le prompt (NVIDIA PiD 1.5, 4 étapes, "
        "1024→4096) : ré-encode l'image avec le VAE du backbone puis la décode en pixels "
        "4096×4096 — reconstruit des détails crédibles (peau, tissu, texte) là où un ESRGAN "
        "se contente de lisser. Backbones : FLUX.1, FLUX.2, Qwen-Image. "
        "⚠️ Licence NSCLv1 (non-commerciale). ~1,6 Go par backbone (int8) + socle commun "
        "~5,4 Go (encodeur Gemma 2 2B bf16 + tokenizer, dépôts non-gated)."
    ),
    # Socle commun aux trois backbones (téléchargé une seule fois)
    "gemma": {
        "repo": "Comfy-Org/PixelDiT",
        "filename": "text_encoders/gemma_2_2b_it_elm_bf16.safetensors",
        "dest_name": "gemma_2_2b_it_elm_bf16.safetensors",
        "size_mb": 5356,
    },
    "tokenizer": {
        "repo": "unsloth/gemma-2-2b-it",
        "filename": "tokenizer.json",
        "dest_name": "tokenizer_gemma2.json",
        "size_mb": 18,
    },
    "backbones": {
        "flux1": {
            "id": "flux1",
            "label": "FLUX.1",
            "label_long": "FLUX.1 — Dev / Schnell / Kontext / Chroma / Z-Image",
            "filename": "pid_1.5_flux1_1024_to_4096_4step_int8_convrot.safetensors",
            "repo_filename": "diffusion_models/pid_1.5_flux1_1024_to_4096_4step_int8_convrot.safetensors",
            "size_mb": 1620,
            "vae_format": "flux",
            "vae_dep": "vae_flux",          # models/vae/ae.safetensors (0,32 Go)
            "arches": ["flux", "flux_kontext", "chroma", "zimage"],
        },
        "flux2": {
            "id": "flux2",
            "label": "FLUX.2",
            "label_long": "FLUX.2 — Klein 4B / 9B",
            "filename": "pid_1.5_flux2_1024_to_4096_4step_int8_convrot.safetensors",
            "repo_filename": "diffusion_models/pid_1.5_flux2_1024_to_4096_4step_int8_convrot.safetensors",
            "size_mb": 1630,
            "vae_format": "flux2",
            "vae_dep": "vae_flux2",         # models/vae/flux2-vae.safetensors (0,25 Go)
            "arches": ["flux2"],
        },
        "qwenimage": {
            "id": "qwenimage",
            "label": "Qwen-Image",
            "label_long": "Qwen-Image — 2508 / 2512 (VAE Wan 2D)",
            "filename": "pid_1.5_qwenimage_1024_to_4096_4step_int8_convrot.safetensors",
            "repo_filename": "diffusion_models/pid_1.5_qwenimage_1024_to_4096_4step_int8_convrot.safetensors",
            "size_mb": 1620,
            "vae_format": "wan",
            "vae_dep": "vae_qwen",          # models/vae/qwen_image_vae.safetensors (0,27 Go)
            "arches": ["qwen_image"],
        },
    },
}

# Correspondance famille de modèle (arch MODELS) → backbone PiD
PID_ARCH_TO_BACKBONE = {}
for _bb_id, _bb in PID["backbones"].items():
    for _arch in _bb["arches"]:
        PID_ARCH_TO_BACKBONE[_arch] = _bb_id

_DEFAULT_PID_PROMPT = ("masterpiece, best quality, ultra detailed, sharp focus, "
                       "professional photography, highly detailed textures")


def pid_gemma_path() -> Path:
    return PID_DIR / PID["gemma"]["dest_name"]


def pid_tokenizer_path() -> Path:
    return PID_DIR / PID["tokenizer"]["dest_name"]


def pid_model_path(backbone: str) -> Path:
    return PID_DIR / PID["backbones"][backbone]["filename"]


def pid_vae_path(backbone: str) -> Path | None:
    """VAE requis par le backbone (réutilise les dépôts/chemins de DEPS)."""
    dep = DEPS.get(PID["backbones"][backbone]["vae_dep"])
    dest = dep.get("dest") if dep else None
    return Path(dest) if dest is not None else None


# Seuils de taille pour valider un fichier PiD (patchables en test)
PID_GEMMA_MIN_BYTES = 1024 * 1024 * 1024
PID_TOKENIZER_MIN_BYTES = 1024 * 1024
PID_MODEL_MIN_BYTES = 512 * 1024 * 1024
PID_VAE_MIN_BYTES = 1024 * 1024


def _pid_shared_status() -> dict:
    gemma_p, tok_p = pid_gemma_path(), pid_tokenizer_path()
    gemma_ok = gemma_p.exists() and gemma_p.stat().st_size > PID_GEMMA_MIN_BYTES
    tok_ok = tok_p.exists() and tok_p.stat().st_size > PID_TOKENIZER_MIN_BYTES
    return {"gemma": gemma_ok, "tokenizer": tok_ok,
            "ready": gemma_ok and tok_ok,
            "gemma_path": str(gemma_p) if gemma_ok else None,
            "tokenizer_path": str(tok_p) if tok_ok else None}


def pid_backbone_ready(backbone: str) -> bool:
    bb = PID["backbones"].get(backbone)
    if not bb:
        return False
    shared = _pid_shared_status()
    model_p = pid_model_path(backbone)
    vae_p = pid_vae_path(backbone)
    model_ok = model_p.exists() and model_p.stat().st_size > PID_MODEL_MIN_BYTES
    vae_ok = bool(vae_p) and vae_p.exists() and vae_p.stat().st_size > PID_VAE_MIN_BYTES
    return shared["ready"] and model_ok and vae_ok


def pid_status() -> dict:
    """État d'installation PiD : socle commun + par backbone."""
    shared = _pid_shared_status()
    backbones = {}
    ready = []
    for bb_id, bb in PID["backbones"].items():
        model_p = pid_model_path(bb_id)
        vae_p = pid_vae_path(bb_id)
        model_ok = model_p.exists() and model_p.stat().st_size > PID_MODEL_MIN_BYTES
        vae_ok = bool(vae_p) and vae_p.exists() and vae_p.stat().st_size > PID_VAE_MIN_BYTES
        ok = shared["ready"] and model_ok and vae_ok
        backbones[bb_id] = {
            "model": model_ok, "vae": vae_ok, "ready": ok,
            "size_mb": bb["size_mb"],
            "vae_format": bb["vae_format"],
            "vae_dep": bb["vae_dep"],
        }
        if ok:
            ready.append(bb_id)
    return {"downloaded": bool(ready),
            "shared": shared,
            "backbones": backbones,
            "ready_backbones": ready}


def pid_backbone_for_arch(arch: str | None) -> str | None:
    """Famille de modèle → backbone PiD (None si non applicable)."""
    if not arch:
        return None
    return PID_ARCH_TO_BACKBONE.get(arch)


def pid_default_prompt() -> str:
    return _DEFAULT_PID_PROMPT


# Marqueurs de prompts qui décrivent une *instruction* (édition / retouche / traitement)
# plutôt que le contenu de l'image. PiD étant une super-résolution GÉNÉRATIVE conditionnée
# par le prompt, un tel texte biaise la reconstruction : on lui préfère alors la description
# générique de qualité. Liste volontairement conservatrice (les faux positifs retombent sur
# la description générique, ce qui est sûr — jamais sur un prompt d'édition).
_EDIT_INSTRUCTION_MARKERS = (
    "<image", "{img", "image 1", "image 2", "image 3", "image1", "image2",
    "keep the subject", "keep the face", "keep his", "keep her", "keep the woman",
    "keep the man", "keep the pose", "keep the composition", "keep the identity",
    "garder le sujet", "garde le sujet", "garde sa", "garder sa",
    "garde la composition", "garde le visage",
    "préserve le", "preserver le", "preserve the",
    "redraw", "redessine", "re-design", "re-render", "rerender",
    "replace the", "remplace le", "remplace la", "remplace les", "remplacez",
    "only change", "change only", "juste change",
    "change the", "modifie le", "modifie la", "modifie les",
    "inpaint", "outpaint", "extend the frame", "étendre le cadre", "étends le cadre",
    "fill the mask", "remplis le masque", "masque",
    "post-traitement", "post-processing", "postprocess", "post-process",
    "combine image", "fusionne les images", "with reference", "en gardant",
)


def prompt_looks_like_edit_instruction(prompt: str) -> bool:
    """True si le prompt ressemble à une *instruction d'édition/retouche* et non à
    une description du contenu visuel. Sert à éviter de conditionner PiD par erreur."""
    p = (prompt or "").strip().lower()
    if not p:
        return False
    return any(marker in p for marker in _EDIT_INSTRUCTION_MARKERS)


# --------------------------------------------------------------------------- #
#  Légendeurs d'image → prompt (VLM GGUF pour llama.cpp)
# --------------------------------------------------------------------------- #
# Prompt envoyé aux VLMs pour produire un prompt de text-to-image. Volontairement
# en anglais (les modèles de la famille y sont entraînés), en sortie unique,
# sans négatif ni balisage. Éditable dans Paramètres → « Légende d'image ».
CAPTION_DEFAULT_PROMPT = (
    "You are an expert prompt writer for text-to-image diffusion models.\n"
    "Describe the image as a single dense English text-to-image prompt. Include: "
    "the main subject(s) and their appearance, action and pose; the setting or "
    "background; lighting; composition and framing (wide shot, close-up, rule of "
    "thirds...); the medium and style (photograph, oil painting, anime, 3D render, "
    "watercolor...); the color palette; the overall mood.\n"
    "Output ONLY the prompt itself — one paragraph, no preamble, no quotes, no "
    "markdown, no explanation, no negative prompt, no camera-brand trivia, no "
    "trailing period. Maximum 120 words."
)

# Catalogue des légendeurs. `size_gb` = téléchargement total (modèle + mmproj).
# Bonsai-2 : seul le packing Q2_0 fonctionne en llama.cpp officiel (≥ b11556) ;
# les packings PTQ1_0/PQ2_0 exigeraient le fork PrismML — volontairement exclus.
# LFM3-VL-2B : licence custom LiquidAI « lfm1.0 » (pas Apache-2.0) — affichée telle quelle.
CAPTIONER_MODELS = {
    "bonsai2_4b": {
        "name": "Bonsai-2 4B (ternaire 2 bits)",
        "desc": "Légendeur 2026 dérivé de Qwen3.5-4B, ultra-compact (2-bit ternary). "
                "Le meilleur compromis poids/qualité de la famille. Licence Apache-2.0.",
        "license": "Apache-2.0", "hf_url": "https://huggingface.co/prism-ml/Ternary-Bonsai-2-4B-gguf",
        "deps": ["bonsai2_4b_model", "bonsai2_4b_mmproj"],
        "size_gb": 1.6, "vram_gb": 3, "recommended": True,
    },
    "bonsai2_2b": {
        "name": "Bonsai-2 2B (ternaire 2 bits)",
        "desc": "La version la plus légère (~0,9 Go) — pour petits GPU ou légendes rapides. Qualité moindre. Licence Apache-2.0.",
        "license": "Apache-2.0", "hf_url": "https://huggingface.co/prism-ml/Ternary-Bonsai-2-2B-gguf",
        "deps": ["bonsai2_2b_model", "bonsai2_2b_mmproj"],
        "size_gb": 0.9, "vram_gb": 2, "recommended": False,
    },
    "bonsai2_9b": {
        "name": "Bonsai-2 9B (ternaire 2 bits)",
        "desc": "La version 9B — plus capable pour les descriptions denses, toujours en 2-bit (~3,2 Go). Licence Apache-2.0.",
        "license": "Apache-2.0", "hf_url": "https://huggingface.co/prism-ml/Ternary-Bonsai-2-9B-gguf",
        "deps": ["bonsai2_9b_model", "bonsai2_9b_mmproj"],
        "size_gb": 3.2, "vram_gb": 4, "recommended": False,
    },
    "qwen35_4b": {
        "name": "Qwen3.5 4B (natif multimodal)",
        "desc": "VLM 2026 officiel Qwen, 262 k contexte, excellentes légendes structurées (Q4_K_M). Licence Apache-2.0.",
        "license": "Apache-2.0", "hf_url": "https://huggingface.co/Qwen/Qwen3.5-4B",
        "deps": ["qwen35_4b_model", "qwen35_4b_mmproj"],
        "size_gb": 3.4, "vram_gb": 5, "recommended": True,
    },
    "qwen3vl_4b": {
        "name": "Qwen3-VL 4B (déjà installé pour l'édition)",
        "desc": "Réutilise les poids Qwen3-VL-4B-Instruct + mmproj déjà téléchargés avec Fibo 2 / FLUX.3 / Iris / MOSS — 0 Go de plus. Licence Apache-2.0.",
        "license": "Apache-2.0", "hf_url": "https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct",
        "deps": ["qwen3vl_4b", "mmproj_qwen3vl_4b"],
        "size_gb": 0.0, "vram_gb": 5, "recommended": False, "reuses_installed": True,
    },
    "qwen3vl_8b": {
        "name": "Qwen3-VL 8B (déjà installé pour l'édition)",
        "desc": "Réutilise Qwen3-VL-8B-Instruct + mmproj déjà téléchargés avec Qwen-Image 2.1 / FLUX.3 — 0 Go de plus. Licence Apache-2.0.",
        "license": "Apache-2.0", "hf_url": "https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct",
        "deps": ["qwen3vl_8b", "mmproj_qwen3vl_8b"],
        "size_gb": 0.0, "vram_gb": 8, "recommended": False, "reuses_installed": True,
    },
    "qwen35_9b": {
        "name": "Qwen3.5 9B (encodeur de MOSS-Image)",
        "desc": "Réutilise Qwen3.5-9B (5,7 Go, déjà installé avec MOSS-Image) — seul mmproj F16 (~0,9 Go) est ajouté. Licence Apache-2.0.",
        "license": "Apache-2.0", "hf_url": "https://huggingface.co/Qwen/Qwen3.5-9B",
        "deps": ["qwen35_9b", "qwen35_9b_mmproj"],
        "size_gb": 0.9, "vram_gb": 8, "recommended": False,
    },
    "gemma4_e2b": {
        "name": "Gemma-4 E2B (Google)",
        "desc": "Gemma 4 edge, natif multimodal, supporté par llama.cpp au lancement (avr. 2026). Un poil plus lourd (~4,1 Go). Licence Apache-2.0.",
        "license": "Apache-2.0", "hf_url": "https://huggingface.co/google/gemma-4-E2B-it",
        "deps": ["gemma4_e2b_model", "gemma4_e2b_mmproj"],
        "size_gb": 4.1, "vram_gb": 6, "recommended": False,
    },
    "gemma4_e4b": {
        "name": "Gemma-4 E4B (Google)",
        "desc": "Gemma 4 edge grande taille (~6 Go) — légendes plus riches. Licence Apache-2.0.",
        "license": "Apache-2.0", "hf_url": "https://huggingface.co/google/gemma-4-E4B-it",
        "deps": ["gemma4_e4b_model", "gemma4_e4b_mmproj"],
        "size_gb": 6.0, "vram_gb": 8, "recommended": False,
    },
    "lfm3vl_2b": {
        "name": "LFM3-VL 2B (LiquidAI)",
        "desc": "Très compact (~1,3 Go). ⚠️ Licence custom « lfm1.0 » (LiquidAI) — usage personnel/évaluation ; ce n'est PAS une licence Apache/OSI. À lire avant installation.",
        "license": "lfm1.0 (custom LiquidAI)", "license_warn": True,
        "hf_url": "https://huggingface.co/LiquidAI/LFM3-VL-2B-GGUF",
        "deps": ["lfm3vl_2b_model", "lfm3vl_2b_mmproj"],
        "size_gb": 1.3, "vram_gb": 3, "recommended": False,
    },
}

CAPTIONER_ORDER = ["bonsai2_4b", "qwen35_4b", "bonsai2_9b", "qwen35_9b",
                   "qwen3vl_8b", "qwen3vl_4b", "gemma4_e2b", "bonsai2_2b",
                   "lfm3vl_2b", "gemma4_e4b"]

def _captioner_dep_present(dep_id):
    """Une dépendance de légendeur est présente si le manifeste/disque la connaît (sans passer par engine)."""
    mf = load_manifest()
    p = _dep_path(mf, dep_id)
    return bool(p and Path(p).exists())


def captioner_status(cid):
    """État d'un légendeur : {"ready": bool, "deps": {dep_id: bool}, "missing": [dep_id]}."""
    deps = (CAPTIONER_MODELS.get(cid) or {}).get("deps") or []
    deps_ready = {d: _captioner_dep_present(d) for d in deps}
    missing = [d for d, ok in deps_ready.items() if not ok]
    return {"ready": bool(deps) and not missing, "deps": deps_ready, "missing": missing}


def captioner_cards():
    """Cartes pour la page Modèles (ordre CAPTIONER_ORDER)."""
    return [{**CAPTIONER_MODELS[cid], "id": cid, "status": captioner_status(cid)}
            for cid in CAPTIONER_ORDER if cid in CAPTIONER_MODELS]


def captioners_ready():
    """Liste des ids de légendeurs prêts (ordre CAPTIONER_ORDER)."""
    return [cid for cid in CAPTIONER_ORDER if captioner_status(cid)["ready"]]


def resolve_captioner_id(preferred):
    """Choisit le légendeur effectif : celui demandé si prêt, sinon le premier prêt."""
    preferred = (preferred or "").strip()
    if preferred in CAPTIONER_MODELS and captioner_status(preferred)["ready"]:
        return preferred
    ready = captioners_ready()
    return ready[0] if ready else None


def captioner_files(cid):
    """(model_path, mmproj_path) depuis le manifeste — suppose le légendeur prêt."""
    m = load_manifest()
    paths = {d: _dep_path(m, d) for d in CAPTIONER_MODELS[cid]["deps"]}
    model = mmproj = None
    for d, p in paths.items():
        if "mmproj" in d:
            mmproj = p
        else:
            model = p
    if not model or not mmproj:
        raise RuntimeError(f"Fichiers du légendeur « {CAPTIONER_MODELS[cid]['name']} » introuvables — "
                           "téléchargez-le depuis la page Modèles.")
    return model, mmproj



# --------------------------------------------------------------------------- #
#  Mini-VAE TAE (decodage ultra-rapide + apercu en direct)
#  taew2_1  : Qwen-Image / Qwen-Image 2512 / Wan 2.1 (decode rapide en fin
#             de generation ; baisse tres legerement la finesse)
#  taeqi2_1 : Qwen-Image 2.1 (VAE 64 canaux) — decode rapide + apercu.
#  Repo HF : madebyollin/taehv (taew2_1) et madebyollin/taeqi2_1 (taeqi2_1).
# --------------------------------------------------------------------------- #
TAESD = {
    "taew2_1": {
        "id": "taew2_1",
        "name": "TAE Wan 2.1 (mini-VAE rapide pour Qwen-Image 2512)",
        "short_label": "⚡ Qwen-Image 2512 (TAE Wan)",
        "filename": "taew2_1.safetensors",
        "repo": "madebyollin/taehv",
        "repo_filename": "safetensors/taew2_1.safetensors",
        "size_mb": 2,
        "vae_dep": "vae_qwen",
        "desc": (
            "Mini-VAE (~2 Mo) qui remplace le décodage complet du VAE : la génération "
            "se termine presque instantanément au prix d'un très léger adoucissement. "
            "Compatible Qwen-Image 2512 (VAE Wan 2.1)."
        ),
    },
    "taeqi2_1": {
        "id": "taeqi2_1",
        "name": "TAE Qwen-Image 2.1 (mini-VAE rapide)",
        "short_label": "⚡ Qwen-Image 2.1 (TAE QI2.1)",
        "filename": "taeqi2_1.safetensors",
        "repo": "madebyollin/taeqi2_1",
        "repo_filename": "taeqi2_1.safetensors",
        "size_mb": 2,
        "vae_dep": "vae_qwen_21",
        "desc": (
            "Mini-VAE pour les modèles Qwen-Image 2.1 (VAE 64 canaux) : décodage final "
            "quasi instantané et aperçu en direct plus fluide. Léger adoucissement possible."
        ),
    },
}


def taesd_path(ta_id: str) -> Path | None:
    t = TAESD.get(ta_id)
    if not t:
        return None
    return TAESD_DIR / t["filename"]


def taesd_status(ta_id: str) -> dict:
    t = TAESD.get(ta_id)
    if not t:
        return {"downloaded": False, "path": None}
    p = TAESD_DIR / t["filename"]
    ok = p.exists() and p.is_file() and p.stat().st_size > 50 * 1024
    return {"downloaded": ok, "path": str(p) if ok else None}


def taesd_for_model(model_id: str) -> str | None:
    """Retourne l'id TAE compatible avec un modele, ou None."""
    m = MODELS.get(model_id)
    if not m:
        return None
    vae_dep = m.get("vae_dep")
    if m.get("arch") == "qwen_image":
        vae_dep = vae_dep or "vae_qwen"
    for ta_id, t in TAESD.items():
        if t["vae_dep"] == vae_dep:
            return ta_id
    return None


# --------------------------------------------------------------------------- #
#  PuLID-FLUX (conservation du visage a partir d'une photo de reference)
#  Poids : guozinan/PuLID/pulid_flux_v0.9.1.safetensors (~1.14 Go), usage avec
#  les modeles arch « flux ». L'empreinte d'identite (.pulidembd) est extraite
#  une fois par portrait avec le script outils/pulid_extract_id.py (stack
#  PyTorch externe, voir docs/pulid.md de stable-diffusion.cpp).
# --------------------------------------------------------------------------- #
PULID = {
    "weights_filename": "pulid_flux_v0.9.1.safetensors",
    "weights_repo": "guozinan/PuLID",
    "weights_url": "https://huggingface.co/guozinan/PuLID",
    "weights_size_mb": 1140,
    "compatible_arches": ("flux", "flux_kontext"),
    "compatible_models": ("flux-schnell", "flux-dev", "fhdr"),
    "default_weight": 1.0,
    "min_weight": 0.0,
    "max_weight": 2.0,
}


def pulid_weights_path() -> Path:
    return PULID_DIR / PULID["weights_filename"]


def pulid_status() -> dict:
    p = pulid_weights_path()
    ok = p.exists() and p.is_file() and p.stat().st_size > 100 * 1024 * 1024
    return {"downloaded": ok, "path": str(p) if ok else None,
            "size_gb": round(PULID["weights_size_mb"] / 1024, 2),
            "url": PULID["weights_url"]}


def list_portraits() -> list[dict]:
    """Portraits disponibles (empreinte extraite) dans portraits/."""
    out = []
    if PORTRAITS_DIR.exists():
        for emb in sorted(PORTRAITS_DIR.glob("*.pulidembd")):
            img = None
            for ext in (".png", ".jpg", ".jpeg", ".webp"):
                cand = emb.with_suffix(ext)
                if cand.exists():
                    img = cand.name
                    break
            ok = emb.stat().st_size > 50 * 1024
            out.append({
                "id": emb.stem,
                "name": emb.stem,
                "embedding": emb.name,
                "size_kb": max(1, round(emb.stat().st_size / 1024)),
                "size_mb": round(emb.stat().st_size / (1024 * 1024), 2),
                "url": f"/portraits/{img}" if img else None,
                "has_image": bool(img),
                "valid": ok,
            })
    return out


def portrait_embedding(portrait_id: str) -> Path | None:
    """Chemin d'une empreinte .pulidembd (nom nettoye, jamais hors portraits/)."""
    safe = re.sub(r"[^a-zA-Z0-9_\-]", "_", str(portrait_id or "").strip())
    if not safe:
        return None
    p = PORTRAITS_DIR / f"{safe}.pulidembd"
    return p if p.exists() and p.stat().st_size > 50 * 1024 else None


def supports_pulid(model_id: str) -> bool:
    """Indique si le modele peut recevoir une empreinte PuLID (arch FLUX)."""
    m = MODELS.get(model_id, {})
    return m.get("arch") in PULID["compatible_arches"]


# --------------------------------------------------------------------------- #
#  Detection VRAM : recommandation de quant par modele
# --------------------------------------------------------------------------- #
def recommended_quant(model_id: str, vram_gb: float) -> str | None:
    """
    Choisit le meilleur quant qui « tient » dans la VRAM detectee.
    Heuristique simple : poids du modele x1.2 (marge d'execution) +
    1.5 Go de contexte (VAE, encodeurs, activation) <= VRAM disponible.
    Si rien ne rentre, le plus leger est propose (l'offload CPU finira le travail).
    """
    m = MODELS.get(model_id)
    if not m:
        return None
    sizes = [(q, s) for q, s in ((q, m.get("size_gb", {}).get(q)) for q in m.get("quants", []))
             if isinstance(s, (int, float))]
    if not sizes:
        return m.get("default_quant")
    if not vram_gb:
        return m.get("default_quant")
    budget = float(vram_gb) - 1.5  # marge VAE + encodeurs
    best_light = None
    chosen = None
    for q, s in sorted(sizes, key=lambda x: -x[1]):
        if best_light is None:
            best_light = q
        if s * 1.2 <= budget:
            chosen = q
            break
        best_light = q
    return chosen or best_light


def quant_recommendations(vram_gb: float) -> dict:
    """Recommandation par modele installe (None si VRAM inconnue)."""
    if not vram_gb:
        return {}
    return {mid: recommended_quant(mid, vram_gb) for mid in MODELS}


SAMPLERS_INFO = [
    {
        "id": "default",
        "label": "Auto (recommandé par le modèle)",
        "desc": "Utilise l'échantillonneur optimal prévu pour ce modèle (généralement Euler).",
    },
    {
        "id": "euler",
        "label": "Euler — Rapide & fidèle (standard DiT / FLUX)",
        "desc": "Le meilleur compromis vitesse/qualité pour FLUX, Qwen-Image, Fibo et Z-Image.",
    },
    {
        "id": "heun",
        "label": "Heun — Finesse des dégradés & textures (2× plus précis)",
        "desc": "Méthode du 2e ordre : affine les textures et les transitions de lumière (plus lent par étape).",
    },
    {
        "id": "dpm++2m",
        "label": "DPM++ 2M — Piqué élevé (excellent sur SD 3.5 & portraits)",
        "desc": "Renforce le micro-contraste et la netteté dès 20-28 étapes.",
    },
    {
        "id": "euler_a",
        "label": "Euler Ancestral — Créatif & grain organique",
        "desc": "Ajoute une légère variation stochastique à chaque étape, utile pour casser un aspect trop lisse.",
    },
    {
        "id": "lcm",
        "label": "LCM — Spécial modèles distillés ultra-courts",
        "desc": "Conçu pour les checkpoints distillés en très peu d'étapes (4 à 8 étapes).",
    },
]

SCHEDULERS_INFO = [
    {
        "id": "default",
        "label": "Auto (défaut du moteur)",
        "desc": "Laisse sd-cli choisir la courbe de bruit adaptée à l'architecture du modèle.",
    },
    {
        "id": "discrete",
        "label": "Discrete — Progression linéaire standard",
        "desc": "Répartition classique des étapes de débruitage.",
    },
    {
        "id": "karras",
        "label": "Karras — Micro-détails & finitions soignées",
        "desc": "Concentre davantage d'étapes sur la fin du débruitage pour soigner le grain et les petits détails.",
    },
    {
        "id": "beta",
        "label": "Beta — Contraste & richesse des matières",
        "desc": "Courbe récente très appréciée sur les modèles DiT/Flow pour améliorer la densité des textures.",
    },
    {
        "id": "sgm_uniform",
        "label": "SGM Uniform — Stable sur les modèles Turbo / SD3",
        "desc": "Répartition uniforme recommandée pour plusieurs checkpoints basés sur le Flow Matching.",
    },
    {
        "id": "exponential",
        "label": "Exponential — Transitions douces",
        "desc": "Décroissance exponentielle du bruit, utile pour des éclairages très progressifs.",
    },
]


# --------------------------------------------------------------------------- #
#  Dependances partagees (telechargees une fois, reutilisees par les modeles)
# --------------------------------------------------------------------------- #
DEPS = {
    "vae_flux": {
        "type": "exact",
        "repo": "black-forest-labs/FLUX.1-schnell",
        "filename": "ae.safetensors",
        "dest": VAE_DIR / "ae.safetensors",
        "size_gb": 0.32,
        # Dépôt BFL gated (licence FLUX requise). Si le téléchargement échoue
        # (ex. 401 sans token), le moteur retente automatiquement sur ce miroir
        # public officiel Comfy-Org (même fichier, 335 Mo).
        "fallback": {"repo": "Comfy-Org/Z-Image-Turbo",
                     "filename": "split_files/vae/ae.safetensors"},
    },
    "vae_flux2": {
        "type": "exact",
        "repo": "Comfy-Org/ERNIE-Image",
        "filename": "vae/flux2-vae.safetensors",
        "dest": VAE_DIR / "flux2-vae.safetensors",
        "size_gb": 0.25,
    },
    "vae_qwen": {
        "type": "exact",
        "repo": "Comfy-Org/Qwen-Image_ComfyUI",
        "filename": "split_files/vae/qwen_image_vae.safetensors",
        "dest": VAE_DIR / "qwen_image_vae.safetensors",
        "size_gb": 0.27,
    },
    "clip_l": {
        "type": "exact",
        "repo": "comfyanonymous/flux_text_encoders",
        "filename": "clip_l.safetensors",
        "dest": TEXTENC_DIR / "clip_l.safetensors",
        "size_gb": 0.25,
    },
    "clip_g": {
        "type": "exact",
        "repo": "Comfy-Org/stable-diffusion-3.5-fp8",
        "filename": "text_encoders/clip_g.safetensors",
        "dest": TEXTENC_DIR / "clip_g.safetensors",
        "size_gb": 1.4,
    },
    "t5xxl": {
        "type": "exact",
        "repo": "comfyanonymous/flux_text_encoders",
        "filename": "t5xxl_fp8_e4m3fn.safetensors",
        "dest": TEXTENC_DIR / "t5xxl_fp8_e4m3fn.safetensors",
        "size_gb": 4.9,
    },
    "qwen3_4b": {
        "type": "gguf",
        "repo": "unsloth/Qwen3-4B-GGUF",
        "dest_dir": LLM_DIR,
        "size_gb": 2.5,
    },
    "qwen3vl_4b": {
        "type": "gguf",
        "repo": "Qwen/Qwen3-VL-4B-Instruct-GGUF",
        "dest_dir": LLM_DIR,
        "size_gb": 2.5,
    },
    "qwen3_8b": {
        "type": "gguf",
        "repo": "unsloth/Qwen3-8B-GGUF",
        "dest_dir": LLM_DIR,
        "size_gb": 5.0,
    },
    "ministral_3b": {
        "type": "gguf",
        "repo": "unsloth/Ministral-3-3B-Instruct-2512-GGUF",
        "dest_dir": LLM_DIR,
        "size_gb": 2.2,
    },
    "qwen3vl_8b": {
        "type": "gguf",
        "repo": "unsloth/Qwen3-VL-8B-Instruct-GGUF",
        "dest_dir": LLM_DIR,
        "size_gb": 5.1,
    },
    "qwen25vl_7b": {
        "type": "exact",
        "repo": "mradermacher/Qwen2.5-VL-7B-Instruct-GGUF",
        "filename": "Qwen2.5-VL-7B-Instruct.Q4_K_M.gguf",
        "dest": LLM_DIR / "Qwen2.5-VL-7B-Instruct.Q4_K_M.gguf",
        "size_gb": 4.7,
    },

    "mmproj_qwen3vl_8b": {
        "type": "exact",
        "repo": "Qwen/Qwen3-VL-8B-Instruct-GGUF",
        "filename": "mmproj-Qwen3VL-8B-Instruct-F16.gguf",
        "dest": LLM_DIR / "mmproj-Qwen3VL-8B-Instruct-F16.gguf",
        "size_gb": 1.2,
    },
    "vae_qwen_21": {
        "type": "exact",
        "repo": "unsloth/Qwen-Image-2.1-FP8",
        "filename": "vae/qwen_image_2.1_vae_bf16.safetensors",
        "dest": VAE_DIR / "qwen_image_2.1_vae_bf16.safetensors",
        "size_gb": 0.68,
    },
    "vae_sd3": {
        "type": "exact",
        "repo": "stabilityai/stable-diffusion-3.5-large",
        "filename": "vae/diffusion_pytorch_model.safetensors",
        "dest": VAE_DIR / "sd3_vae.safetensors",
        "size_gb": 0.17,
    },
    # --- Dependances ajoutees avec Fibo 2.0, MOSS-Image et Krea 2 ---
    "vae_wan21": {
        "type": "exact",
        "repo": "Comfy-Org/Wan_2.1_ComfyUI_repackaged",
        "filename": "split_files/vae/wan_2.1_vae.safetensors",
        "dest": VAE_DIR / "wan_2.1_vae.safetensors",
        "size_gb": 0.25,
    },
    "qwen35_9b": {
        "type": "gguf",
        "repo": "unsloth/Qwen3.5-9B-GGUF",
        "dest_dir": LLM_DIR,
        "size_gb": 5.7,
    },
    "moss_tokenizer": {
        "type": "exact",
        "repo": "OpenMOSS-Team/MOSS-Image-Base",
        "filename": "tokenizer/tokenizer.json",
        "dest": LLM_DIR / "moss_image_tokenizer.json",
        "size_gb": 0.02,
    },
    "mmproj_qwen3vl_4b": {
        "type": "exact",
        "repo": "Qwen/Qwen3-VL-4B-Instruct-GGUF",
        "filename": "mmproj-Qwen3VL-4B-Instruct-F16.gguf",
        "dest": LLM_DIR / "mmproj-Qwen3VL-4B-Instruct-F16.gguf",
        "size_gb": 0.84,
    },
    # --- Dépendances des légendeurs d'image (GGUF llama.cpp + encodeur visuel) ---
    "bonsai2_2b_model": {
        "type": "exact",
        "repo": "prism-ml/Ternary-Bonsai-2-2B-gguf",
        "filename": "Ternary-Bonsai-2-2B-Q2_0.gguf",
        "dest": LLM_DIR / "Ternary-Bonsai-2-2B-Q2_0.gguf",
        "size_gb": 0.55,
    },
    "bonsai2_2b_mmproj": {
        "type": "exact",
        "repo": "prism-ml/Ternary-Bonsai-2-2B-gguf",
        "filename": "Ternary-Bonsai-2-2B-mmproj-Q8_0.gguf",
        "dest": LLM_DIR / "Ternary-Bonsai-2-2B-mmproj-Q8_0.gguf",
        "size_gb": 0.36,
    },
    "bonsai2_4b_model": {
        "type": "exact",
        "repo": "prism-ml/Ternary-Bonsai-2-4B-gguf",
        "filename": "Ternary-Bonsai-2-4B-Q2_0.gguf",
        "dest": LLM_DIR / "Ternary-Bonsai-2-4B-Q2_0.gguf",
        "size_gb": 1.21,
    },
    "bonsai2_4b_mmproj": {
        "type": "exact",
        "repo": "prism-ml/Ternary-Bonsai-2-4B-gguf",
        "filename": "Ternary-Bonsai-2-4B-mmproj-Q8_0.gguf",
        "dest": LLM_DIR / "Ternary-Bonsai-2-4B-mmproj-Q8_0.gguf",
        "size_gb": 0.37,
    },
    "bonsai2_9b_model": {
        "type": "exact",
        "repo": "prism-ml/Ternary-Bonsai-2-9B-gguf",
        "filename": "Ternary-Bonsai-2-9B-Q2_0.gguf",
        "dest": LLM_DIR / "Ternary-Bonsai-2-9B-Q2_0.gguf",
        "size_gb": 2.56,
    },
    "bonsai2_9b_mmproj": {
        "type": "exact",
        "repo": "prism-ml/Ternary-Bonsai-2-9B-gguf",
        "filename": "Ternary-Bonsai-2-9B-mmproj-Q8_0.gguf",
        "dest": LLM_DIR / "Ternary-Bonsai-2-9B-mmproj-Q8_0.gguf",
        "size_gb": 0.62,
    },
    "qwen35_4b_model": {
        "type": "exact",
        "repo": "unsloth/Qwen3.5-4B-GGUF",
        "filename": "Qwen3.5-4B-Q4_K_M.gguf",
        "dest": LLM_DIR / "Qwen3.5-4B-Q4_K_M.gguf",
        "size_gb": 2.74,
    },
    "qwen35_4b_mmproj": {
        "type": "exact",
        "repo": "unsloth/Qwen3.5-4B-GGUF",
        "filename": "mmproj-F16.gguf",
        "dest": LLM_DIR / "qwen3.5-4b-mmproj-F16.gguf",
        "size_gb": 0.67,
    },
    "qwen35_9b_mmproj": {
        "type": "exact",
        "repo": "unsloth/Qwen3.5-9B-GGUF",
        "filename": "mmproj-F16.gguf",
        "dest": LLM_DIR / "qwen3.5-9b-mmproj-F16.gguf",
        "size_gb": 0.92,
    },
    "gemma4_e2b_model": {
        "type": "exact",
        "repo": "unsloth/gemma-4-E2B-it-GGUF",
        "filename": "gemma-4-E2B-it-Q4_K_M.gguf",
        "dest": LLM_DIR / "gemma-4-E2B-it-Q4_K_M.gguf",
        "size_gb": 3.11,
    },
    "gemma4_e2b_mmproj": {
        "type": "exact",
        "repo": "unsloth/gemma-4-E2B-it-GGUF",
        "filename": "mmproj-F16.gguf",
        "dest": LLM_DIR / "gemma-4-e2b-mmproj-F16.gguf",
        "size_gb": 0.99,
    },
    "gemma4_e4b_model": {
        "type": "exact",
        "repo": "unsloth/gemma-4-E4B-it-GGUF",
        "filename": "gemma-4-E4B-it-Q4_K_M.gguf",
        "dest": LLM_DIR / "gemma-4-E4B-it-Q4_K_M.gguf",
        "size_gb": 4.98,
    },
    "gemma4_e4b_mmproj": {
        "type": "exact",
        "repo": "unsloth/gemma-4-E4B-it-GGUF",
        "filename": "mmproj-F16.gguf",
        "dest": LLM_DIR / "gemma-4-e4b-mmproj-F16.gguf",
        "size_gb": 0.99,
    },
    "lfm3vl_2b_model": {
        "type": "exact",
        "repo": "LiquidAI/LFM3-VL-2B-GGUF",
        "filename": "LFM3-VL-2B-Q4_K_M.gguf",
        "dest": LLM_DIR / "LFM3-VL-2B-Q4_K_M.gguf",
        "size_gb": 1.10,
    },
    "lfm3vl_2b_mmproj": {
        "type": "exact",
        "repo": "LiquidAI/LFM3-VL-2B-GGUF",
        "filename": "mmproj-LFM3-VL-2B-Q8_0.gguf",
        "dest": LLM_DIR / "mmproj-LFM3-VL-2B-Q8_0.gguf",
        "size_gb": 0.20,
    },
}

DEFAULT_NEGATIVE = "blurry, low quality, lowres, distorted, deformed, ugly, bad anatomy, extra limbs, missing fingers, watermark, text, signature, jpeg artifacts, cropped, out of frame, duplicate, mutation"

DEP_QUANT_PRIORITY = ["Q4_K_M", "Q5_K_M", "Q6_K"]


# --------------------------------------------------------------------------- #
#  Modeles de generation d'images
# --------------------------------------------------------------------------- #
# diffusion_fa : False pour ERNIE (bug officiel #1447 -> image blanche)
# needs_vae    : False pour SD3 (VAE integre dans le modele)
MODELS = {
    "flux-schnell": {

        "presets": {
            "rapide":    {"steps": 4,  "cfg": 1.0, "quant": "Q4_K_M", "label": "⚡ Rapide (4 etapes, Q4)"},
            "equilibre": {"steps": 4,  "cfg": 1.0, "quant": "Q5_K_M", "label": "⚡ Rapide+ (4 etapes, Q5)"},
            "qualite":   {"steps": 8,  "cfg": 2.0, "quant": "Q6_K",   "label": "✨ Qualite (8 etapes, Q6)"},
        },
        "name": "FLUX.1 schnell",
        "arch": "flux",
        "repo": "unsloth/FLUX.1-schnell-GGUF",
        "quants": ["Q4_K_M", "Q5_K_M", "Q6_K"],
        "default_quant": "Q5_K_M",
        "file_for_quant": {
            "Q4_K_M": "flux1-schnell-Q4_K_M.gguf",
            "Q5_K_M": "flux1-schnell-Q5_K_M.gguf",
            "Q6_K":   "flux1-schnell-Q6_K.gguf",
        },
        "size_gb": {"Q4_K_M": 6.9, "Q5_K_M": 8.4, "Q6_K": 9.8},
        "deps": ["vae_flux", "clip_l", "t5xxl"],
        "supports_neg": False,
        "needs_token": False,
        "license": "Apache 2.0 (libre, commercial OK)",
        "hf_url": "https://huggingface.co/unsloth/FLUX.1-schnell-GGUF",
        "vram_min_gb": 6,
        "desc": "Tres rapide (4 etapes), excellent pour des tests expressifs.",
        "defaults": {"steps": 4,  "cfg": 1.0, "sampler": "euler"},
        "min_steps": 1, "max_steps": 8,
    },
    "z-image": {

        "presets": {
            "rapide":    {"steps": 14, "cfg": 3.0, "quant": "Q4_K_M", "label": "⚡ Rapide (14 etapes, Q4)"},
            "equilibre": {"steps": 28, "cfg": 4.0, "quant": "Q5_K_M", "label": "⚖️ Equilibre (28 etapes, Q5)"},
            "qualite":   {"steps": 40, "cfg": 5.0, "quant": "Q6_K",   "label": "✨ Qualite (40 etapes, Q6)"},
        },
        "name": "Z-Image",
        "arch": "zimage",
        "repo": "unsloth/Z-Image-GGUF",
        "quants": ["Q4_K_M", "Q5_K_M", "Q6_K"],
        "default_quant": "Q5_K_M",
        "file_for_quant": {
            "Q4_K_M": "z-image-Q4_K_M.gguf",
            "Q5_K_M": "z-image-Q5_K_M.gguf",
            "Q6_K":   "z-image-Q6_K.gguf",
        },
        "size_gb": {"Q4_K_M": 5.1, "Q5_K_M": 5.6, "Q6_K": 6.1},
        "deps": ["vae_flux", "qwen3_4b"],
        "supports_neg": True,
        "needs_token": False,
        "license": "Apache 2.0 (libre, commercial OK)",
        "hf_url": "https://huggingface.co/unsloth/Z-Image-GGUF",
        "vram_min_gb": 4,
        "desc": "Modele fondamental polyvalent, excellent respect du prompt.",
        "defaults": {"steps": 28, "cfg": 4.0, "sampler": "euler"},
        "min_steps": 10, "max_steps": 50,
    },
    "ernie-turbo": {

        "presets": {
            "rapide":    {"steps": 8,  "cfg": 1.0, "quant": "Q4_K_M", "label": "⚡ Rapide (8 etapes, Q4)"},
            "equilibre": {"steps": 12, "cfg": 2.0, "quant": "Q5_K_M", "label": "⚖️ Equilibre (12 etapes, Q5)"},
            "qualite":   {"steps": 20, "cfg": 3.5, "quant": "Q6_K",   "label": "✨ Qualite (20 etapes, Q6)"},
        },
        "name": "ERNIE-Image Turbo",
        "arch": "ernie",
        "repo": "unsloth/ERNIE-Image-Turbo-GGUF",
        "quants": ["Q4_K_M", "Q5_K_M", "Q6_K"],
        "default_quant": "Q5_K_M",
        "file_for_quant": {
            "Q4_K_M": "ernie-image-turbo-Q4_K_M.gguf",
            "Q5_K_M": "ernie-image-turbo-Q5_K_M.gguf",
            "Q6_K":   "ernie-image-turbo-Q6_K.gguf",
        },
        "size_gb": {"Q4_K_M": 5.0, "Q5_K_M": 5.6, "Q6_K": 6.1},
        "deps": ["vae_flux2", "ministral_3b"],
        "supports_neg": False,
        "needs_token": False,
        "license": "Apache 2.0 (libre, commercial OK)",
        "hf_url": "https://huggingface.co/unsloth/ERNIE-Image-Turbo-GGUF",
        "vram_min_gb": 4,
        "diffusion_fa": False,
        "desc": "Rapide (8 etapes), tres bon pour le texte dans l'image.",
        "defaults": {"steps": 8, "cfg": 1.0, "sampler": "euler"},
        "min_steps": 4, "max_steps": 20,
    },
    "ideogram4": {

        "presets": {
            "rapide":    {"steps": 8,  "cfg": 3.0, "quant": "Q4_0", "label": "⚡ Rapide (8 etapes)"},
            "equilibre": {"steps": 12, "cfg": 4.0, "quant": "Q4_0", "label": "⚖️ Equilibre (12 etapes)"},
            "qualite":   {"steps": 20, "cfg": 5.0, "quant": "Q4_0", "label": "✨ Qualite (20 etapes)"},
        },
        "name": "Ideogram 4",
        "arch": "ideogram",
        "repo": "leejet/ideogram-4-GGUF",
        "quants": ["Q4_0"],
        "default_quant": "Q4_0",
        "file_for_quant": {"Q4_0": "ideogram4-Q4_0.gguf"},
        "uncond_file_for_quant": {"Q4_0": "ideogram4_uncond-Q4_0.gguf"},
        "size_gb": {"Q4_0": 11.3},
        "deps": ["vae_flux2", "qwen3vl_8b"],
        "supports_neg": False,
        "needs_token": False,
        "license": "Ideogram (lire les conditions)",
        "hf_url": "https://huggingface.co/leejet/ideogram-4-GGUF",
        "vram_min_gb": 10,
        "desc": "Rendu de texte top mais Q4_0 limite la qualite. Prompt converti en JSON automatiquement.",
        "defaults": {"steps": 12, "cfg": 4.0, "sampler": "euler"},
        "min_steps": 4, "max_steps": 30,
    },
    "fhdr": {

        "presets": {
            "rapide":    {"steps": 12, "cfg": 2.5, "quant": "Q4_K_M", "label": "⚡ Rapide (12 etapes)"},
            "equilibre": {"steps": 20, "cfg": 3.5, "quant": "Q4_K_M", "label": "⚖️ Equilibre (20 etapes)"},
            "qualite":   {"steps": 35, "cfg": 4.5, "quant": "Q4_K_M", "label": "✨ Qualite (35 etapes)"},
        },
        "name": "FHDR Uncensored (FLUX-dev)",
        "arch": "flux",
        "repo": "kpsss34/FHDR_Uncensored",
        "quants": ["Q4_K_M"],
        "default_quant": "Q4_K_M",
        "file_for_quant": {"Q4_K_M": "FHDR_ComfyUI-Q4_K_M.gguf"},
        "size_gb": {"Q4_K_M": 6.9},
        "deps": ["vae_flux", "clip_l", "t5xxl"],
        "supports_neg": True,
        "needs_token": True,
        "license": "FLUX.1-dev Non-Commercial (usage perso uniquement)",
        "hf_url": "https://huggingface.co/kpsss34/FHDR_Uncensored",
        "vram_min_gb": 6,
        "desc": "FLUX.1-dev sans censure. Necessite un token Hugging Face.",
        "defaults": {"steps": 20, "cfg": 3.5, "sampler": "euler"},
        "min_steps": 8, "max_steps": 40,
    },
    "qwen-image-2512": {

        "presets": {
            "rapide":    {"steps": 15, "cfg": 2.0, "quant": "Q4_K_M", "label": "⚡ Rapide (15 etapes, Q4)"},
            "equilibre": {"steps": 30, "cfg": 4.0, "quant": "Q5_K_M", "label": "⚖️ Equilibre (30 etapes, Q5)"},
            "qualite":   {"steps": 50, "cfg": 5.0, "quant": "Q6_K",   "label": "✨ Qualite (50 etapes, Q6)"},
            "optimise":  {"steps": 25, "cfg": 3.5, "quant": "Q5_K_M", "label": "🎯 Optimise edition (25 etapes)"},
        },
        "name": "Qwen-Image 2512",
        "arch": "qwen_image",
        "repo": "unsloth/Qwen-Image-2512-GGUF",
        "quants": ["Q4_K_M", "Q5_K_M", "Q6_K"],
        "default_quant": "Q5_K_M",
        "file_for_quant": {
            "Q4_K_M": "qwen-image-2512-Q4_K_M.gguf",
            "Q5_K_M": "qwen-image-2512-Q5_K_M.gguf",
            "Q6_K":   "qwen-image-2512-Q6_K.gguf",
        },
        "size_gb": {"Q4_K_M": 13.2, "Q5_K_M": 15.0, "Q6_K": 16.8},
        "deps": ["vae_qwen", "qwen25vl_7b"],
        "supports_neg": True,
        "needs_token": False,
        "license": "Apache 2.0 (libre, commercial OK)",
        "hf_url": "https://huggingface.co/unsloth/Qwen-Image-2512-GGUF",
        "vram_min_gb": 8,
        "desc": "Realisme humain ameliore, details naturels et rendu de texte.",
        "defaults": {"steps": 30, "cfg": 4.0, "sampler": "euler"},
        "min_steps": 10, "max_steps": 60,
    },

    "qwen-image-2.1": {
        "name": "Qwen-Image-2.1",
        "arch": "qwen_image",
        "repo": "unsloth/Qwen-Image-2.1-GGUF",
        "quants": ["Q4_K_M", "Q5_K_M", "Q6_K"],
        "default_quant": "Q5_K_M",
        "file_for_quant": {
            "Q4_K_M": "qwen-image-2.1-Q4_K_M.gguf",
            "Q5_K_M": "qwen-image-2.1-Q5_K_M.gguf",
            "Q6_K":   "qwen-image-2.1-Q6_K.gguf",
        },
        "size_gb": {"Q4_K_M": 4.2, "Q5_K_M": 5.4, "Q6_K": 6.3},
        "deps": ["vae_qwen_21", "qwen3vl_8b", "mmproj_qwen3vl_8b"],
        "supports_neg": False,
        "needs_token": False,
        "supports_img2img": True,
        # --- Edition multi-images (cf. docs/ADD_MODEL_FR.md) ---
        "supports_ref_images": True,
        "supports_outpainting": True,
        "input_modes": ["ref"],
        "max_ref_images": 10,
        "ref_tag_syntax": "<image{n}>",
        "ref_needs_vlm": True,
        "ref_hint": ("Le moteur annote automatiquement chaque image pour le VLM : adresse-les "
                     "dans le prompt avec <image1>, <image2>… Image 1 = celle que l'on modifie, "
                     "les autres fournissent le contenu (vêtement, objet, style)."),
        "ref_examples": [
            "Keep the character and pose in <image1> unchanged, put the denim shirt from <image2> "
            "on the character, preserve the original face, hair and background",
            "Replace the text on the sign in <image1> with the exact text from <image2>, "
            "same font, same lighting",
        ],
        "vae_dep": "vae_qwen_21",
        "llm_dep": "qwen3vl_8b",
        "mmproj_dep": "mmproj_qwen3vl_8b",
        "zero_cond_t_on_edit": True,
        "license": "Qwen Research License (usage non-commercial)",
        "hf_url": "https://huggingface.co/unsloth/Qwen-Image-2.1-GGUF",
        "vram_min_gb": 8,
        "desc": "Édition sémantique multi-images (jusqu'à 10) + text2image. mmproj requis pour l'édition.",
        "defaults": {"steps": 25, "cfg": 3.5, "sampler": "euler"},
        "min_steps": 10, "max_steps": 50,
        "presets": {
            "rapide":    {"steps": 15, "cfg": 1.0, "quant": "Q4_K_M", "label": "⚡ Rapide (15 etapes, Q4)"},
            "equilibre": {"steps": 25, "cfg": 3.5, "quant": "Q5_K_M", "label": "⚖️ Equilibre (25 etapes, Q5)"},
            "qualite":   {"steps": 40, "cfg": 6.0, "quant": "Q6_K",   "label": "✨ Qualite (40 etapes, Q6)"},
            "optimise":  {"steps": 20, "cfg": 1.0, "quant": "Q4_K_M", "label": "🎯 Optimise edition (20 etapes, Q4)"},
        },
    },
    "qwen-image-2.1-turbo": {
        "name": "Qwen-Image-2.1 Turbo",
        "arch": "qwen_image",
        "repo": "AtomicChat/Qwen-Image-2.1-Turbo-GGUF",
        "quants": ["AD-Q2_K", "AD-Q3_K", "AD-Q4_K", "AD-Q5_K", "AD-Q6_K", "Q8_0", "BF16"],
        "default_quant": "AD-Q4_K",
        "file_for_quant": {
            "AD-Q2_K": "Qwen-Image-2.1-Turbo-AD-Q2_K.gguf",
            "AD-Q3_K": "Qwen-Image-2.1-Turbo-AD-Q3_K.gguf",
            "AD-Q4_K": "Qwen-Image-2.1-Turbo-AD-Q4_K.gguf",
            "AD-Q5_K": "Qwen-Image-2.1-Turbo-AD-Q5_K.gguf",
            "AD-Q6_K": "Qwen-Image-2.1-Turbo-AD-Q6_K.gguf",
            "Q8_0": "Qwen-Image-2.1-Turbo-Q8_0.gguf",
            "BF16": "Qwen-Image-2.1-Turbo-BF16.gguf",
        },
        "size_gb": {
            "AD-Q2_K": 2.55, "AD-Q3_K": 3.6, "AD-Q4_K": 4.2,
            "AD-Q5_K": 5.4, "AD-Q6_K": 6.71, "Q8_0": 7.59, "BF16": 14.2,
        },
        "deps": ["vae_qwen_21", "qwen3vl_8b"],
        "supports_neg": False,
        "needs_token": False,
        "supports_img2img": True,
        "vae_dep": "vae_qwen_21",
        "llm_dep": "qwen3vl_8b",
        "mmproj_dep": "mmproj_qwen3vl_8b",
        "mmproj_for_img2img_only": True,
        "zero_cond_t_on_edit": True,
        # --- Edition multi-images ---
        "supports_ref_images": True,
        "supports_outpainting": True,
        "input_modes": ["ref"],
        "max_ref_images": 10,
        "ref_tag_syntax": "<image{n}>",
        "ref_needs_vlm": True,
        "ref_hint": ("Même syntaxe que Qwen-Image 2.1 : <image1>, <image2>… (image 1 = le canvas). "
                     "Version distillée : restez à 2-3 images si la VRAM est serrée."),
        "ref_examples": [
            "Remove the background of <image1>, keep the logo from <image2> as RGBA",
            "Keep the person in <image1> unchanged, dress them with the coat from <image2>",
        ],
        "fixed_steps": 8,
        "fixed_cfg": 1.0,
        "sigmas": "1.0,0.978453,0.95418,0.926626,0.89508,0.845148,0.704534,0.414568,0.0",
        "license": "Qwen Research License (usage non-commercial)",
        "hf_url": "https://huggingface.co/AtomicChat/Qwen-Image-2.1-Turbo-GGUF",
        "vram_min_gb": 8,
        "desc": "Turbo distillé (8 étapes, CFG 1, sigmas dédiés), génération + édition. Requiert sd-cli c150a6b (6 oct. 2026) ou plus récent.",
        "defaults": {"steps": 8, "cfg": 1.0, "sampler": "euler"},
        "min_steps": 8, "max_steps": 8,
        "presets": {
            "compact":   {"steps": 8, "cfg": 1.0, "quant": "AD-Q3_K", "label": "💾 Léger (AD-Q3_K)"},
            "equilibre": {"steps": 8, "cfg": 1.0, "quant": "AD-Q4_K", "label": "⚖️ Équilibre (AD-Q4_K)"},
            "qualite":   {"steps": 8, "cfg": 1.0, "quant": "AD-Q6_K", "label": "✨ Qualité (AD-Q6_K)"},
        },
    },
    "iris-3b": {
        "name": "Iris-3B",
        "arch": "iris",
        "repo": "speridlabs/iris-3b",
        "quants": ["F32"],
        "default_quant": "F32",
        "file_for_quant": {"F32": "model.safetensors"},
        "size_gb": {"F32": 12.0},
        "deps": ["qwen3vl_4b"],
        "supports_neg": True,
        "needs_token": False,
        "needs_vae": False,
        "license": "Apache 2.0",
        "hf_url": "https://huggingface.co/speridlabs/iris-3b",
        "vram_min_gb": 12,
        "desc": "Iris-3B en espace pixel (~12 Go safetensors), sans VAE. Qwen3-VL-4B requis; CFG 3, 100 étapes, prompts ≤300 tokens. Requiert sd-cli f89d9b1+.",
        "defaults": {"steps": 100, "cfg": 3.0, "sampler": "euler"},
        "min_steps": 10, "max_steps": 200,
    },

    # ---- NOUVEAUX MODELES ----
    "sd3.5-medium": {


        "presets": {
            "rapide":    {"steps": 15, "cfg": 3.5, "quant": "Q4_K_M", "label": "⚡ Rapide (15 etapes, Q4)"},
            "equilibre": {"steps": 30, "cfg": 4.5, "quant": "Q5_K_M", "label": "⚖️ Equilibre (30 etapes, Q5)"},
            "qualite":   {"steps": 45, "cfg": 5.5, "quant": "Q6_K",   "label": "✨ Qualite (45 etapes, Q6)"},
        },
        "name": "Stable Diffusion 3.5 Medium",
        "arch": "sd3",
        "repo": "city96/stable-diffusion-3.5-medium-gguf",
        "quants": ["Q4_K_M", "Q5_K_M", "Q6_K"],
        "default_quant": "Q5_K_M",
        "file_for_quant": {
            "Q4_K_M": "sd3.5_medium-Q4_K_M.gguf",
            "Q5_K_M": "sd3.5_medium-Q5_K_M.gguf",
            "Q6_K":   "sd3.5_medium-Q6_K.gguf",
        },
        "size_gb": {"Q4_K_M": 1.8, "Q5_K_M": 2.1, "Q6_K": 2.3},
        "deps": ["vae_sd3", "clip_l", "clip_g", "t5xxl"],
        "supports_neg": True,
        "diffusion_fa": False,
        "license": "Stability AI Community (non-commercial <$1M)",
        "supports_img2img": True,
        # Img2img classique : une seule image de depart + force (pas de references multiples).
        "input_modes": ["init"],
        "max_ref_images": 1,
        "hf_url": "https://huggingface.co/city96/stable-diffusion-3.5-medium-gguf",
        "vram_min_gb": 4,
        "needs_token": True,
        "desc": "Modele compact 2.5B, VAE SD3 requis (gated). Bon equilibre qualite/vitesse.",
        "defaults": {"steps": 30, "cfg": 4.5, "sampler": "euler"},
        "min_steps": 10, "max_steps": 50,
    },
    "sd3.5-large": {


        "presets": {
            "rapide":    {"steps": 15, "cfg": 3.5, "quant": "Q5_0", "label": "⚡ Rapide (15 etapes, Q5_0)"},
            "equilibre": {"steps": 30, "cfg": 4.5, "quant": "Q5_1", "label": "⚖️ Equilibre (30 etapes, Q5_1)"},
            "qualite":   {"steps": 45, "cfg": 5.5, "quant": "Q5_1", "label": "✨ Qualite (45 etapes, Q5_1)"},
        },
        "name": "Stable Diffusion 3.5 Large",
        "arch": "sd3",
        "repo": "city96/stable-diffusion-3.5-large-gguf",
        "quants": ["Q5_0", "Q5_1"],
        "default_quant": "Q5_1",
        "file_for_quant": {
            "Q5_0": "sd3.5_large-Q5_0.gguf",
            "Q5_1": "sd3.5_large-Q5_1.gguf",
        },
        "size_gb": {"Q5_0": 5.8, "Q5_1": 6.3},
        "deps": ["vae_sd3", "clip_l", "clip_g", "t5xxl"],
        "supports_neg": True,
        "diffusion_fa": False,
        "license": "Stability AI Community (non-commercial <$1M)",
        "supports_img2img": True,
        # Img2img classique : une seule image de depart + force (pas de references multiples).
        "input_modes": ["init"],
        "max_ref_images": 1,
        "hf_url": "https://huggingface.co/city96/stable-diffusion-3.5-large-gguf",
        "vram_min_gb": 6,
        "needs_token": True,
        "desc": "Modele 8B haute qualite. VAE SD3 requis (gated).",
        "defaults": {"steps": 30, "cfg": 4.5, "sampler": "euler"},
        "min_steps": 10, "max_steps": 50,
    },
    "sd3.5-large-turbo": {


        "presets": {
            "rapide":    {"steps": 4,  "cfg": 0.4, "quant": "Q4_1", "label": "⚡ Ultra-rapide (4 etapes, Q4_1)"},
            "equilibre": {"steps": 4,  "cfg": 0.4, "quant": "Q5_1", "label": "⚖️ Equilibre (4 etapes, Q5_1)"},
            "qualite":   {"steps": 6,  "cfg": 0.6, "quant": "Q5_1", "label": "✨ Qualite (6 etapes, Q5_1)"},
        },
        "name": "Stable Diffusion 3.5 Large Turbo",
        "arch": "sd3",
        "repo": "city96/stable-diffusion-3.5-large-turbo-gguf",
        "quants": ["Q4_1", "Q5_1"],
        "default_quant": "Q5_1",
        "file_for_quant": {
            "Q4_1": "sd3.5_large_turbo-Q4_1.gguf",
            "Q5_1": "sd3.5_large_turbo-Q5_1.gguf",
        },
        "size_gb": {"Q4_1": 5.3, "Q5_1": 6.3},
        "deps": ["vae_sd3", "clip_l", "clip_g", "t5xxl"],
        "supports_neg": False,
        "diffusion_fa": False,
        "license": "Stability AI Community (non-commercial <$1M)",
        "supports_img2img": True,
        # Img2img classique : une seule image de depart + force (pas de references multiples).
        "input_modes": ["init"],
        "max_ref_images": 1,
        "hf_url": "https://huggingface.co/city96/stable-diffusion-3.5-large-turbo-gguf",
        "vram_min_gb": 6,
        "needs_token": True,
        "desc": "Version distillee (4 etapes). VAE SD3 requis (gated). Ultra-rapide.",
        "defaults": {"steps": 4, "cfg": 0.4, "sampler": "euler"},
        "min_steps": 1, "max_steps": 8,
    },
    "flux2-klein-4b": {

        "presets": {
            "rapide":    {"steps": 4,  "cfg": 1.0, "quant": "Q4_K_M", "label": "⚡ Ultra-rapide (4 etapes, Q4)"},
            "equilibre": {"steps": 4,  "cfg": 1.0, "quant": "Q5_K_M", "label": "⚖️ Equilibre (4 etapes, Q5)"},
            "qualite":   {"steps": 6,  "cfg": 2.0, "quant": "Q6_K",   "label": "✨ Qualite (6 etapes, Q6)"},
            "optimise":  {"steps": 4,  "cfg": 1.0, "quant": "Q4_K_M", "label": "🎯 Optimise edition (4 etapes, Q4)"},
        },
        "name": "FLUX.2 Klein 4B",
        "arch": "flux2",
        "repo": "unsloth/FLUX.2-klein-4B-GGUF",
        "quants": ["Q4_K_M", "Q5_K_M", "Q6_K"],
        "default_quant": "Q5_K_M",
        "file_for_quant": {
            "Q4_K_M": "flux-2-klein-4b-Q4_K_M.gguf",
            "Q5_K_M": "flux-2-klein-4b-Q5_K_M.gguf",
            "Q6_K":   "flux-2-klein-4b-Q6_K.gguf",
        },
        "size_gb": {"Q4_K_M": 2.6, "Q5_K_M": 2.9, "Q6_K": 3.3},
        "deps": ["vae_flux2", "qwen3_4b"],
        "supports_neg": False,
        "supports_img2img": True,
        # --- Edition multi-images ---
        "supports_ref_images": True,
        "supports_outpainting": True,
        "input_modes": ["ref"],
        "max_ref_images": 10,
        "ref_tag_syntax": None,
        "ref_needs_vlm": False,
        "ref_hint": ("Klein ne « voit » pas les images avec son encodeur de texte : les références "
                     "vont directement au DiT. N'utilisez PAS de balise <image1> — désignez chaque "
                     "image par sa position en langage naturel (« the man in image 1 »). "
                     "4B = 4 Go de poids : restez à 2-3 références, sinon baissez le budget pixels."),
        "ref_examples": [
            "Place the watch from image 2 on the desk in image 1, keep the morning light and the "
            "wood texture of image 1",
            "Replace the child in image 1 with the cat from image 2, same pose and same framing",
        ],
        "needs_token": False,
        "license": "Apache 2.0 (libre, commercial OK)",
        "hf_url": "https://huggingface.co/unsloth/FLUX.2-klein-4B-GGUF",
        "vram_min_gb": 4,
        "desc": "Ultra-rapide (4 etapes), sous la seconde. Generation + edition unifiees (jusqu'à 10 references).",
        "defaults": {"steps": 4, "cfg": 1.0, "sampler": "euler"},
        "min_steps": 1, "max_steps": 10,
    },
    "flux2-klein-9b": {

        "presets": {
            "rapide":    {"steps": 4,  "cfg": 1.0, "quant": "Q4_K_M", "label": "⚡ Ultra-rapide (4 etapes, Q4)"},
            "equilibre": {"steps": 4,  "cfg": 1.0, "quant": "Q5_K_M", "label": "⚖️ Equilibre (4 etapes, Q5)"},
            "qualite":   {"steps": 6,  "cfg": 2.0, "quant": "Q6_K",   "label": "✨ Qualite (6 etapes, Q6)"},
            "optimise":  {"steps": 4,  "cfg": 1.0, "quant": "Q4_K_M", "label": "🎯 Optimise edition (4 etapes, Q4)"},
        },
        "name": "FLUX.2 Klein 9B",
        "arch": "flux2",
        "repo": "unsloth/FLUX.2-klein-9B-GGUF",
        "quants": ["Q4_K_M", "Q5_K_M", "Q6_K"],
        "default_quant": "Q5_K_M",
        "file_for_quant": {
            "Q4_K_M": "flux-2-klein-9b-Q4_K_M.gguf",
            "Q5_K_M": "flux-2-klein-9b-Q5_K_M.gguf",
            "Q6_K":   "flux-2-klein-9b-Q6_K.gguf",
        },
        "size_gb": {"Q4_K_M": 5.9, "Q5_K_M": 6.7, "Q6_K": 7.5},
        "deps": ["vae_flux2", "qwen3_8b"],
        "supports_neg": False,
        "supports_img2img": True,
        # --- Edition multi-images ---
        "supports_ref_images": True,
        "supports_outpainting": True,
        "input_modes": ["ref"],
        "max_ref_images": 10,
        "ref_tag_syntax": None,
        "ref_needs_vlm": False,
        "ref_hint": ("Pas de balise <image1> avec Klein : désignez les images par leur position en "
                     "langage naturel (« the man in image 1 »). Le 9B encaisse mieux 4-6 références "
                     "que le 4B, mais chaque image coûte des tokens."),
        "ref_examples": [
            "Keep the face and hair of the woman in image 1, dress her in the red silk dress from "
            "image 2, studio lighting like image 3",
            "Put the product from image 2 on the marble table in image 1, preserve the shadows of image 1",
        ],
        "needs_token": True,
        "license": "FLUX Non-Commercial (usage perso uniquement)",
        "hf_url": "https://huggingface.co/unsloth/FLUX.2-klein-9B-GGUF",
        "vram_min_gb": 8,
        "desc": "Modele phare BFL. Qualite top en sous-seconde (4 etapes), édition jusqu'à 10 references. Non-commercial.",
        "defaults": {"steps": 4, "cfg": 1.0, "sampler": "euler"},
        "min_steps": 1, "max_steps": 10,
    },
    # FLUX.3 Image Klein (arch flux3, cf. docs/flux3.md de stable-diffusion.cpp) :
    #   - DiT flow-map distille 5.6B : 16 etapes, CFG 1 (pas de prompt negatif) ;
    #   - VAE FLUX.2 (vae_flux2) + encodeur Qwen3-VL-4B (qwen3vl_4b, partage avec Iris-3B) ;
    #   - edition jusqu'a 10 references (-r, preset moteur "flux2" : pas de mmproj, pas de balise) ;
    #   - poids officiels : black-forest-labs/flux-3-image-klein (safetensors, gated).
    #   - variante base (50 etapes, CFG 3.5) : possederait le meme arch mais d'autres defauts.
    # Quantification retenue : DogukanUrker/FLUX.3-Image-Klein-GGUF -> convertie AVEC sd-cli
    # (commit 8cd731e, celui que telecharge le bouton "Installer le moteur") et testee dessus ;
    # pics VRAM documentes a 1024x1024 encodeur compris : Q3_K 6.8 / Q4_K 7.4 / Q6_K 8.7 / Q8_0 9.8 Go.
    # Alternative si besoin d'autres quants : unsloth/flux-3-image-klein-GGUF (Q4_K_M a Q8_0 +
    # UD-Q2_K_XL..UD-Q5_K_XL, meilleurs a taille egale, mais conversion orientee diffusers/ComfyUI)
    # ou Abiray/flux-3-image-klein-sd-GGUF (Q2_K a Q8_0).
    # Requiert sd-cli 8cd731e (15 oct. 2026) ou plus recent (support FLUX.3, PR #2143).
    "flux3-image-klein": {

        "presets": {
            "rapide":    {"steps": 12, "cfg": 1.0, "quant": "Q4_K", "label": "⚡ Rapide (12 etapes, Q4_K)"},
            "equilibre": {"steps": 16, "cfg": 1.0, "quant": "Q6_K", "label": "⚖️ Equilibre (16 etapes, Q6_K)"},
            "qualite":   {"steps": 20, "cfg": 1.0, "quant": "Q8_0", "label": "✨ Qualite (20 etapes, Q8_0)"},
            "leger":     {"steps": 16, "cfg": 1.0, "quant": "Q3_K", "label": "💾 Léger (16 etapes, Q3_K, 2,6 Go)"},
            "optimise":  {"steps": 16, "cfg": 1.0, "quant": "Q4_K", "label": "🎯 Optimise edition (16 etapes, Q4_K)"},
        },
        "name": "FLUX.3 Image Klein",
        "arch": "flux3",
        "repo": "DogukanUrker/FLUX.3-Image-Klein-GGUF",
        "quants": ["Q3_K", "Q4_K", "Q6_K", "Q8_0"],
        "default_quant": "Q4_K",
        "file_for_quant": {
            "Q3_K": "flux3-image-klein-Q3_K.gguf",
            "Q4_K": "flux3-image-klein-Q4_K.gguf",
            "Q6_K": "flux3-image-klein-Q6_K.gguf",
            "Q8_0": "flux3-image-klein-Q8_0.gguf",
        },
        "size_gb": {"Q3_K": 2.6, "Q4_K": 3.3, "Q6_K": 4.7, "Q8_0": 6.0},
        "deps": ["vae_flux2", "qwen3vl_4b"],
        "supports_neg": False,
        "supports_img2img": True,
        # --- Edition multi-images (comme FLUX.2 Klein : jusqu'a 10 references) ---
        "supports_ref_images": True,
        "supports_outpainting": True,
        "input_modes": ["ref"],
        "max_ref_images": 10,
        "ref_tag_syntax": None,
        "ref_needs_vlm": False,
        "ref_hint": ("Klein ne « voit » pas les images avec son encodeur de texte : les références "
                     "vont directement au DiT. N'utilisez PAS de balise <image1> — désignez chaque "
                     "image par sa position en langage naturel (« the woman in image 1 »). "
                     "DiT distillé (16 étapes, CFG 1) : décrivez le résultat final souhaité plutôt "
                     "que le processus ; 4-6 références passent sans problème, au-delà baissez le "
                     "budget pixels."),
        "ref_examples": [
            "Put the jacket from image 2 on the man in image 1, keep his face, his pose and the "
            "street lighting of image 1",
            "Replace the sky in image 1 with the sunset of image 2, keep the buildings and the "
            "reflections on the water",
        ],
        "needs_token": False,
        "license": "FLUX Kommunity License (non-commercial, exception commerciale)",
        "hf_url": "https://huggingface.co/DogukanUrker/FLUX.3-Image-Klein-GGUF",
        "vram_min_gb": 8,
        "desc": ("Successeur de FLUX.2 Klein : generation + edition (10 references) en 16 etapes, "
                 "texte lisible et boites englobantes dans le prompt. GGUF convertis avec sd-cli "
                 "8cd731e (Q3_K 6,8 Go de VRAM a Q8_0 9,8 Go, encodeur compris). Requiert ce meme "
                 "moteur ou plus recent. Reutilise Qwen3-VL-4B et le VAE FLUX.2."),
        "defaults": {"steps": 16, "cfg": 1.0, "sampler": "euler"},
        "min_steps": 8, "max_steps": 30,
    },
    # ---- Fibo 2.0 (Bria AI, arch fibo2, cf. docs/fibo2.md de stable-diffusion.cpp) ----
    # Quants GGUF : molbal/fibo-2.0-GGUF (formats standard uniquement ; le Q8_CR propriétaire
    # de ComfyUI-GGUF-reboot n'est pas pris en charge). Pas de Q3 : la qualité chute trop.
    # Encodeur Qwen3-VL-4B (qwen3vl_4b) + mmproj pour les références ; VAE FLUX.2.
    # Licence CC BY-NC 4.0 : usage non commercial.
    "fibo2-dev": {
        "presets": {
            "rapide":    {"steps": 30, "cfg": 5.0, "quant": "Q4_K_M", "label": "⚡ Rapide (30 étapes, Q4_K_M)"},
            "equilibre": {"steps": 50, "cfg": 5.0, "quant": "Q6_K",   "label": "⚖️ Équilibre (50 étapes, Q6_K)"},
            "qualite":   {"steps": 50, "cfg": 5.0, "quant": "Q8_0",   "label": "✨ Qualité (50 étapes, Q8_0)"},
        },
        "name": "Fibo 2.0 Dev",
        "arch": "fibo2",
        "repo": "molbal/fibo-2.0-GGUF",
        "quants": ["Q4_K_M", "Q6_K", "Q8_0"],
        "default_quant": "Q6_K",
        "file_for_quant": {
            "Q4_K_M": "fibo2-dev-Q4_K_M.gguf",
            "Q6_K":   "fibo2-dev-Q6_K.gguf",
            "Q8_0":   "fibo2-dev-Q8_0.gguf",
        },
        "size_gb": {"Q4_K_M": 5.5, "Q6_K": 7.0, "Q8_0": 8.9},
        "deps": ["vae_flux2", "qwen3vl_4b", "mmproj_qwen3vl_4b"],
        "llm_dep": "qwen3vl_4b",
        "mmproj_dep": "mmproj_qwen3vl_4b",
        "supports_neg": True,
        "supports_img2img": False,
        "needs_token": False,
        # --- Texte-image + édition (références) ---
        "supports_ref_images": True,
        "supports_outpainting": True,
        "input_modes": ["ref"],
        "max_ref_images": 4,
        "ref_tag_syntax": "<image_{n}>",
        "ref_needs_vlm": True,
        "ref_hint": ("Fibo cite les images avec <image_1>, <image_2>… (image 1 = le canvas). "
                     "Chaque référence ajoute des tokens : au-delà de 2-3, baissez le budget pixels."),
        "ref_examples": [
            "Keep the person in <image_1> unchanged, dress them with the jacket from <image_2>",
            "Replace the background of <image_1> with the city street of <image_2>, keep the lighting",
        ],
        "license": "CC BY-NC 4.0 (Bria AI, non commercial)",
        "hf_url": "https://huggingface.co/molbal/fibo-2.0-GGUF",
        "vram_min_gb": 8,
        "desc": ("Fibo 2.0 Dev de Bria AI : génération (50 étapes, CFG 5) et édition par références. "
                 "Requiert sd-cli récent (support Fibo 2.0 depuis octobre 2026). Non commercial."),
        "defaults": {"steps": 50, "cfg": 5.0, "sampler": "euler"},
        "min_steps": 20, "max_steps": 80,
    },
    "fibo2-edit-turbo": {
        "presets": {
            "rapide":    {"steps": 4, "cfg": 1.0, "quant": "Q4_K_M", "label": "⚡ Rapide (4 étapes, Q4_K_M)"},
            "equilibre": {"steps": 4, "cfg": 1.0, "quant": "Q6_K",   "label": "⚖️ Équilibre (4 étapes, Q6_K)"},
            "qualite":   {"steps": 4, "cfg": 1.0, "quant": "Q8_0",   "label": "✨ Qualité (4 étapes, Q8_0)"},
        },
        "name": "Fibo 2.0 Edit Turbo",
        "arch": "fibo2",
        "repo": "molbal/fibo-2.0-GGUF",
        "quants": ["Q4_K_M", "Q6_K", "Q8_0"],
        "default_quant": "Q6_K",
        "file_for_quant": {
            "Q4_K_M": "fibo2-edit-turbo-Q4_K_M.gguf",
            "Q6_K":   "fibo2-edit-turbo-Q6_K.gguf",
            "Q8_0":   "fibo2-edit-turbo-Q8_0.gguf",
        },
        "size_gb": {"Q4_K_M": 5.5, "Q6_K": 7.0, "Q8_0": 8.9},
        "deps": ["vae_flux2", "qwen3vl_4b", "mmproj_qwen3vl_4b"],
        "llm_dep": "qwen3vl_4b",
        "mmproj_dep": "mmproj_qwen3vl_4b",
        "supports_neg": False,
        "supports_img2img": False,
        "needs_token": False,
        # --- Édition par références uniquement (distillé pour l'édition en 4 étapes) ---
        "supports_ref_images": True,
        "supports_outpainting": True,
        "input_modes": ["ref"],
        "max_ref_images": 4,
        "ref_tag_syntax": "<image_{n}>",
        "ref_needs_vlm": True,
        "ref_hint": ("Edit Turbo est distillé pour l'édition : image 1 = le canvas, les autres = références. "
                     "Citez-les avec <image_2>, <image_3>… ou par position (« the man in image 1 »)."),
        "ref_examples": [
            "Change the outfit of the person in <image_1> to the red dress from <image_2>",
            "Put the product from <image_2> on the table in <image_1>, keep the lighting of <image_1>",
        ],
        "fixed_steps": 4,
        "fixed_cfg": 1.0,
        "license": "CC BY-NC 4.0 (Bria AI, non commercial)",
        "hf_url": "https://huggingface.co/molbal/fibo-2.0-GGUF",
        "vram_min_gb": 8,
        "desc": ("Fibo 2.0 Edit Turbo de Bria AI : édition rapide (4 étapes, CFG 1) avec références. "
                 "Conçu pour l'édition plutôt que pour la génération pure. Non commercial."),
        "defaults": {"steps": 4, "cfg": 1.0, "sampler": "euler"},
        "min_steps": 4, "max_steps": 4,
    },

    # ---- MOSS-Image (OpenMOSS, arch moss_image, cf. docs/moss_image.md de stable-diffusion.cpp) ----
    # DiT 5B + VAE FLUX.2 + encodeur Qwen3.5-9B (GGUF) + tokenizer.json externe (--tokenizer).
    # Quants officiels leejet/MOSS-Image-*-GGUF (Q2_K et Q4_0 écartés : trop dégradés / peu utiles).
    "moss-image-sft": {
        "presets": {
            "leger":     {"steps": 50, "cfg": 3.0, "quant": "Q3_K", "label": "💾 Léger (50 étapes, Q3_K)"},
            "equilibre": {"steps": 50, "cfg": 3.0, "quant": "Q4_K", "label": "⚖️ Équilibre (50 étapes, Q4_K)"},
            "qualite":   {"steps": 50, "cfg": 3.0, "quant": "Q8_0", "label": "✨ Qualité (50 étapes, Q8_0)"},
        },
        "name": "MOSS-Image SFT",
        "arch": "moss_image",
        "repo": "leejet/MOSS-Image-SFT-GGUF",
        "quants": ["Q3_K", "Q4_K", "Q5_K", "Q6_K", "Q8_0"],
        "default_quant": "Q4_K",
        "file_for_quant": {
            "Q3_K": "MOSS-Image-SFT-Q3_K.gguf",
            "Q4_K": "MOSS-Image-SFT-Q4_K.gguf",
            "Q5_K": "MOSS-Image-SFT-Q5_K.gguf",
            "Q6_K": "MOSS-Image-SFT-Q6_K.gguf",
            "Q8_0": "MOSS-Image-SFT-Q8_0.gguf",
        },
        "size_gb": {"Q3_K": 2.7, "Q4_K": 3.3, "Q5_K": 3.9, "Q6_K": 4.6, "Q8_0": 5.7},
        "deps": ["vae_flux2", "qwen35_9b", "moss_tokenizer"],
        "llm_dep": "qwen35_9b",
        "tokenizer_dep": "moss_tokenizer",
        "supports_neg": True,
        "supports_img2img": False,
        "needs_token": False,
        "license": "Apache 2.0 (libre, commercial OK)",
        "hf_url": "https://huggingface.co/leejet/MOSS-Image-SFT-GGUF",
        "vram_min_gb": 8,
        "desc": ("MOSS-Image SFT (OpenMOSS) : version ajustée, à privilégier pour la génération standard. "
                 "Texte dans l'image et mise en page soignés. 50 étapes, CFG 3."),
        "defaults": {"steps": 50, "cfg": 3.0, "sampler": "euler"},
        "min_steps": 20, "max_steps": 80,
    },
    "moss-image-base": {
        "presets": {
            "leger":     {"steps": 50, "cfg": 3.0, "quant": "Q3_K", "label": "💾 Léger (50 étapes, Q3_K)"},
            "equilibre": {"steps": 50, "cfg": 3.0, "quant": "Q4_K", "label": "⚖️ Équilibre (50 étapes, Q4_K)"},
            "qualite":   {"steps": 50, "cfg": 3.0, "quant": "Q8_0", "label": "✨ Qualité (50 étapes, Q8_0)"},
        },
        "name": "MOSS-Image Base",
        "arch": "moss_image",
        "repo": "leejet/MOSS-Image-Base-GGUF",
        "quants": ["Q3_K", "Q4_K", "Q5_K", "Q6_K", "Q8_0"],
        "default_quant": "Q4_K",
        "file_for_quant": {
            "Q3_K": "MOSS-Image-Base-Q3_K.gguf",
            "Q4_K": "MOSS-Image-Base-Q4_K.gguf",
            "Q5_K": "MOSS-Image-Base-Q5_K.gguf",
            "Q6_K": "MOSS-Image-Base-Q6_K.gguf",
            "Q8_0": "MOSS-Image-Base-Q8_0.gguf",
        },
        "size_gb": {"Q3_K": 2.7, "Q4_K": 3.3, "Q5_K": 3.9, "Q6_K": 4.6, "Q8_0": 5.7},
        "deps": ["vae_flux2", "qwen35_9b", "moss_tokenizer"],
        "llm_dep": "qwen35_9b",
        "tokenizer_dep": "moss_tokenizer",
        "supports_neg": True,
        "supports_img2img": False,
        "needs_token": False,
        "license": "Apache 2.0 (libre, commercial OK)",
        "hf_url": "https://huggingface.co/leejet/MOSS-Image-Base-GGUF",
        "vram_min_gb": 8,
        "desc": ("MOSS-Image Base (OpenMOSS) : checkpoint non ajusté, plutôt destiné aux LoRA entraînés "
                 "sur Base. Résultat brut par défaut : préférez MOSS-Image SFT pour une génération standard."),
        "defaults": {"steps": 50, "cfg": 3.0, "sampler": "euler"},
        "min_steps": 20, "max_steps": 80,
    },

    # ---- Krea 2 Turbo (arch krea2, cf. docs/krea2.md de stable-diffusion.cpp) ----
    # DiT 12-13B distillé : 8 étapes, CFG 1 (pas de prompt négatif). VAE Wan 2.1, encodeur Qwen3-VL-4B.
    # Quants : dépôt officiel réalrebelai/KREA-2_GGUFs, dossier TURBO/ (Q4_K_S et Q5_K_M absents du dépôt).
    "krea2-turbo": {
        "presets": {
            "leger":     {"steps": 8, "cfg": 1.0, "quant": "Q3_K_M", "label": "💾 Léger (8 étapes, Q3_K_M)"},
            "equilibre": {"steps": 8, "cfg": 1.0, "quant": "Q4_K_M", "label": "⚖️ Équilibre (8 étapes, Q4_K_M)"},
            "qualite":   {"steps": 8, "cfg": 1.0, "quant": "Q6_K",   "label": "✨ Qualité (8 étapes, Q6_K)"},
        },
        "name": "Krea 2 Turbo",
        "arch": "krea2",
        "repo": "realrebelai/KREA-2_GGUFs",
        "quants": ["Q3_K_M", "Q4_K_M", "Q5_K_S", "Q6_K", "Q8_0"],
        "default_quant": "Q4_K_M",
        "file_for_quant": {
            "Q3_K_M": "Krea-2-Turbo-Q3_K_M.gguf",
            "Q4_K_M": "Krea-2-Turbo-Q4_K_M.gguf",
            "Q5_K_S": "Krea-2-Turbo-Q5_K_S.gguf",
            "Q6_K":   "Krea-2-Turbo-Q6_K.gguf",
            "Q8_0":   "Krea-2-Turbo-Q8_0.gguf",
        },
        # Le fichier est dans le sous-dossier TURBO/ du dépôt, aplati à la copie locale.
        "remote_file_for_quant": {
            "Q3_K_M": "TURBO/Krea-2-Turbo-Q3_K_M.gguf",
            "Q4_K_M": "TURBO/Krea-2-Turbo-Q4_K_M.gguf",
            "Q5_K_S": "TURBO/Krea-2-Turbo-Q5_K_S.gguf",
            "Q6_K":   "TURBO/Krea-2-Turbo-Q6_K.gguf",
            "Q8_0":   "TURBO/Krea-2-Turbo-Q8_0.gguf",
        },
        "size_gb": {"Q3_K_M": 5.5, "Q4_K_M": 7.2, "Q5_K_S": 8.8, "Q6_K": 10.5, "Q8_0": 13.6},
        "deps": ["vae_wan21", "qwen3vl_4b"],
        "llm_dep": "qwen3vl_4b",
        "supports_neg": False,
        "supports_img2img": False,
        "needs_token": False,
        "license": "Krea 2 Community License (voir conditions Krea)",
        "hf_url": "https://huggingface.co/realrebelai/KREA-2_GGUFs",
        "vram_min_gb": 8,
        "desc": ("Krea 2 Turbo (Krea) : génération photoréaliste en 8 étapes, CFG 1. "
                 "Requiert stable-diffusion.cpp master-721 ou plus récent."),
        "defaults": {"steps": 8, "cfg": 1.0, "sampler": "euler"},
        "min_steps": 4, "max_steps": 20,
    },
    # ---- Nouveaux modeles Qualite / Details / Edition (reutilisant les dependances existantes) ----
    "flux-dev": {
        "presets": {
            "rapide":    {"steps": 18, "cfg": 1.0, "quant": "Q4_K_S", "label": "⚡ Rapide (18 étapes, Q4_K_S)"},
            "equilibre": {"steps": 24, "cfg": 1.0, "quant": "Q5_K_S", "label": "⚖️ Équilibre (24 étapes, Q5_K_S)"},
            "qualite":   {"steps": 28, "cfg": 1.0, "quant": "Q8_0",   "label": "✨ Qualité max (28 étapes, Q8_0)"},
        },
        "name": "FLUX.1 Dev (Haute Finesse)",
        "arch": "flux",
        "repo": "unsloth/FLUX.1-dev-GGUF",
        "quants": ["Q4_K_S", "Q5_K_S", "Q6_K", "Q8_0"],
        "default_quant": "Q5_K_S",
        "file_for_quant": {
            "Q4_K_S": "flux1-dev-Q4_K_S.gguf",
            "Q5_K_S": "flux1-dev-Q5_K_S.gguf",
            "Q6_K":   "flux1-dev-Q6_K.gguf",
            "Q8_0":   "flux1-dev-Q8_0.gguf",
        },
        "size_gb": {"Q4_K_S": 6.8, "Q5_K_S": 8.3, "Q6_K": 9.8, "Q8_0": 12.7},
        "deps": ["vae_flux", "clip_l", "t5xxl"],
        "supports_neg": False,
        "supports_img2img": True,
        "input_modes": ["init"],
        "needs_token": False,
        "license": "FLUX.1 [dev] Non-Commercial License",
        "hf_url": "https://huggingface.co/unsloth/FLUX.1-dev-GGUF",
        "vram_min_gb": 8,
        "desc": (
            "Version complète de FLUX.1 (20 à 28 étapes) : nettement supérieure à FLUX Schnell "
            "pour le grain de peau, les mains, la lumière cinématique et les micro-détails. "
            "Supporte l'img2img et les LoRA FLUX, et réutilise exactement les dépendances de FLUX Schnell."
        ),
        "defaults": {"steps": 24, "cfg": 1.0, "sampler": "euler"},
        "min_steps": 12, "max_steps": 40,
    },
    "flux-kontext-dev": {
        "presets": {
            "rapide":    {"steps": 18, "cfg": 1.0, "quant": "Q4_K_S", "label": "⚡ Rapide (18 étapes, Q4_K_S)"},
            "equilibre": {"steps": 24, "cfg": 1.0, "quant": "Q5_K_M", "label": "⚖️ Équilibre (24 étapes, Q5_K_M)"},
            "qualite":   {"steps": 28, "cfg": 1.0, "quant": "Q8_0",   "label": "✨ Qualité (28 étapes, Q8_0)"},
        },
        "name": "FLUX.1 Kontext Dev (Édition & Cohérence)",
        "arch": "flux_kontext",
        "repo": "QuantStack/FLUX.1-Kontext-dev-GGUF",
        "quants": ["Q4_K_S", "Q5_K_M", "Q6_K", "Q8_0"],
        "default_quant": "Q5_K_M",
        "file_for_quant": {
            "Q4_K_S": "flux1-kontext-dev-Q4_K_S.gguf",
            "Q5_K_M": "flux1-kontext-dev-Q5_K_M.gguf",
            "Q6_K":   "flux1-kontext-dev-Q6_K.gguf",
            "Q8_0":   "flux1-kontext-dev-Q8_0.gguf",
        },
        "size_gb": {"Q4_K_S": 6.8, "Q5_K_M": 8.5, "Q6_K": 9.8, "Q8_0": 12.7},
        "deps": ["vae_flux", "clip_l", "t5xxl"],
        "supports_neg": False,
        "supports_img2img": True,
        "supports_ref_images": True,
        "supports_outpainting": True,
        "input_modes": ["ref"],
        "max_ref_images": 4,
        "ref_tag_syntax": None,
        "ref_needs_vlm": False,
        "ref_hint": (
            "FLUX.1 Kontext excelle pour modifier un élément précis, changer un texte, l'éclairage "
            "ou l'angle d'un même personnage en gardant son identité intacte. Décrivez directement "
            "la modification souhaitée en langage naturel (sans balise <image1>)."
        ),
        "ref_examples": [
            "Keep the character's face and outfit identical, place them in a sunlit Parisian cafe",
            "Change the text on the sign to 'LOCAL STUDIO' while keeping the exact font style and lighting",
        ],
        "needs_token": False,
        "license": "FLUX.1 [dev] Non-Commercial License",
        "hf_url": "https://huggingface.co/QuantStack/FLUX.1-Kontext-dev-GGUF",
        "vram_min_gb": 8,
        "desc": (
            "Modèle d'édition contextuelle de Black Forest Labs : modifie une scène, un texte "
            "ou un personnage avec le piqué photographique de FLUX.1. Réutilise 100 % des "
            "dépendances de FLUX.1 (vae_flux, clip_l, t5xxl)."
        ),
        "defaults": {"steps": 24, "cfg": 1.0, "sampler": "euler"},
        "min_steps": 12, "max_steps": 36,
    },
    "chroma": {
        "presets": {
            "rapide":    {"steps": 20, "cfg": 4.0, "quant": "Q4_0", "label": "⚡ Rapide (20 étapes, Q4_0)"},
            "equilibre": {"steps": 26, "cfg": 4.0, "quant": "Q4_0", "label": "⚖️ Équilibre (26 étapes, Q4_0)"},
            "qualite":   {"steps": 32, "cfg": 4.5, "quant": "Q8_0", "label": "✨ Qualité (32 étapes, Q8_0)"},
        },
        "name": "Chroma Unlocked v40 (Textures & Prompt Négatif)",
        "arch": "chroma",
        "repo": "silveroxides/Chroma-GGUF",
        "quants": ["Q4_0", "Q8_0"],
        "default_quant": "Q4_0",
        "file_for_quant": {
            "Q4_0": "chroma-unlocked-v40-Q4_0.gguf",
            "Q8_0": "chroma-unlocked-v40-Q8_0.gguf",
        },
        # Les fichiers vivent dans le sous-dossier chroma-unlocked-v40/ du dépôt
        # (aplatis dans models/diffusion/ à la copie locale).
        "remote_file_for_quant": {
            "Q4_0": "chroma-unlocked-v40/chroma-unlocked-v40-Q4_0.gguf",
            "Q8_0": "chroma-unlocked-v40/chroma-unlocked-v40-Q8_0.gguf",
        },
        "size_gb": {"Q4_0": 5.4, "Q8_0": 9.7},
        "deps": ["vae_flux", "t5xxl"],
        "supports_neg": True,
        "supports_img2img": True,
        "input_modes": ["init"],
        "needs_token": False,
        "license": "Apache 2.0 (lodestones)",
        "hf_url": "https://huggingface.co/silveroxides/Chroma-GGUF",
        "vram_min_gb": 6,
        "desc": (
            "Dérivé dé-distillé de FLUX (8,9B) : contrairement à FLUX classique, Chroma comprend "
            "un vrai Prompt Négatif (CFG 4.0), évite l'effet peau lissée/plastique et produit des "
            "textures organiques ultra-détaillées. N'utilise que vae_flux et t5xxl. "
            "Le dépôt upstream (silveroxides) ne publie plus en v40 que Q4_0 et Q8_0."
        ),
        "defaults": {"steps": 26, "cfg": 4.0, "sampler": "euler"},
        "min_steps": 16, "max_steps": 45,
    },
    "chroma-radiance": {
        "presets": {
            "rapide":    {"steps": 20, "cfg": 4.0, "quant": "Q4_K_S", "label": "⚡ Rapide (20 étapes, Q4_K_S)"},
            "equilibre": {"steps": 26, "cfg": 4.0, "quant": "Q5_K_M", "label": "⚖️ Équilibre (26 étapes, Q5_K_M)"},
            "qualite":   {"steps": 32, "cfg": 4.5, "quant": "Q8_0",   "label": "✨ Qualité (32 étapes, Q8_0)"},
        },
        "name": "Chroma1-Radiance v0.3 (Pixel-Space sans VAE)",
        "arch": "chroma_radiance",
        "repo": "silveroxides/Chroma1-Radiance-GGUF",
        "quants": ["Q4_K_S", "Q5_K_M", "Q6_K", "Q8_0"],
        "default_quant": "Q5_K_M",
        "file_for_quant": {
            "Q4_K_S": "Chroma1-Radiance-v0.3-Q4_K_S.gguf",
            "Q5_K_M": "Chroma1-Radiance-v0.3-Q5_K_M.gguf",
            "Q6_K":   "Chroma1-Radiance-v0.3-Q6_K.gguf",
            "Q8_0":   "Chroma1-Radiance-v0.3-Q8_0.gguf",
        },
        # v0.4 (dernière version amont) ne publie plus que BF16 et Q8_0 ;
        # v0.3 reste la dernière à proposer des quants intermédiaires.
        "remote_file_for_quant": {
            "Q4_K_S": "Chroma1-Radiance-v0.3/Chroma1-Radiance-v0.3-Q4_K_S.gguf",
            "Q5_K_M": "Chroma1-Radiance-v0.3/Chroma1-Radiance-v0.3-Q5_K_M.gguf",
            "Q6_K":   "Chroma1-Radiance-v0.3/Chroma1-Radiance-v0.3-Q6_K.gguf",
            "Q8_0":   "Chroma1-Radiance-v0.3/Chroma1-Radiance-v0.3-Q8_0.gguf",
        },
        "size_gb": {"Q4_K_S": 5.8, "Q5_K_M": 7.1, "Q6_K": 8.2, "Q8_0": 10.4},
        "deps": ["t5xxl"],
        "needs_vae": False,
        "supports_neg": True,
        "supports_img2img": False,
        "needs_token": False,
        "license": "Apache 2.0 (lodestones)",
        "hf_url": "https://huggingface.co/silveroxides/Chroma1-Radiance-GGUF",
        "vram_min_gb": 6,
        "desc": (
            "Variante Radiance de Chroma qui génère directement dans l'espace pixel (sans perte "
            "de compression VAE) : piqué micro-détails remarquable, lumière réaliste et support "
            "du Prompt Négatif. Ne requiert que t5xxl. Version v0.3 : v0.4 ne propose plus que "
            "BF16 et Q8_0 (10,4 Go) sur le dépôt upstream."
        ),
        "defaults": {"steps": 26, "cfg": 4.0, "sampler": "euler"},
        "min_steps": 16, "max_steps": 45,
    },
    "longcat-image": {
        "presets": {
            "rapide":    {"steps": 20, "cfg": 4.5, "quant": "Q4_K_M", "label": "⚡ Rapide (20 étapes, Q4_K_M)"},
            "equilibre": {"steps": 28, "cfg": 5.0, "quant": "Q6_K",   "label": "⚖️ Équilibre (28 étapes, Q6_K)"},
            "qualite":   {"steps": 35, "cfg": 5.0, "quant": "Q8_0",   "label": "✨ Qualité (35 étapes, Q8_0)"},
        },
        "name": "LongCat-Image (Photoréalisme & Texte)",
        "arch": "longcat",
        "repo": "vantagewithai/LongCat-Image-GGUF",
        "quants": ["Q4_K_M", "Q6_K", "Q8_0"],
        "default_quant": "Q4_K_M",
        "file_for_quant": {
            "Q4_K_M": "LongCat-Image-Q4_K_M.gguf",
            "Q6_K":   "LongCat-Image-Q6_K.gguf",
            "Q8_0":   "LongCat-Image-Q8_0.gguf",
        },
        "remote_file_for_quant": {
            "Q4_K_M": "comfy/LongCat-Image-Q4_K_M.gguf",
            "Q6_K":   "comfy/LongCat-Image-Q6_K.gguf",
            "Q8_0":   "comfy/LongCat-Image-Q8_0.gguf",
        },
        "size_gb": {"Q4_K_M": 3.7, "Q6_K": 5.2, "Q8_0": 6.7},
        "deps": ["vae_flux", "qwen25vl_7b"],
        "llm_dep": "qwen25vl_7b",
        "supports_neg": True,
        "supports_img2img": False,
        "needs_token": False,
        "license": "Apache 2.0 (Meituan LongCat)",
        "hf_url": "https://huggingface.co/vantagewithai/LongCat-Image-GGUF",
        "vram_min_gb": 8,
        "desc": (
            "Modèle DiT photoréaliste avec rendu de texte caractère par caractère (mettez le "
            "texte entre guillemets) et excellente fidélité aux prompts complexes. Réutilise "
            "vae_flux et Qwen2.5-VL-7B (déjà utilisé par Qwen-Image 2512)."
        ),
        "defaults": {"steps": 28, "cfg": 5.0, "sampler": "euler"},
        "min_steps": 16, "max_steps": 50,
    },
}


# --------------------------------------------------------------------------- #
#  Resolution de quant (pour les dependances GGUF)
# --------------------------------------------------------------------------- #
def _quant_of(filename: str):
    base = filename.rsplit(".", 1)[0]
    for part in base.split("-"):
        if re.fullmatch(r"Q\d[_A-Z0-9]*", part):
            return part
    return None


def _is_valid_dep(dep_id: str, p: Path) -> bool:
    """Verifie qu'un fichier correspond bien a la dependance attendue (evite les collisions)."""
    name = p.name.lower()
    if dep_id == "qwen3_4b":
        return ("qwen3" in name or "qwen_3" in name) and "4b" in name and "vl" not in name and "mmproj" not in name
    elif dep_id == "qwen3_8b":
        return ("qwen3" in name or "qwen_3" in name) and "8b" in name and "vl" not in name and "mmproj" not in name
    elif dep_id == "ministral_3b":
        return "ministral" in name
    elif dep_id == "qwen3vl_4b":
        return ("qwen3" in name or "qwen_3" in name) and "4b" in name and "vl" in name and "mmproj" not in name
    elif dep_id == "qwen3vl_8b":
        return ("qwen3" in name or "qwen_3" in name) and "8b" in name and "vl" in name and "mmproj" not in name
    elif dep_id == "qwen25vl_7b":
        return ("qwen2.5" in name or "qwen2_5" in name or "qwen25" in name) and "vl" in name and "mmproj" not in name
    elif dep_id == "mmproj_qwen3vl_8b":
        return "mmproj" in name and ("qwen3" in name or "qwen_3" in name) and "8b" in name
    elif dep_id == "mmproj_qwen3vl_4b":
        return "mmproj" in name and ("qwen3" in name or "qwen_3" in name) and "4b" in name
    elif dep_id == "bonsai2_2b_model":
        return name == "ternary-bonsai-2-2b-q2_0.gguf"
    elif dep_id == "bonsai2_2b_mmproj":
        return name == "ternary-bonsai-2-2b-mmproj-q8_0.gguf"
    elif dep_id == "bonsai2_4b_model":
        return name == "ternary-bonsai-2-4b-q2_0.gguf"
    elif dep_id == "bonsai2_4b_mmproj":
        return name == "ternary-bonsai-2-4b-mmproj-q8_0.gguf"
    elif dep_id == "bonsai2_9b_model":
        return name == "ternary-bonsai-2-9b-q2_0.gguf"
    elif dep_id == "bonsai2_9b_mmproj":
        return name == "ternary-bonsai-2-9b-mmproj-q8_0.gguf"
    elif dep_id == "qwen35_4b_model":
        return name == "qwen3.5-4b-q4_k_m.gguf" or name == "qwen35-4b-q4_k_m.gguf"
    elif dep_id == "qwen35_4b_mmproj":
        return "mmproj" in name and "4b" in name and ("qwen3.5" in name or "qwen35" in name)
    elif dep_id == "qwen35_9b_mmproj":
        return "mmproj" in name and "9b" in name and ("qwen3.5" in name or "qwen35" in name)
    elif dep_id == "gemma4_e2b_model":
        return name == "gemma-4-e2b-it-q4_k_m.gguf"
    elif dep_id == "gemma4_e2b_mmproj":
        return "mmproj" in name and "e2b" in name
    elif dep_id == "gemma4_e4b_model":
        return name == "gemma-4-e4b-it-q4_k_m.gguf"
    elif dep_id == "gemma4_e4b_mmproj":
        return "mmproj" in name and "e4b" in name
    elif dep_id == "lfm3vl_2b_model":
        return name == "lfm3-vl-2b-q4_k_m.gguf"
    elif dep_id == "lfm3vl_2b_mmproj":
        return name == "mmproj-lfm3-vl-2b-q8_0.gguf"
    elif dep_id == "qwen35_9b":
        return ("qwen3.5" in name or "qwen3_5" in name or "qwen35" in name) and "9b" in name \
            and "vl" not in name and "mmproj" not in name
    elif dep_id == "moss_tokenizer":
        return "tokenizer" in name
    elif dep_id == "vae_wan21":
        return "wan" in name and "vae" in name
    elif dep_id == "vae_flux":
        return (("flux" in name and "2" not in name and ("vae" in name or "ae" in name)) or name == "ae.safetensors")
    elif dep_id == "vae_flux2":
        return ("flux2" in name or "flux_2" in name) and ("vae" in name or "ae" in name)
    elif dep_id == "vae_qwen":
        return "qwen" in name and ("vae" in name or "ae" in name) and "2.1" not in name and "21" not in name
    elif dep_id == "vae_qwen_21":
        return "qwen" in name and ("2.1" in name or "21" in name) and ("vae" in name or "ae" in name)
    elif dep_id == "vae_sd3":
        return "sd3" in name or name == "diffusion_pytorch_model.safetensors"
    elif dep_id == "clip_l":
        return "clip_l" in name or "clip-l" in name
    elif dep_id == "clip_g":
        return "clip_g" in name or "clip-g" in name
    elif dep_id == "t5xxl":
        return "t5xxl" in name or "t5_xxl" in name or "t5-xxl" in name
    return True


def resolve_dep_gguf(dep_id: str, files: list, priority=None):
    priority = priority or DEP_QUANT_PRIORITY

    ggufs = [f for f in files if f.lower().endswith(".gguf") and "/" not in f and _is_valid_dep(dep_id, Path(f))]
    plain = {}
    for f in ggufs:
        q = _quant_of(f)
        if q and not ("-UD-" in f or "-IQ" in f):
            plain.setdefault(q, f)
    for q in priority:
        if q in plain:
            return plain[q]
    if plain:
        return next(iter(plain.values()))
    return ggufs[0] if ggufs else None


# --------------------------------------------------------------------------- #
#  Manifeste
# --------------------------------------------------------------------------- #
def load_manifest():
    if MANIFEST_PATH.exists():
        try:
            mf = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
            cleaned = False
            for dep_id in list(mf.keys()):
                info = mf[dep_id]
                if isinstance(info, dict) and "path" in info:
                    p = Path(info["path"])
                    if not p.exists() or not _is_valid_dep(dep_id, p):
                        del mf[dep_id]
                        cleaned = True
            if cleaned:
                save_manifest(mf)
            return mf
        except Exception:
            return {}
    return {}


def save_manifest(data: dict):
    MANIFEST_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                             encoding="utf-8")


# --------------------------------------------------------------------------- #
#  Prompt Ideogram : JSON canonique enrichi
# --------------------------------------------------------------------------- #
def build_ideogram_prompt(text, negative, width, height):
    """
    Transforme une description simple en JSON CANONIQUE pour Ideogram 4.
    Le filtre de securite (cuit dans les poids) se declenche sur les prompts
    trop simples -> on construit une description riche et on-distribution.
    """
    import json as _json
    desc = (text or "").strip() or "a cheerful everyday scene"
    w, h = int(width), int(height)
    obj = {
        "high_level_description": (
            f"A clean, wholesome, family-friendly {w} x {h} illustration of {desc}. "
            f"Cheerful, positive and safe everyday scene, suitable for all audiences."
        ),
        "style_description": {
            "aesthetics": "highly detailed, professional, sharp focus, visually striking, "
                          "balanced composition, premium quality, clean and wholesome editorial",
            "lighting": "well-balanced natural lighting, soft shadows, cinematic illumination",
            "photo": "ultra high resolution, fine detail, crisp, clean, professional look",
            "medium": "digital art, highly detailed polished illustration, professional concept art",
            "color_palette": ["#F4EFE7", "#111111", "#3A6EA5", "#D8B56D", "#B73A3A", "#5BA37A"],
        },
        "compositional_deconstruction": {
            "canvas": f"A {w} x {h} canvas, normal upright orientation. Do not rotate.",
            "background": "a clean, pleasant background that complements the subject",
            "layout": "Center the main subject. Balanced, harmonious composition.",
            "elements": [
                {
                    "type": "obj",
                    "bbox": [10, 10, 90, 90],
                    "desc": f"{desc}. Full detail, centered, clearly visible, friendly.",
                }
            ],
        },
    }
    return _json.dumps(obj, ensure_ascii=False)


# --------------------------------------------------------------------------- #
#  Capacites d'entree image (edition / img2img)
# --------------------------------------------------------------------------- #
# Deux facons pour sd-cli de recevoir une image :
#   "ref"  -> -r / --ref-image  : reference (REPETABLE : une fois par image).
#             C'est le mode des modeles d'edition semantique.
#   "init" -> -i / --init-img   : image de depart unique + --strength (img2img).
# Le nombre maximum d'images est une limite d'interface : le moteur n'en pose
# aucune, mais chaque reference ajoute des tokens (donc VRAM + temps).


def input_modes(model_id: str) -> list:
    """Modes d'entree image acceptes par un modele ("ref" et/ou "init")."""
    m = MODELS[model_id]
    modes = m.get("input_modes")
    if modes:
        return list(modes)
    # Retro-compatibilite : les architectures UNet utilisent -i, les DiT -r.
    if m.get("supports_img2img") or m.get("supports_ref_images"):
        return ["init"] if m.get("arch") in ("sd3", "sd") else ["ref"]
    return []


def max_ref_images(model_id: str, input_mode: str | None = None) -> int:
    """Nombre maximal d'images acceptees par le modele (canvas + references)."""
    m = MODELS[model_id]
    modes = input_modes(model_id)
    mode = input_mode or (modes[0] if modes else None)
    if mode == "init":
        return 1
    return int(m.get("max_ref_images", 1))


def supports_outpainting(model_id: str) -> bool:
    """Indique si le modele supporte l'outpainting (extension du cadre du canvas)."""
    m = MODELS.get(model_id, {})
    return bool(m.get("supports_outpainting", False))


def supports_inpainting(model_id: str) -> bool:
    """Indique si le modele supporte le mode Inpainting au pinceau (retouche locale)."""
    m = MODELS.get(model_id, {})
    return bool(m.get("supports_inpainting", True) and m.get("supports_ref_images", False))


def _describe_bbox_region(bbox: dict | None) -> tuple[str, list[int] | None]:
    """
    A partir d'une boite englobante en pourcentages {x1, y1, x2, y2} (0..100),
    retourne (description_spatiale_en, [ymin, xmin, ymax, xmax] normalise 0..1000).
    """
    if not isinstance(bbox, dict):
        return "in the painted target region", None
    try:
        x1 = max(0.0, min(100.0, float(bbox.get("x1", 0))))
        y1 = max(0.0, min(100.0, float(bbox.get("y1", 0))))
        x2 = max(x1, min(100.0, float(bbox.get("x2", 100))))
        y2 = max(y1, min(100.0, float(bbox.get("y2", 100))))
    except (TypeError, ValueError):
        return "in the painted target region", None

    cx = (x1 + x2) / 2.0
    cy = (y1 + y2) / 2.0
    v_part = "upper" if cy < 36 else ("lower" if cy > 64 else "middle")
    h_part = "left" if cx < 36 else ("right" if cx > 64 else "center")
    if v_part == "middle" and h_part == "center":
        loc = "in the central area"
    elif v_part == "middle":
        loc = f"on the {h_part} side"
    elif h_part == "center":
        loc = f"in the {v_part} area"
    else:
        loc = f"in the {v_part}-{h_part} area"

    norm_box = [
        int(round(y1 * 10)),
        int(round(x1 * 10)),
        int(round(y2 * 10)),
        int(round(x2 * 10)),
    ]
    return loc, norm_box


def build_inpaint_prompt(model_id: str, user_prompt: str = "",
                         bbox: dict | None = None) -> str:
    """
    Construit ou enrichit l'instruction d'edition pour un Inpainting localise au pinceau,
    en ciblant precisement la zone peinte (description spatiale + boite normalisee)
    et en preservant le reste de l'image intact.
    """
    ref_label = _ref_token(model_id, 1)
    loc, norm_box = _describe_bbox_region(bbox)
    box_str = f" (region {norm_box})" if norm_box else ""
    clean = (user_prompt or "").strip()
    action = clean if clean else "seamlessly remove the unwanted element and reconstruct the background naturally"
    return (
        f"Inpaint and modify ONLY the target area {loc}{box_str} of {ref_label}: {action}. "
        f"Keep everything outside this target area in {ref_label} strictly unchanged and identical, "
        "with seamless blending, matching lighting, perspective, and textures."
    )


def build_outpaint_prompt(model_id: str, user_prompt: str = "",
                          directions: list[str] | None = None) -> str:
    """
    Construit ou enrichit l'instruction d'edition pour un outpainting (extension hors-cadre)
    en respectant la syntaxe d'adressage du modele (<image1>, <image_1> ou langage naturel).
    """
    m = MODELS.get(model_id, {})
    syntax = m.get("ref_tag_syntax")
    ref_label = syntax.replace("{n}", "1") if syntax else "image 1"
    dir_names = {
        "top": "top",
        "bottom": "bottom",
        "left": "left",
        "right": "right",
    }
    valid_dirs = [dir_names[d] for d in (directions or []) if d in dir_names]
    if valid_dirs and len(valid_dirs) < 4:
        where = "on the " + ", ".join(valid_dirs) + " border" + ("s" if len(valid_dirs) > 1 else "")
    else:
        where = "around the borders"

    base = (
        f"Outpaint and seamlessly extend {ref_label} {where} to fill the entire frame, "
        f"keep the original central content of {ref_label} intact and unchanged, "
        "match the exact lighting, colors, perspective, texture and style."
    )
    clean = (user_prompt or "").strip()
    if not clean:
        return base
    if "outpaint" in clean.lower():
        return clean
    return f"{base} {clean}"


def _ref_token(model_id: str, index: int = 1) -> str:
    """Retourne le jeton d'image adapte au modele (<image1>, <image_1> ou 'image 1')."""
    m = MODELS.get(model_id, {})
    syntax = m.get("ref_tag_syntax")
    if syntax:
        return syntax.replace("{n}", str(index))
    return f"image {index}"


def outpaint_prompt_presets(model_id: str) -> list[dict]:
    """
    Pre-prompts d'outpainting adaptes a chaque modele compatible (syntaxe et style).
    """
    if not supports_outpainting(model_id):
        return []
    img1 = _ref_token(model_id, 1)
    m = MODELS.get(model_id, {})
    is_distilled_dit = m.get("arch") in ("flux2", "flux3")
    if is_distilled_dit:
        return [
            {
                "id": "outpaint_natural",
                "label": "🌄 Prolonger la scène naturellement",
                "prompt": (
                    f"Outpaint and seamlessly extend {img1} to fill the entire frame, "
                    f"keeping the original content of {img1} intact and naturally continuing "
                    "the surrounding environment, lighting, perspective, and textures"
                ),
            },
            {
                "id": "outpaint_landscape",
                "label": "🏞️ Étendre le paysage & le ciel",
                "prompt": (
                    f"Wide panoramic view outpainting {img1} across the entire frame, "
                    f"keep the original {img1} unchanged and seamlessly extend the horizon, "
                    "sky, clouds, ground details, and natural daylight"
                ),
            },
            {
                "id": "outpaint_fullbody",
                "label": "🧍 Dézoomer / Compléter le personnage",
                "prompt": (
                    f"Wider framing of the person in {img1} filling the entire frame, "
                    f"preserve the exact face, hair, pose, and outfit from {img1} while "
                    "naturally extending the rest of the body and surrounding background"
                ),
            },
            {
                "id": "outpaint_studio",
                "label": "📸 Prolonger un fond studio propre",
                "prompt": (
                    f"Outpaint {img1} with a clean, seamless studio backdrop filling the "
                    f"entire frame, keep the subject in {img1} unchanged with soft natural "
                    "contact shadows and studio lighting"
                ),
            },
            {
                "id": "outpaint_interior",
                "label": "🛋️ Étendre un intérieur / architecture",
                "prompt": (
                    f"Wide architectural shot outpainting {img1} to fill the frame, "
                    f"keep the original room in {img1} intact and coherently extend the walls, "
                    "floor, ceiling, furniture, and indoor lighting perspective"
                ),
            },
        ]
    return [
        {
            "id": "outpaint_natural",
            "label": "🌄 Prolonger la scène naturellement",
            "prompt": (
                f"Outpaint and seamlessly extend {img1} into the surrounding borders to fill "
                f"the entire frame. Keep the original content of {img1} completely unchanged, "
                "and match the exact lighting, colors, perspective, and style."
            ),
        },
        {
            "id": "outpaint_landscape",
            "label": "🏞️ Étendre le paysage & le ciel",
            "prompt": (
                f"Outpaint {img1} to create a wider landscape view. Keep the original {img1} "
                "intact and seamlessly extend the sky, horizon, terrain, foliage, and natural "
                "atmospheric lighting into the borders."
            ),
        },
        {
            "id": "outpaint_fullbody",
            "label": "🧍 Dézoomer / Compléter le personnage",
            "prompt": (
                f"Outpaint {img1} into a wider shot. Preserve the exact face, identity, pose, "
                f"and clothing of the character in {img1}, and naturally complete their body "
                "and the surrounding environment."
            ),
        },
        {
            "id": "outpaint_studio",
            "label": "📸 Prolonger un fond studio propre",
            "prompt": (
                f"Outpaint {img1} by extending a clean, uniform studio backdrop and floor "
                f"around the subject in {img1}, preserving the original subject and soft shadows."
            ),
        },
        {
            "id": "outpaint_interior",
            "label": "🛋️ Étendre un intérieur / architecture",
            "prompt": (
                f"Outpaint {img1} to reveal more of the room and architecture. Keep {img1} "
                "unchanged and coherently extend the walls, floor perspective, decor, and warm indoor lighting."
            ),
        },
    ]


def edit_prompt_presets(model_id: str) -> list[dict]:
    """
    Pre-prompts d'edition (1 image ou multi-references) adaptes a la syntaxe du modele.
    """
    m = MODELS.get(model_id, {})
    if not m.get("supports_ref_images"):
        return []
    img1 = _ref_token(model_id, 1)
    img2 = _ref_token(model_id, 2)
    presets = [
        {
            "id": "edit_bg",
            "category": "canvas",
            "label": "🌆 Changer l'arrière-plan (garder le sujet)",
            "prompt": (
                f"Keep the main subject, pose, and face in {img1} completely unchanged, "
                "replace the background with a scenic sunlit mountain landscape, matching the lighting and shadows"
            ),
        },
        {
            "id": "edit_relight",
            "category": "canvas",
            "label": "🌅 Relighting Golden Hour / Cinématique",
            "prompt": (
                f"Keep the subject, composition, and details of {img1} unchanged, relight the "
                "scene with warm golden hour sunlight, rim lighting, and cinematic soft shadows"
            ),
        },
        {
            "id": "edit_outfit",
            "category": "canvas",
            "label": "👕 Changer la tenue du personnage",
            "prompt": (
                f"Keep the person's face, hair, pose, and background in {img1} unchanged, "
                "dress them in a tailored dark leather jacket with natural fabric folds"
            ),
        },
        {
            "id": "edit_remove",
            "category": "canvas",
            "label": "🧹 Nettoyer / Supprimer un objet",
            "prompt": (
                f"Remove the unwanted background clutter in {img1} and reconstruct the background "
                f"seamlessly while keeping the main subject of {img1} completely intact"
            ),
        },
        {
            "id": "edit_text",
            "category": "canvas",
            "label": "🔤 Modifier un texte / une enseigne",
            "prompt": (
                f"In {img1}, replace the visible text on the sign with 'STUDIO LOCAL', "
                "preserving the exact font style, perspective, surface texture, and lighting"
            ),
        },
        {
            "id": "ref_tryon",
            "category": "multi",
            "label": "🧥 Transférer le vêtement de l'image 2 sur l'image 1",
            "prompt": (
                f"Keep the person, face, hair, pose, and background in {img1} unchanged, "
                f"put the clothing from {img2} on the person in {img1} with natural fit and lighting"
            ),
        },
        {
            "id": "ref_object",
            "category": "multi",
            "label": "📦 Placer l'objet de l'image 2 dans l'image 1",
            "prompt": (
                f"Place the object from {img2} naturally into the scene of {img1}, "
                f"matching the perspective, scale, shadows, and lighting of {img1}"
            ),
        },
        {
            "id": "ref_style",
            "category": "multi",
            "label": "🎨 Appliquer le style / l'ambiance de l'image 2",
            "prompt": (
                f"Keep the subject and composition of {img1}, transfer the color palette, "
                f"lighting mood, and artistic rendering style from {img2}"
            ),
        },
        {
            "id": "style_watercolor",
            "category": "style",
            "label": "🎨 Aquarelle",
            "prompt": (
                f"Keep the subject and composition of {img1} completely unchanged, redraw the "
                "entire image as a delicate watercolor painting with soft wet-on-wet washes and "
                "textured paper"
            ),
        },
        {
            "id": "style_oil",
            "category": "style",
            "label": "🖼️ Peinture à l'huile",
            "prompt": (
                f"Keep the subject and composition of {img1} unchanged, repaint the scene as an "
                "expressive oil painting with visible brushstrokes and warm chiaroscuro lighting"
            ),
        },
        {
            "id": "style_anime",
            "category": "style",
            "label": "🌸 Anime / illustration japonaise",
            "prompt": (
                f"Keep the subject and pose of {img1} unchanged, redraw the image in masterpiece "
                "anime style, clean linework, vibrant cel shading, Makoto Shinkai inspired background"
            ),
        },
        {
            "id": "style_sketch",
            "category": "style",
            "label": "✏️ Croquis encre & fusain",
            "prompt": (
                f"Keep the subject of {img1} unchanged, convert the image into a detailed pencil "
                "and charcoal sketch on textured paper with expressive cross-hatching"
            ),
        },
        {
            "id": "style_3d",
            "category": "style",
            "label": "🧸 3D / animation",
            "prompt": (
                f"Keep the subject and composition of {img1} unchanged, reimagine the scene as a "
                "stylized 3D animated film still with soft cinematic lighting and global illumination"
            ),
        },
        {
            "id": "style_noir",
            "category": "style",
            "label": "🎞️ Noir & blanc (film noir)",
            "prompt": (
                f"Keep the subject and composition of {img1} unchanged, convert the image to "
                "black and white film noir photography, hard contrast, venetian blind shadows, "
                "1940s atmosphere"
            ),
        },
        {
            "id": "style_pixel",
            "category": "style",
            "label": "👾 Pixel art 16 bits",
            "prompt": (
                f"Keep the subject and composition of {img1} unchanged, convert the image into "
                "16-bit pixel art with a limited color palette and crisp chunky pixels"
            ),
        },
        {
            "id": "style_ukiyoe",
            "category": "style",
            "label": "🖌️ Estampe japonaise ukiyo-e",
            "prompt": (
                f"Keep the subject and composition of {img1} unchanged, redraw the image as a "
                "traditional ukiyo-e woodblock print with bold outlines and flat areas of color"
            ),
        },
        {
            "id": "style_digitalpaint",
            "category": "style",
            "label": "🖌️ Peinture digitale",
            "prompt": (
                f"Keep the subject and composition of {img1} unchanged, repaint the image as a "
                "dynamic digital painting with bold brush strokes, dramatic lighting and rich "
                "saturated colors"
            ),
        },
        {
            "id": "style_concept",
            "category": "style",
            "label": "💡 Concept art / matte painting",
            "prompt": (
                f"Keep the subject and composition of {img1} unchanged, reimagine the scene as a "
                "cinematic matte painting with atmospheric depth, photobash realism and AAA game "
                "concept-art quality"
            ),
        },
        {
            "id": "style_synthwave",
            "category": "style",
            "label": "🌆 Synthwave / retrowave",
            "prompt": (
                f"Keep the subject and composition of {img1} unchanged, redraw the image in "
                "synthwave retrowave style, magenta and cyan neon glow, chrome accents, 80s "
                "outrun poster aesthetic"
            ),
        },
        {
            "id": "style_celshaded",
            "category": "style",
            "label": "🌀 Cel-shading / anime digital",
            "prompt": (
                f"Keep the subject and pose of {img1} unchanged, redraw the image in cel-shaded "
                "anime style, crisp ink outlines, flat vibrant colors with hard shadows, premium "
                "anime key visual"
            ),
        },
        {
            "id": "style_photobash",
            "category": "style",
            "label": "🖼️ Photobash",
            "prompt": (
                f"Keep the subject and composition of {img1} unchanged, restyle the image as a "
                "photobash illustration blending real photographic textures with digital painting"
            ),
        },
        {
            "id": "style_octane",
            "category": "style",
            "label": "💎 Rendu 3D (Octane)",
            "prompt": (
                f"Keep the subject and composition of {img1} unchanged, reimagine the scene as a "
                "photorealistic 3D render, octane renderer, subsurface scattering, cinematic "
                "studio lighting, product quality"
            ),
        },
        {
            "id": "style_glitch",
            "category": "style",
            "label": "🟣 Glitch art",
            "prompt": (
                f"Keep the subject and composition of {img1} unchanged, apply a glitch art "
                "treatment with pixel sorting, RGB channel shift, scan lines and chromatic "
                "aberration"
            ),
        },
        {
            "id": "style_isometric",
            "category": "style",
            "label": "🎲 Isométrique game art",
            "prompt": (
                f"Keep the subject of {img1} unchanged, re-render the scene as an isometric "
                "game art illustration, clean digital linework, vibrant stylized colors, crisp "
                "render"
            ),
        },
        {
            "id": "ref_bg_swap",
            "category": "multi",
            "label": "🖼️ Utiliser l'image 2 comme nouveau décor de l'image 1",
            "prompt": (
                f"Keep the foreground subject of {img1} unchanged, replace the background of "
                f"{img1} with the environment from {img2}, harmonize lighting and shadows"
            ),
        },
    ]
    for op in outpaint_prompt_presets(model_id):
        presets.append({
            "id": op["id"],
            "category": "outpaint",
            "label": op["label"],
            "prompt": op["prompt"],
        })
    return presets


def gen_prompt_presets(model_id: str) -> list[dict]:
    """
    Pre-prompts de generation text-to-image adaptes aux points forts de chaque modele.
    """
    m = MODELS.get(model_id, {})
    arch = m.get("arch", "")
    common = [
        {
            "id": "gen_portrait",
            "category": "general",
            "label": "📷 Portrait photoréaliste 85mm",
            "prompt": (
                "Close-up editorial portrait of a weathered explorer in soft natural window light, "
                "85mm f/1.4 lens, shallow depth of field, intricate skin texture, Kodachrome color grading"
            ),
        },
        {
            "id": "gen_landscape",
            "category": "general",
            "label": "🏔️ Paysage cinématique Golden Hour",
            "prompt": (
                "Breathtaking alpine valley at golden hour, dramatic volumetric sunbeams piercing "
                "through morning mist, crystal clear river reflection, ultra-detailed 8k nature photography"
            ),
        },
        {
            "id": "gen_cyberpunk",
            "category": "general",
            "label": "🌃 Scène Cyberpunk néon sous la pluie",
            "prompt": (
                "Cinematic street-level view of a futuristic Tokyo alley at night in the rain, "
                "vibrant neon holograms reflecting on wet asphalt, moody atmospheric fog, anamorphic lens flare"
            ),
        },
        {
            "id": "gen_product",
            "category": "general",
            "label": "⌚ Photo produit commerciale Studio",
            "prompt": (
                "Luxury mechanical chronograph watch resting on dark volcanic stone with water droplets, "
                "dramatic studio rim lighting, macro photography, razor-sharp reflections"
            ),
        },
        {
            "id": "gen_anime",
            "category": "general",
            "label": "🎨 Illustration Anime / Concept Art",
            "prompt": (
                "Masterpiece anime illustration of a cozy steampunk rooftop greenhouse overlooking a "
                "floating city at sunset, lush glowing plants, warm painterly lighting, Makoto Shinkai inspired"
            ),
        },
    ]
    if arch in ("ernie", "ideogram", "qwen_image", "moss_image", "flux3"):
        common.insert(0, {
            "id": "gen_typography",
            "category": "general",
            "label": "🔤 Affiche / Texte lisible intégré",
            "prompt": (
                "Vintage travel poster of an art-deco train station at twilight with bold, crisp "
                "typography at the top reading 'LOCAL IMAGE STUDIO', warm brass and teal palette, "
                "clean vector-inspired illustration"
            ),
        })
    elif arch == "longcat":
        # LongCat rend le texte caractère par caractère : le mettre entre guillemets.
        common.insert(0, {
            "id": "gen_typography",
            "category": "general",
            "label": "🔤 Texte exact entre guillemets (spécialité LongCat)",
            "prompt": (
                "Minimalist movie poster of a lighthouse in a storm at dusk, the title "
                "\"LOCAL IMAGE STUDIO\" written in large elegant serif letters across the sky, "
                "cinematic volumetric light, photorealistic, 8k"
            ),
        })
    elif arch == "flux_kontext":
        common.insert(0, {
            "id": "gen_kontext_relight",
            "category": "general",
            "label": "💡 Changer l'ambiance lumineuse (Kontext)",
            "prompt": (
                "Keep the subject, composition and details identical, relight the scene with "
                "warm golden-hour sunlight coming from the left, soft long shadows"
            ),
        })


    elif arch in ("sd3",):
        common.append({
            "id": "gen_img2img_restyle",
            "category": "general",
            "label": "🖌️ Transformation peinture à l'huile (img2img)",
            "prompt": (
                "Expressive impasto oil painting on canvas, rich visible brushstrokes, "
                "warm chiaroscuro lighting, museum fine art quality"
            ),
        })

    # --- 🎭 Styles & rendus : bibliothèque partagée, langage DiT/FLUX/Qwen/SD3 ---
    styles = [
        {
            "id": "gen_style_cinematic",
            "category": "style",
            "label": "🎬 Cinéma anamorphique (teal & orange)",
            "prompt": (
                "Cinematic film still, a lone figure walking through a rain-soaked neon-lit "
                "street at night, anamorphic lens flare, teal and orange color grade, subtle "
                "35mm film grain, shallow depth of field, dramatic volumetric light"
            ),
        },
        {
            "id": "gen_style_portra",
            "category": "style",
            "label": "📷 Photo argentique Portra 400",
            "prompt": (
                "Analog 35mm film photograph of a quiet café terrace in the morning, "
                "Kodak Portra 400, soft warm tones, fine film grain, natural available light, "
                "candid documentary feel, 85mm lens"
            ),
        },
        {
            "id": "gen_style_oil",
            "category": "style",
            "label": "🖼️ Peinture à l'huile impressionniste",
            "prompt": (
                "Impressionist oil painting of a sunlit lavender field, vigorous visible brushstrokes, "
                "impasto texture, warm painterly light, rich color harmony, museum masterpiece"
            ),
        },
        {
            "id": "gen_style_watercolor",
            "category": "style",
            "label": "🎨 Aquarelle délicate",
            "prompt": (
                "Delicate watercolor illustration of a fox curled up in autumn leaves, loose "
                "wet-on-wet washes, soft paper texture, gentle pigment bleeds, muted earthy "
                "palette, storybook charm"
            ),
        },
        {
            "id": "gen_style_ink",
            "category": "style",
            "label": "✏️ Encre & fusain (croquis)",
            "prompt": (
                "Detailed ink and charcoal sketch of an old lighthouse in a storm, expressive "
                "cross-hatching, dramatic chiaroscuro, smudged charcoal shading, textured "
                "sketchbook paper"
            ),
        },
        {
            "id": "gen_style_ukiyoe",
            "category": "style",
            "label": "🌸 Estampe japonaise ukiyo-e",
            "prompt": (
                "Traditional Japanese ukiyo-e woodblock print of a great wave beneath a full moon, "
                "bold outlines, flat areas of color, carved woodblock texture, Edo period style"
            ),
        },
        {
            "id": "gen_style_3d",
            "category": "style",
            "label": "🧸 3D animation (rendu Blender)",
            "prompt": (
                "3D animated film still of a small robot tending a rooftop garden at sunset, soft "
                "subsurface scattering, cinematic global illumination, stylized animated character "
                "design, Blender render"
            ),
        },
        {
            "id": "gen_style_pixel",
            "category": "style",
            "label": "👾 Pixel art 16 bits",
            "prompt": (
                "Pixel art illustration of a cozy spaceship interior with a sleeping cat, 16-bit "
                "style, limited color palette, crisp chunky pixels, no anti-aliasing, retro game "
                "aesthetic"
            ),
        },
        {
            "id": "gen_style_lowpoly",
            "category": "style",
            "label": "🔺 Low-poly géométrique",
            "prompt": (
                "Low-poly geometric illustration of a snowy mountain lake at sunrise, faceted "
                "triangular shapes, flat vibrant colors, minimalist composition, crisp clean render"
            ),
        },
        {
            "id": "gen_style_noir",
            "category": "style",
            "label": "🎞️ Film noir (noir & blanc)",
            "prompt": (
                "Black and white film noir photograph, a detective in a fedora under a street lamp "
                "in the rain, hard venetian blind shadows, deep contrast, silver gelatin print, "
                "1940s atmosphere"
            ),
        },
        {
            "id": "gen_style_flat",
            "category": "style",
            "label": "⬜ Flat design / vectoriel",
            "prompt": (
                "Minimalist flat vector illustration of a person cycling through a modern city, "
                "bold geometric shapes, limited teal-coral-cream palette, subtle print grain, "
                "editorial magazine cover"
            ),
        },
        {
            "id": "gen_style_artnouveau",
            "category": "style",
            "label": "🎭 Art Nouveau (Mucha)",
            "prompt": (
                "Art Nouveau lithograph poster of a woman with flowing floral hair, ornate organic "
                "border, muted gold and sage palette, Alphonse Mucha style, intricate decorative "
                "detail"
            ),
        },
        {
            "id": "gen_style_surreal",
            "category": "style",
            "label": "🌀 Surréalisme (Dalí)",
            "prompt": (
                "Surrealist oil painting of a desert with melting clocks draped over abandoned "
                "objects, dreamlike vast landscape, hyperreal detail, Salvador Dalí style, "
                "meticulous brushwork"
            ),
        },
        {
            "id": "gen_style_storybook",
            "category": "style",
            "label": "📖 Livre pour enfants",
            "prompt": (
                "Children's storybook illustration of a child sailing a tiny boat on a moonlit "
                "sea, soft crayon and watercolor textures, whimsical clouds, cozy bedtime mood, "
                "gentle pastel palette"
            ),
        },
        # --- Styles digitaux (peinture digitale, concept art, 3D, retro digital) ---
        {
            "id": "gen_style_digitalpaint",
            "category": "style",
            "label": "🖌️ Peinture digitale (speedpaint)",
            "prompt": (
                "Dynamic digital painting of a windswept forest valley, bold painterly brushwork "
                "with visible strokes, dramatic rim light, rich saturated colors, concept-art "
                "quality, professional speedpaint"
            ),
        },
        {
            "id": "gen_style_concept",
            "category": "style",
            "label": "💡 Concept art / Matte painting",
            "prompt": (
                "Breathtaking sci-fi matte painting of a crashed spaceship in a misty redwood "
                "forest, cinematic composition, photobash realism, atmospheric depth, AAA game "
                "cinematic, 8k"
            ),
        },
        {
            "id": "gen_style_photobash",
            "category": "style",
            "label": "🖼️ Photobash illustration",
            "prompt": (
                "Photobash illustration of a rainy cyberpunk harbor at night, real photographic "
                "textures blended with digital painting, moody reflections on wet concrete, "
                "cinematic framing, highly detailed"
            ),
        },
        {
            "id": "gen_style_synthwave",
            "category": "style",
            "label": "🌆 Synthwave / Retrowave",
            "prompt": (
                "Synthwave retrowave digital artwork, a chrome sports car driving toward a neon "
                "sun on a glowing grid horizon, magenta and cyan glow, subtle VHS grain, 80s "
                "outrun poster style"
            ),
        },
        {
            "id": "gen_style_isometric",
            "category": "style",
            "label": "🎲 Isométrique game art",
            "prompt": (
                "Isometric game art illustration of a cozy floating island village, clean digital "
                "linework, vibrant gradient sky, stylized cute assets, crisp render, indie game "
                "aesthetic"
            ),
        },
        {
            "id": "gen_style_celshaded",
            "category": "style",
            "label": "🌀 Cel-shading / anime digital",
            "prompt": (
                "Cel-shaded anime digital illustration of a samurai overlooking a neon-lit city "
                "rooftop, crisp ink outlines, flat vibrant colors with hard shadows, high contrast, "
                "premium anime key visual"
            ),
        },
        {
            "id": "gen_style_octane",
            "category": "style",
            "label": "💎 Rendu 3D photoréaliste (Octane)",
            "prompt": (
                "Photorealistic 3D render of a ceramic coffee mug on a marble table, octane "
                "renderer, subsurface scattering, soft studio HDRI lighting, product photography "
                "quality, 8k"
            ),
        },
        {
            "id": "gen_style_vaporwave",
            "category": "style",
            "label": "🌸 Vaporwave",
            "prompt": (
                "Vaporwave aesthetic digital collage, roman bust with glitch stripes, palm trees "
                "and sunset gradient grid, retro computer glitches, pastel pink and purple, dreamy "
                "surreal mood"
            ),
        },
        {
            "id": "gen_style_glitch",
            "category": "style",
            "label": "🟣 Glitch art / datamosh",
            "prompt": (
                "Glitch art portrait of an android face fragmenting into pixel sorting and "
                "datamoshing artifacts, RGB channel shift, scan lines, chromatic aberration, dark "
                "background, cybernetic glitch aesthetic"
            ),
        },
        {
            "id": "gen_style_generative",
            "category": "style",
            "label": "🌊 Art génératif algorithmique",
            "prompt": (
                "Algorithmic generative art, flowing recursive flow field of glowing particles, "
                "deep dark background, mathematically balanced composition, elegant generative "
                "studio poster"
            ),
        },
    ]
    common.extend(styles)
    return common


def clamp_ref_max_pixels(value) -> int | None:
    """Normalise le budget pixels des references (None = auto, gere par le moteur)."""
    if value in (None, "", 0, "0", "auto", "Auto"):
        return None
    try:
        px = int(float(value))
    except (TypeError, ValueError):
        return None
    if px <= 0:
        return None
    return max(65536, min(4 * 1024 * 1024, px))  # 256x256 .. 4 MP


def check_images_input(model_id: str, images, input_mode: str | None = None):
    """
    Valide le couple (modele, images).
    Retourne (images_normalisees, input_mode, message_erreur) — erreur None si OK.
    La presence du mmproj (encodeur visuel) est verifiee cote moteur.
    """
    m = MODELS[model_id]
    modes = input_modes(model_id)
    imgs = [str(p).strip() for p in (images or []) if str(p).strip()]
    # ordre preserve, doublons retire
    seen = set()
    imgs = [p for p in imgs if not (p in seen or seen.add(p))]

    if not imgs:
        return [], None, None
    if not modes:
        return imgs, None, (
            f"{m['name']} n'accepte pas d'image en entrée.\n"
            "Pour de l'édition multi-images, choisis Qwen-Image 2.1 (ou 2.1 Turbo) ou "
            "FLUX.2 / FLUX.3 Klein dans le Studio d'édition ; pour de l'img2img avec force de "
            "dénouage, choisis Stable Diffusion 3.5."
        )
    mode = input_mode or modes[0]
    if mode not in modes:
        return imgs, mode, (
            f"{m['name']} n'accepte pas le mode d'entrée « {mode} » "
            f"(modes disponibles : {', '.join(modes)})."
        )
    limit = max_ref_images(model_id, mode)
    if len(imgs) > limit:
        label = "image de départ (img2img)" if mode == "init" else "référence(s)"
        return imgs, mode, (
            f"{m['name']} accepte au maximum {limit} {label} — "
            f"{len(imgs)} image(s) fournie(s). Retirez des images ou changez de modèle."
        )
    return imgs, mode, None


# --------------------------------------------------------------------------- #
#  Construction de la commande sd-cli
# --------------------------------------------------------------------------- #
def _find_dep_on_disk(dep_id: str) -> Path | None:
    """Recherche sur le disque un fichier correspondant precisement a dep_id."""
    if dep_id not in DEPS:
        return None
    dep = DEPS[dep_id]
    if dep.get("type") == "exact":
        dest = dep.get("dest")
        if dest and dest.exists() and _is_valid_dep(dep_id, dest):
            return dest

    search_dirs = []
    if dep.get("dest_dir"):
        search_dirs.append(dep["dest_dir"])
    if dep.get("dest") and dep["dest"].parent not in search_dirs:
        search_dirs.append(dep["dest"].parent)
    if "llm" in dep_id or "qwen" in dep_id or "ministral" in dep_id:
        if LLM_DIR not in search_dirs:
            search_dirs.append(LLM_DIR)
        if TEXTENC_DIR not in search_dirs:
            search_dirs.append(TEXTENC_DIR)
    elif "vae" in dep_id:
        if VAE_DIR not in search_dirs:
            search_dirs.append(VAE_DIR)
    elif "clip" in dep_id or "t5" in dep_id:
        if TEXTENC_DIR not in search_dirs:
            search_dirs.append(TEXTENC_DIR)

    candidates = []
    for d in search_dirs:
        if not d or not d.exists():
            continue
        for f in d.iterdir():
            if f.is_file() and _is_valid_dep(dep_id, f):
                candidates.append(f)

    if not candidates:
        return None

    plain = {}
    for f in candidates:
        q = _quant_of(f.name)
        if q and not ("-UD-" in f.name or "-IQ" in f.name):
            plain.setdefault(q, f)
    for q in DEP_QUANT_PRIORITY:
        if q in plain:
            return plain[q]
    if plain:
        return next(iter(plain.values()))
    return candidates[0]


def _dep_path(manifest, dep_id):
    info = manifest.get(dep_id) or {}
    path = info.get("path")
    if path and Path(path).exists() and _is_valid_dep(dep_id, Path(path)):
        return str(path)
    found = _find_dep_on_disk(dep_id)
    if found:
        return str(found)
    return None


def _diffusion_path(model_id, quant):
    m = MODELS[model_id]
    return str(DIFFUSION_DIR / m["file_for_quant"][quant])


def build_command(model_id, quant, prompt, negative, width, height, steps,
                  cfg, seed, batch, out_template, sd_cli, manifest,
                  source_image=None, lora_dir=None, strength=None,
                  ref_images=None, input_mode=None, ref_max_pixels=None,
                  mask_image=None, sampler=None, scheduler=None,
                  vae_tiling=False, slg_scale=None, upscale_model=None,
                  adetailer_model=None, taesd_path=None, sage_attn=False,
                  preview_method=None, preview_path=None, preview_interval=None,
                  tae_preview_only=False,
                  pulid_weights=None, pulid_id_embedding=None, pulid_id_weight=None):
    m = MODELS[model_id]
    arch = m["arch"]
    args = [sd_cli]

    # --- Entrees image : references (edition) ou image de depart (img2img) ---
    images = [str(p) for p in (ref_images or []) if p]
    if not images and source_image:
        images = [str(source_image)]
    if input_mode is None:
        input_mode = "init" if arch in ("sd3", "sd") else "ref"
    has_refs = bool(images) and input_mode == "ref"
    has_init = bool(images) and input_mode == "init"

    # Modele de diffusion
    diff_file = _diffusion_path(model_id, quant)
    args += ["--diffusion-model", diff_file]

    # Modele uncond (Ideogram)
    if arch == "ideogram":
        uncond = m.get("uncond_file_for_quant", {}).get(quant)
        if uncond:
            args += ["--uncond-diffusion-model", str(DIFFUSION_DIR / uncond)]

    # VAE : SD3 et Chroma1-Radiance n'utilisent pas --vae externe
    if m.get("needs_vae", True):
        if arch == "sd3":
            vae_key = "vae_sd3"
        elif arch in ("ernie", "ideogram", "flux2", "flux3", "fibo2", "moss_image"):
            vae_key = "vae_flux2"
        elif arch == "krea2":
            vae_key = "vae_wan21"
        elif arch == "qwen_image":
            vae_key = m.get("vae_dep", "vae_qwen")
        else:
            vae_key = "vae_flux"
        vpath = _dep_path(manifest, vae_key)
        if vpath:
            args += ["--vae", str(vpath)]

    # Encodeurs de texte
    if arch in ("flux", "flux_kontext"):
        cl = _dep_path(manifest, "clip_l")
        t5 = _dep_path(manifest, "t5xxl")
        if cl:
            args += ["--clip_l", str(cl)]
        if t5:
            args += ["--t5xxl", str(t5)]
    elif arch in ("chroma", "chroma_radiance"):
        t5 = _dep_path(manifest, "t5xxl")
        if t5:
            args += ["--t5xxl", str(t5)]
    elif arch == "longcat":
        llm = _dep_path(manifest, m.get("llm_dep", "qwen25vl_7b"))
        if llm:
            args += ["--llm", str(llm)]
    elif arch == "sd3":
        cl = _dep_path(manifest, "clip_l")
        cg = _dep_path(manifest, "clip_g")
        t5 = _dep_path(manifest, "t5xxl")
        if cl:
            args += ["--clip_l", str(cl)]
        if cg:
            args += ["--clip_g", str(cg)]
        if t5:
            args += ["--t5xxl", str(t5)]
    elif arch == "flux2":
        llm = _dep_path(manifest, "qwen3_4b" if model_id == "flux2-klein-4b" else "qwen3_8b")
        if llm:
            args += ["--llm", str(llm)]
    elif arch == "flux3":
        # FLUX.3 Klein : Qwen3-VL 4B (GGUF) comme encodeur de texte, VAE FLUX.2.
        # Les references partent au DiT (preset flux2, pass_to_vlm=false) -> pas de mmproj.
        llm = _dep_path(manifest, m.get("llm_dep", "qwen3vl_4b"))
        if llm:
            args += ["--llm", str(llm)]
    elif arch == "fibo2":
        # Fibo 2.0 : Qwen3-VL-4B (GGUF) comme encodeur ; le mmproj (encodeur visuel)
        # fait entrer les images de reference dans le VLM (docs/fibo2.md).
        llm = _dep_path(manifest, m.get("llm_dep", "qwen3vl_4b"))
        if llm:
            args += ["--llm", str(llm)]
        mmproj = _dep_path(manifest, m.get("mmproj_dep", "mmproj_qwen3vl_4b"))
        if mmproj:
            args += ["--llm_vision", str(mmproj)]
    elif arch == "moss_image":
        # MOSS-Image : encodeur Qwen3.5-9B (GGUF) + tokenizer.json externe (Qwen3.5 a son
        # propre vocabulaire, distinct de celui embarque dans sd-cli).
        llm = _dep_path(manifest, m.get("llm_dep", "qwen35_9b"))
        if llm:
            args += ["--llm", str(llm)]
        tok = _dep_path(manifest, m.get("tokenizer_dep", "moss_tokenizer"))
        if tok:
            args += ["--tokenizer", str(tok)]
    elif arch == "krea2":
        # Krea 2 : encodeur Qwen3-VL-4B (texte seul pour Turbo), VAE Wan 2.1.
        llm = _dep_path(manifest, m.get("llm_dep", "qwen3vl_4b"))
        if llm:
            args += ["--llm", str(llm)]
    elif arch == "zimage":
        llm = _dep_path(manifest, "qwen3_4b")
        if llm:
            args += ["--llm", str(llm)]
    elif arch == "ernie":
        llm = _dep_path(manifest, "ministral_3b")
        if llm:
            args += ["--llm", str(llm)]
    elif arch == "ideogram":
        llm = _dep_path(manifest, "qwen3vl_8b")
        if llm:
            args += ["--llm", str(llm)]
    elif arch == "iris":
        llm = _dep_path(manifest, "qwen3vl_4b")
        if llm:
            args += ["--llm", str(llm)]
    elif arch == "qwen_image":
        llm_key = m.get("llm_dep", "qwen25vl_7b")
        llm = _dep_path(manifest, llm_key)
        if llm:
            args += ["--llm", str(llm)]
        # Certains modèles ne chargent le mmproj que pour l'édition avec références
        # (mode "ref") : c'est lui qui fait entrer l'image dans l'encodeur visuel.
        mmproj_key = m.get("mmproj_dep")
        need_mmproj = has_refs or not m.get("mmproj_for_img2img_only", False)
        if mmproj_key and need_mmproj:
            mmproj = _dep_path(manifest, mmproj_key)
            if mmproj:
                args += ["--llm_vision", str(mmproj)]

    # Prompt
    if arch == "ideogram":
        args += ["-p", build_ideogram_prompt(prompt, negative, width, height)]
    else:
        args += ["-p", prompt or " "]
        if negative and m.get("supports_neg"):
            args += ["-n", negative]

    # Images fournies au modele.
    #  - "ref"  : -r repete une fois par image (edition semantique, multi-refs)
    #  - "init" : -i unique + --strength (img2img classique)
    if images:
        if input_mode == "init":
            args += ["-i", images[0]]
            if strength is not None:
                args += ["--strength", f"{strength}"]
        else:
            for ref in images:
                args += ["-r", ref]
            # Budget pixels des references (levier VRAM) ; -1 = auto selon le modele.
            if ref_max_pixels:
                args += ["--ref-image-args",
                         f"vae_input_max_pixels={int(ref_max_pixels)}"]
        if mask_image and arch != "fibo2":
            args += ["--mask", str(mask_image)]

    # Parametres (certains checkpoints Turbo imposent un nombre d'etapes/CFG fixe)
    cfg = m.get("fixed_cfg", cfg)
    steps = m.get("fixed_steps", steps)
    chosen_sampler = (sampler if (sampler and sampler != "default") else m["defaults"]["sampler"])
    args += ["--cfg-scale", f"{cfg}",
             "--steps", f"{int(steps)}",
             "--sampling-method", chosen_sampler,
             "-H", f"{int(height)}",
             "-W", f"{int(width)}",
             "--seed", f"{int(seed)}",
             "--rng", "cuda",
             "--batch-count", f"{int(batch)}",
             "-o", out_template,
             "-v",
             "--offload-to-cpu"]
    if scheduler and scheduler != "default":
        args += ["--scheduler", str(scheduler)]
    if m.get("sigmas"):
        args += ["--sigmas", m["sigmas"]]

    # --diffusion-fa : FIX ERNIE (bug #1447 -> image blanche)
    if m.get("diffusion_fa", True):
        args += ["--diffusion-fa"]

    # --clip-on-cpu pour les gros encodeurs T5 / CLIP
    if arch in ("flux", "flux_kontext", "chroma", "chroma_radiance", "sd3"):
        args += ["--clip-on-cpu"]

    # Argument specifique Chroma (docs/chroma.md)
    if arch == "chroma":
        args += ["--model-args", "chroma_use_dit_mask=false"]

    # --flow-shift pour ERNIE, Qwen-Image 2512 et LongCat
    if arch in ("ernie", "longcat") or model_id == "qwen-image-2512":
        args += ["--flow-shift", "3"]

    # zero-cond-t pour l'edition des modeles Qwen-Image 2.1
    if m.get("zero_cond_t_on_edit") and has_refs:
        args += ["--model-args", "qwen_image_zero_cond_t=true"]

    # Options Qualité & Détails : VAE Tiling, Skip Layer Guidance (SLG), Upscaling, ADetailer
    if vae_tiling:
        args += ["--vae-tiling"]
    if slg_scale is not None:
        try:
            slg_val = float(slg_scale)
            if slg_val > 0:
                args += ["--slg-scale", f"{slg_val}"]
        except (TypeError, ValueError):
            pass
    if upscale_model:
        args += ["--upscale-model", str(upscale_model), "--upscale-tile-size", "256"]
    if adetailer_model:
        args += ["--ad-model", str(adetailer_model)]

    # --- Performance : mini-VAE rapide (decodage final + apercu en direct) ---
    # Avec --taesd-preview-only, le TAE ne sert qu'aux aperçus etape par etape :
    # l'encodage/decodage final reste pris en charge par le vrai VAE.
    if taesd_path:
        args += ["--taesd", str(taesd_path)]
        if tae_preview_only:
            args += ["--taesd-preview-only"]

    # --- Performance : SageAttention CUDA (attention plus rapide, moins de VRAM) ---
    # Silencieusement ignore par le moteur si la carte/toolkit ne le permet pas.
    if sage_attn:
        args += ["--sage-attn"]

    # --- Apercu en direct pendant l'echantillonnage (none|proj|tae|vae) ---
    if preview_method and preview_method != "none":
        args += ["--preview", str(preview_method)]
        if preview_path:
            args += ["--preview-path", str(preview_path)]
        if preview_interval:
            try:
                args += ["--preview-interval", str(int(preview_interval))]
            except (TypeError, ValueError):
                pass

    # --- PuLID-FLUX : injection d'une empreinte d'identite (seulement arch flux) ---
    if pulid_weights and pulid_id_embedding and supports_pulid(model_id):
        args += ["--pulid-weights", str(pulid_weights),
                 "--pulid-id-embedding", str(pulid_id_embedding)]
        try:
            w = float(pulid_id_weight)
        except (TypeError, ValueError):
            w = PULID["default_weight"]
        w = max(PULID["min_weight"], min(PULID["max_weight"], w))
        args += ["--pulid-id-weight", f"{w}"]

    # LoRA : --lora-model-dir (option officielle sd-cli, pas --lora-dir)
    if lora_dir:
        lora_p = Path(lora_dir)
        if "<lora:" in (prompt or "") or (lora_p.exists() and any(lora_p.glob("*.safetensors"))):
            lora_p.mkdir(parents=True, exist_ok=True)
            args += ["--lora-model-dir", str(lora_p)]

    return args


def build_upscale_command(sd_cli, input_path, output_path, upscale_model_path, tile_size=256,
                          seed=42):
    """
    Construit la commande sd-cli pour agrandir une image existante en mode autonome (-M upscale).
    """
    return [
        str(sd_cli),
        "-M", "upscale",
        "-i", str(input_path),
        "-o", str(output_path),
        "--upscale-model", str(upscale_model_path),
        "--upscale-tile-size", str(int(tile_size)),
        "-s", str(int(seed) if seed not in (None, "") else 42),
        "-v",
    ]


def build_seedvr2_command(sd_cli, input_path, output_path, diffusion_path, vae_path,
                          upscale_factor=2, seed=42):
    """
    Restauration ×2 par diffusion (mode -M vid_upscale de sd-cli, docs/seedvr2.md) :
    reconstruit la matiere (grain de peau, tissus) plutot que de simplement lisser.
    """
    return [
        str(sd_cli),
        "-M", "vid_upscale",
        "--diffusion-model", str(diffusion_path),
        "--vae", str(vae_path),
        "-i", str(input_path),
        "--upscale-factor", str(int(upscale_factor)),
        "-s", str(int(seed) if seed not in (None, "") else 42),
        "-o", str(output_path),
        "-v",
    ]


def build_pid_command(sd_cli, input_path, output_path, model_path, gemma_path,
                      tokenizer_path, vae_path, vae_format, prompt, seed=42,
                      width=4096, height=4096):
    """
    Super-résolution générative ×4 par PiD (NVIDIA Pixel Diffusion, docs/pid.md) :
    ré-encode l'image source avec le VAE du backbone (--vae-format), puis décode
    directement en pixels (4096×4096 par défaut) en 4 étapes distilled.
    PiD tourne comme un pipeline image-édition : -r <image_source> requis.
    """
    return [
        str(sd_cli),
        "--diffusion-model", str(model_path),
        "--llm", str(gemma_path),
        "--tokenizer", str(tokenizer_path),
        "--vae", str(vae_path),
        "--vae-format", str(vae_format),
        "--cfg-scale", "1.0",
        "-p", str(prompt),
        "-r", str(input_path),
        "--steps", "4",
        "-H", str(int(height)), "-W", str(int(width)),
        "-s", str(int(seed) if seed not in (None, "") else 42),
        "-o", str(output_path),
        "--rng", "cpu",
        "-v",
    ]


def build_adetailer_command(model_id, quant, input_path, output_path, sd_cli,
                            manifest, detector_path, prompt=None, seed=42,
                            ad_prompt=None, confidence=0.3, denoise=0.4,
                            inpaint_padding=32, mask_blur=4, slg_scale=None,
                            taesd_path=None, sage_attn=False, lora_dir=None):
    """
    Reparation de visages/mains sur une image EXISTANTE (mode -M adetailer) :
    le detecteur YOLOv8 repere les zones, puis le modele de generation les re-detaille.
    La composition n'est pas touchee hors des zones detectees.
    """
    m = MODELS[model_id]
    arch = m["arch"]
    args = [str(sd_cli), "-M", "adetailer"]

    diff_file = _diffusion_path(model_id, quant)
    args += ["--diffusion-model", diff_file]

    # VAE : meme branchement que la generation
    if m.get("needs_vae", True):
        if arch == "sd3":
            vae_key = "vae_sd3"
        elif arch in ("ernie", "ideogram", "flux2", "flux3", "fibo2", "moss_image"):
            vae_key = "vae_flux2"
        elif arch == "krea2":
            vae_key = "vae_wan21"
        elif arch == "qwen_image":
            vae_key = m.get("vae_dep", "vae_qwen")
        else:
            vae_key = "vae_flux"
        vpath = _dep_path(manifest, vae_key)
        if vpath:
            args += ["--vae", str(vpath)]

    # Encodeurs de texte : miroir compact de build_command
    if arch in ("flux", "flux_kontext"):
        cl, t5 = _dep_path(manifest, "clip_l"), _dep_path(manifest, "t5xxl")
        if cl:
            args += ["--clip_l", str(cl)]
        if t5:
            args += ["--t5xxl", str(t5)]
        args += ["--clip-on-cpu"]
    elif arch in ("chroma", "chroma_radiance"):
        t5 = _dep_path(manifest, "t5xxl")
        if t5:
            args += ["--t5xxl", str(t5)]
        args += ["--clip-on-cpu"]
    elif arch == "longcat":
        llm = _dep_path(manifest, m.get("llm_dep", "qwen25vl_7b"))
        if llm:
            args += ["--llm", str(llm)]
    elif arch == "sd3":
        cl, cg = _dep_path(manifest, "clip_l"), _dep_path(manifest, "clip_g")
        t5 = _dep_path(manifest, "t5xxl")
        if cl:
            args += ["--clip_l", str(cl)]
        if cg:
            args += ["--clip_g", str(cg)]
        if t5:
            args += ["--t5xxl", str(t5)]
        args += ["--clip-on-cpu"]
    elif arch in ("flux2", "flux3"):
        llm = _dep_path(manifest, "qwen3_4b" if model_id == "flux2-klein-4b"
                        else m.get("llm_dep", "qwen3_8b"))
        if llm:
            args += ["--llm", str(llm)]
    elif arch == "fibo2":
        llm = _dep_path(manifest, m.get("llm_dep", "qwen3vl_4b"))
        if llm:
            args += ["--llm", str(llm)]
        mmproj = _dep_path(manifest, m.get("mmproj_dep", "mmproj_qwen3vl_4b"))
        if mmproj:
            args += ["--llm_vision", str(mmproj)]
    elif arch == "moss_image":
        llm = _dep_path(manifest, m.get("llm_dep", "qwen35_9b"))
        if llm:
            args += ["--llm", str(llm)]
        tok = _dep_path(manifest, m.get("tokenizer_dep", "moss_tokenizer"))
        if tok:
            args += ["--tokenizer", str(tok)]
    elif arch == "krea2":
        llm = _dep_path(manifest, m.get("llm_dep", "qwen3vl_4b"))
        if llm:
            args += ["--llm", str(llm)]
    elif arch == "zimage":
        llm = _dep_path(manifest, "qwen3_4b")
        if llm:
            args += ["--llm", str(llm)]
    elif arch == "ernie":
        llm = _dep_path(manifest, "ministral_3b")
        if llm:
            args += ["--llm", str(llm)]
    elif arch == "ideogram":
        llm = _dep_path(manifest, "qwen3vl_8b")
        if llm:
            args += ["--llm", str(llm)]
    elif arch == "iris":
        llm = _dep_path(manifest, "qwen3vl_4b")
        if llm:
            args += ["--llm", str(llm)]
    elif arch == "qwen_image":
        llm = _dep_path(manifest, m.get("llm_dep", "qwen25vl_7b"))
        if llm:
            args += ["--llm", str(llm)]

    # Prompt : par defaut un prompt de reparation generique, jaune du prompt d'origine
    # quand il est fourni (aide le modele a garder la coherence de la scene).
    fix_prompt = (ad_prompt or "").strip() or (prompt or "").strip()
    if not fix_prompt:
        fix_prompt = ("highly detailed, sharp focus, natural skin texture, "
                      "detailed eyes and hands, photorealistic")
    args += ["-p", fix_prompt]

    # Parametres de retouche : force moderee (respecter la zone), CFG/leger,
    # et en nombre d'etapes fixe (la passe est locale, pas besoin de beaucoup).
    cfg = float(m.get("defaults", {}).get("cfg", 1.0) or 1.0)
    steps = int(m.get("defaults", {}).get("steps", 20) or 20)
    steps = max(8, min(30, steps))
    args += ["--cfg-scale", f"{cfg}",
             "--steps", f"{steps}",
             "--sampling-method", (m.get("defaults", {}).get("sampler") or "euler"),
             "--seed", str(int(seed) if seed not in (None, "") else 42),
             "--rng", "cuda",
             "-i", str(input_path),
             "-o", str(output_path),
             "-v",
             "--offload-to-cpu"]

    # Detecteur + reglages de masque (docs/adetailer.md)
    args += ["--ad-model", str(detector_path),
             "--extra-ad-args",
             f"confidence={float(confidence):g},denoising_strength={float(denoise):g},"
             f"inpaint_padding={int(inpaint_padding)},mask_blur={int(mask_blur)}"]

    if slg_scale:
        try:
            sv = float(slg_scale)
            if sv > 0:
                args += ["--slg-scale", f"{sv:g}"]
        except (TypeError, ValueError):
            pass
    if taesd_path:
        args += ["--taesd", str(taesd_path)]
    if sage_attn:
        args += ["--sage-attn"]
    if lora_dir:
        args += ["--lora-model-dir", str(lora_dir)]

    if m.get("sigmas"):
        args += ["--sigmas", m["sigmas"]]
    if arch == "chroma":
        args += ["--model-args", "chroma_use_dit_mask=false"]
    if m.get("diffusion_fa", True):
        args += ["--diffusion-fa"]

    return args


# --------------------------------------------------------------------------- #
#  Presets de resolution
# --------------------------------------------------------------------------- #
def round16(x):
    return max(16, (int(x) // 16) * 16)


RATIOS = {
    "1:1":  (1024, 1024),
    "3:4":  (896, 1152),
    "4:3":  (1152, 896),
    "9:16": (768, 1344),
    "16:9": (1344, 768),
    # Formats additionnels façon Midjourney (--ar)
    "2:3":  (832, 1248),
    "4:5":  (896, 1120),
    "21:9": (1536, 656),
    "9:21": (656, 1536),
}
