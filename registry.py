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
        return "mmproj" in name and ("qwen3" in name or "qwen_3" in name)
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
            "FLUX.2 Klein dans le Studio d'édition ; pour de l'img2img avec force de "
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
                  ref_images=None, input_mode=None, ref_max_pixels=None):
    m = MODELS[model_id]
    arch = m["arch"]
    args = [sd_cli]

    # --- Entrees image : references (edition) ou image de depart (img2img) ---
    # `ref_images` est la liste ordonnee (index 0 = canvas edite). `source_image`
    # (chaine unique) est conserve pour la retro-compatibilite.
    images = [str(p) for p in (ref_images or []) if p]
    if not images and source_image:
        images = [str(source_image)]
    if input_mode is None:
        # Retro-compatibilite : -i pour les UNet, -r pour les DiT.
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

    # VAE : SD3 a le VAE integre -> pas de --vae
    if m.get("needs_vae", True):
        if arch == "sd3":
            vae_key = "vae_sd3"
        elif arch in ("ernie", "ideogram", "flux2"):
            vae_key = "vae_flux2"
        elif arch == "qwen_image":
            vae_key = m.get("vae_dep", "vae_qwen")
        else:
            vae_key = "vae_flux"
        vpath = _dep_path(manifest, vae_key)
        if vpath:
            args += ["--vae", str(vpath)]

    # Encodeurs de texte
    if arch == "flux":
        cl = _dep_path(manifest, "clip_l")
        t5 = _dep_path(manifest, "t5xxl")
        if cl:
            args += ["--clip_l", str(cl)]
        if t5:
            args += ["--t5xxl", str(t5)]
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

    # Parametres (certains checkpoints Turbo imposent un nombre d'etapes/CFG fixe)
    cfg = m.get("fixed_cfg", cfg)
    steps = m.get("fixed_steps", steps)
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
    if m.get("sigmas"):
        args += ["--sigmas", m["sigmas"]]

    # --diffusion-fa : FIX ERNIE (bug #1447 -> image blanche)
    if m.get("diffusion_fa", True):
        args += ["--diffusion-fa"]

    # --clip-on-cpu pour les gros encodeurs
    if arch in ("flux", "sd3"):
        args += ["--clip-on-cpu"]

    # --flow-shift pour ERNIE et Qwen-Image 2512 ; Turbo utilise ses sigmas fixes.
    if arch == "ernie" or model_id == "qwen-image-2512":
        args += ["--flow-shift", "3"]

    # zero-cond-t pour l'edition des modeles Qwen-Image 2.1
    if m.get("zero_cond_t_on_edit") and has_refs:
        args += ["--model-args", "qwen_image_zero_cond_t=true"]

    # LoRA : --lora-model-dir (option officielle sd-cli, pas --lora-dir)
    if lora_dir:
        lora_p = Path(lora_dir)
        if "<lora:" in (prompt or "") or (lora_p.exists() and any(lora_p.glob("*.safetensors"))):
            lora_p.mkdir(parents=True, exist_ok=True)
            args += ["--lora-model-dir", str(lora_p)]

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
