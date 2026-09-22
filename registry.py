# -*- coding: utf-8 -*-
"""
Registre des modeles + dependances partagees.
- Chaque modele indique son fichier GGUF par niveau de quant (Q4..Q6).
- Les dependances (VAE, encodeurs de texte) sont telechargees une seule fois.
- build_command() construit la ligne de commande sd-cli adaptee a chaque modele.
"""
import json
import re

from config import (DIFFUSION_DIR, VAE_DIR, TEXTENC_DIR, LLM_DIR, MANIFEST_PATH)


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
    "vae_qwen21": {
        "type": "exact",
        "repo": "Comfy-Org/Qwen-Image-2.1",
        "filename": "vae/qwen_image_2_1_vae.safetensors",
        "dest": VAE_DIR / "qwen_image_2_1_vae.safetensors",
        "size_gb": 0.28,
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
        "size_gb": 3.7,
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
        "repo": "unsloth/Qwen3-4B-Instruct-2507-GGUF",
        "dest_dir": LLM_DIR,
        "size_gb": 2.6,
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
    "vae_sd3": {
        "type": "exact",
        "repo": "stabilityai/stable-diffusion-3.5-large",
        "filename": "vae/diffusion_pytorch_model.safetensors",
        "dest": VAE_DIR / "sd3_vae.safetensors",
        "size_gb": 0.17,
    },
    "mmproj_qwen3vl_8b": {
        "type": "exact",
        "repo": "Qwen/Qwen3-VL-8B-Instruct-GGUF",
        "filename": "mmproj-Qwen3-VL-8B-Instruct-F16.gguf",
        "dest": LLM_DIR / "mmproj-Qwen3-VL-8B-Instruct-F16.gguf",
        "size_gb": 5.5,
    },
}

DEFAULT_NEGATIVE = "blurry, low quality, lowres, distorted, deformed, ugly, bad anatomy, extra limbs, missing fingers, watermark, text, signature, jpeg artifacts, cropped, out of frame, duplicate, mutation"

DEFAULT_NEGATIVE = "blurry, low quality, lowres, distorted, deformed, ugly, bad anatomy, extra limbs, missing fingers, watermark, text, signature, jpeg artifacts, cropped, out of frame, duplicate, mutation"

DEP_QUANT_PRIORITY = ["Q4_K_M", "Q5_K_M", "Q6_K"]


# --------------------------------------------------------------------------- #
#  Modeles de generation d'images
# --------------------------------------------------------------------------- #
# diffusion_fa : False pour ERNIE (bug officiel #1447 -> image blanche)
# needs_vae    : False pour SD3 (VAE integre dans le modele)
MODELS = {
    "flux-schnell": {
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
        "size_gb": {"Q4_K_M": 8.2, "Q5_K_M": 9.6, "Q6_K": 10.5},
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
        "name": "Qwen-Image 2.1",
        "arch": "qwen_image",
        "repo": "leejet/Qwen-Image-2.1-GGUF",
        "quants": ["Q4_0", "Q4_K_M", "Q5_K_M", "Q6_K"],
        "default_quant": "Q5_K_M",
        "file_for_quant": {
            "Q4_0":   "qwen-image-2.1-Q4_0.gguf",
            "Q4_K_M": "qwen-image-2.1-Q4_K_M.gguf",
            "Q5_K_M": "qwen-image-2.1-Q5_K_M.gguf",
            "Q6_K":   "qwen-image-2.1-Q6_K.gguf",
        },
        "size_gb": {"Q4_0": 4.1, "Q4_K_M": 4.6, "Q5_K_M": 5.2, "Q6_K": 5.9},
        "deps": ["vae_qwen21", "qwen3vl_8b"],
        "supports_neg": True,
        "needs_token": False,
        "license": "Qwen Research (usage non-commercial uniquement)",
        "hf_url": "https://huggingface.co/leejet/Qwen-Image-2.1-GGUF",
        "vram_min_gb": 8,
        "desc": "Version 2.1 amelioree. Generation + edition d'images, transparence. Licence non-commercial.",
        "defaults": {"steps": 25, "cfg": 3.5, "sampler": "euler"},
        "min_steps": 10, "max_steps": 50,
    },
    # ---- NOUVEAUX MODELES ----
    "sd3.5-medium": {
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
        "size_gb": {"Q4_K_M": 2.1, "Q5_K_M": 2.4, "Q6_K": 2.6},
        "deps": ["vae_sd3", "clip_l", "clip_g", "t5xxl"],
        "supports_neg": True,
        "needs_token": False,
        "diffusion_fa": False,
        "license": "Stability AI Community (non-commercial <$1M)",
        "hf_url": "https://huggingface.co/city96/stable-diffusion-3.5-medium-gguf",
        "vram_min_gb": 4,
        "needs_token": True,
        "desc": "Modele compact 2.5B, VAE SD3 requis (gated). Bon equilibre qualite/vitesse.",
        "defaults": {"steps": 30, "cfg": 4.5, "sampler": "euler"},
        "min_steps": 10, "max_steps": 50,
    },
    "sd3.5-large": {
        "name": "Stable Diffusion 3.5 Large",
        "arch": "sd3",
        "repo": "city96/stable-diffusion-3.5-large-gguf",
        "quants": ["Q5_0", "Q5_1"],
        "default_quant": "Q5_1",
        "file_for_quant": {
            "Q5_0": "sd3.5_large-Q5_0.gguf",
            "Q5_1": "sd3.5_large-Q5_1.gguf",
        },
        "size_gb": {"Q5_0": 5.3, "Q5_1": 5.6},
        "deps": ["vae_sd3", "clip_l", "clip_g", "t5xxl"],
        "supports_neg": True,
        "needs_token": False,
        "diffusion_fa": False,
        "license": "Stability AI Community (non-commercial <$1M)",
        "hf_url": "https://huggingface.co/city96/stable-diffusion-3.5-large-gguf",
        "vram_min_gb": 6,
        "needs_token": True,
        "desc": "Modele 8B haute qualite. VAE SD3 requis (gated).",
        "defaults": {"steps": 30, "cfg": 4.5, "sampler": "euler"},
        "min_steps": 10, "max_steps": 50,
    },
    "sd3.5-large-turbo": {
        "name": "Stable Diffusion 3.5 Large Turbo",
        "arch": "sd3",
        "repo": "city96/stable-diffusion-3.5-large-turbo-gguf",
        "quants": ["Q4_1", "Q5_1"],
        "default_quant": "Q5_1",
        "file_for_quant": {
            "Q4_1": "sd3.5_large_turbo-Q4_1.gguf",
            "Q5_1": "sd3.5_large_turbo-Q5_1.gguf",
        },
        "size_gb": {"Q4_1": 4.5, "Q5_1": 5.6},
        "deps": ["vae_sd3", "clip_l", "clip_g", "t5xxl"],
        "supports_neg": False,
        "needs_token": False,
        "diffusion_fa": False,
        "license": "Stability AI Community (non-commercial <$1M)",
        "hf_url": "https://huggingface.co/city96/stable-diffusion-3.5-large-turbo-gguf",
        "vram_min_gb": 6,
        "needs_token": True,
        "desc": "Version distillee (4 etapes). VAE SD3 requis (gated). Ultra-rapide.",
        "defaults": {"steps": 4, "cfg": 0.4, "sampler": "euler"},
        "min_steps": 1, "max_steps": 8,
    },
    "flux2-klein-4b": {
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
        "size_gb": {"Q4_K_M": 3.5, "Q5_K_M": 4.1, "Q6_K": 4.5},
        "deps": ["vae_flux2", "qwen3_4b"],
        "supports_neg": False,
        "needs_token": False,
        "license": "Apache 2.0 (libre, commercial OK)",
        "hf_url": "https://huggingface.co/unsloth/FLUX.2-klein-4B-GGUF",
        "vram_min_gb": 4,
        "desc": "Ultra-rapide (4 etapes), sous la seconde. Generation + edition unifies.",
        "defaults": {"steps": 4, "cfg": 1.0, "sampler": "euler"},
        "min_steps": 1, "max_steps": 10,
    },
    "flux2-klein-9b": {
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
        "size_gb": {"Q4_K_M": 6.0, "Q5_K_M": 6.8, "Q6_K": 7.5},
        "deps": ["vae_flux2", "qwen3_8b"],
        "supports_neg": False,
        "needs_token": True,
        "license": "FLUX Non-Commercial (usage perso uniquement)",
        "hf_url": "https://huggingface.co/unsloth/FLUX.2-klein-9B-GGUF",
        "vram_min_gb": 8,
        "desc": "Modele phare BFL. Qualite top en sous-seconde (4 etapes). Non-commercial.",
        "defaults": {"steps": 4, "cfg": 1.0, "sampler": "euler"},
        "min_steps": 1, "max_steps": 10,
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


def resolve_dep_gguf(dep_id: str, files: list, priority=None):
    priority = priority or DEP_QUANT_PRIORITY

    ggufs = [f for f in files if f.lower().endswith(".gguf") and "/" not in f]
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
            return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
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
#  Construction de la commande sd-cli
# --------------------------------------------------------------------------- #
def _dep_path(manifest, dep_id):
    info = manifest.get(dep_id) or {}
    return info.get("path")


def _diffusion_path(model_id, quant):
    m = MODELS[model_id]
    return str(DIFFUSION_DIR / m["file_for_quant"][quant])


def build_command(model_id, quant, prompt, negative, width, height, steps,
                  cfg, seed, batch, out_template, sd_cli, manifest,
                  source_image=None, lora_dir=None, strength=None):
    """
    Construit la commande sd-cli complète.

    Args:
        model_id: ID du modèle
        quant: quantification
        prompt: prompt principal
        negative: prompt négatif
        width, height: dimensions
        steps: nombre d'étapes
        cfg: guidance scale
        seed: seed
        batch: nombre d'images
        out_template: template de sortie
        sd_cli: chemin de sd-cli
        manifest: manifeste des dépendances
        source_image: chemin vers image source pour img2img/edit (optionnel)
        lora_dir: dossier contenant les LoRA (optionnel)
        strength: force de la transformation pour img2img SD (0-1, optionnel)
    """
    m = MODELS[model_id]
    arch = m["arch"]
    args = [sd_cli]

    # Modele de diffusion
    args += ["--diffusion-model", _diffusion_path(model_id, quant)]

    # Modele uncond (Ideogram)
    if arch == "ideogram":
        uncond = m.get("uncond_file_for_quant", {}).get(quant)
        if uncond:
            args += ["--uncond-diffusion-model", str(DIFFUSION_DIR / uncond)]

    # VAE : SD3 a le VAE integre -> pas de --vae
    if m.get("needs_vae", True):
        if arch == "sd3":
            vae_key = "vae_sd3"
        elif arch in ("ernie", "ideogram", "flux2"):
            vae_key = "vae_flux2"
        elif arch == "qwen_image":
            # Qwen-Image 2.1 utilise son propre VAE
            if model_id == "qwen-image-2.1":
                vae_key = "vae_qwen21"
            else:
                vae_key = "vae_qwen"
        else:
            vae_key = "vae_flux"
        args += ["--vae", _dep_path(manifest, vae_key)]

    # Encodeurs de texte
    if arch == "flux":
        args += ["--clip_l", _dep_path(manifest, "clip_l"),
                 "--t5xxl",  _dep_path(manifest, "t5xxl")]
    elif arch == "sd3":
        args += ["--clip_l", _dep_path(manifest, "clip_l"),
                 "--clip_g", _dep_path(manifest, "clip_g"),
                 "--t5xxl",  _dep_path(manifest, "t5xxl")]
    elif arch == "flux2":
        args += ["--llm", _dep_path(manifest, "qwen3_4b" if model_id == "flux2-klein-4b" else "qwen3_8b")]
    elif arch == "zimage":
        args += ["--llm", _dep_path(manifest, "qwen3_4b")]
    elif arch == "ernie":
        args += ["--llm", _dep_path(manifest, "ministral_3b")]
    elif arch == "ideogram":
        args += ["--llm", _dep_path(manifest, "qwen3vl_8b")]
    elif arch == "qwen_image":
        # Qwen-Image 2.1 utilise Qwen3-VL-8B au lieu de Qwen2.5-VL-7B
        if model_id == "qwen-image-2.1":
            args += ["--llm", _dep_path(manifest, "qwen3vl_8b")]
        else:
            args += ["--llm", _dep_path(manifest, "qwen25vl_7b")]

    # Image source pour img2img / edition
    # Qwen-Image-2.1 : -r + --llm_vision (edition semantique avancee)
    if source_image and model_id == "qwen-image-2.1":
        args += ["-r", source_image]
        mmproj_path = _dep_path(manifest, "mmproj_qwen3vl_8b")
        if mmproj_path:
            args += ["--llm_vision", mmproj_path]

    # FLUX.2 Klein : -r pour l'edition (reference image)
    elif source_image and arch == "flux2":
        args += ["-r", source_image]

    # SD 3.5 : --init-image pour img2img classique
    elif source_image and arch == "sd3":
        args += ["--init-image", source_image]
        if strength is not None:
            args += ["--strength", f"{strength}"]

    # Support LoRA (dossier contenant les fichiers .safetensors)
    if lora_dir:
        args += ["--lora-model-dir", lora_dir]

    # Prompt
    if arch == "ideogram":
        args += ["-p", build_ideogram_prompt(prompt, negative, width, height)]
    else:
        args += ["-p", prompt or " "]
        if negative and m.get("supports_neg"):
            args += ["-n", negative]

    # Parametres
    args += ["--cfg-scale", f"{cfg}",
             "--steps", f"{int(steps)}",
             "--sampling-method", m["defaults"]["sampler"],
             "-H", f"{int(height)}",
             "-W", f"{int(width)}",
             "--seed", f"{int(seed)}",
             "--rng", "cuda",
             "--batch-count", f"{int(batch)}",
             "-o", out_template,
             "-v",
             "--offload-to-cpu"]

    # --diffusion-fa : FIX ERNIE (bug #1447 -> image blanche)
    if m.get("diffusion_fa", True):
        args += ["--diffusion-fa"]

    # --clip-on-cpu pour les gros encodeurs
    if arch in ("flux", "sd3"):
        args += ["--clip-on-cpu"]

    # --flow-shift pour les architectures Wan
    if arch in ("qwen_image", "ernie"):
        args += ["--flow-shift", "3"]

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
}
