# -*- coding: utf-8 -*-
"""
Registre des modeles + dependances partagees.
- Chaque modele indique son fichier GGUF par niveau de quant (Q4..Q6).
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
MODELS = {
    "flux-schnell": {
        "presets": {
            "rapide": {'steps': 4, 'cfg': 1.0, 'quant': 'Q4_K_M', 'label': '⚡ Rapide (4 etapes, Q4)'},
            "equilibre": {'steps': 4, 'cfg': 1.0, 'quant': 'Q5_K_M', 'label': '⚡ Rapide+ (4 etapes, Q5)'},
            "qualite": {'steps': 8, 'cfg': 2.0, 'quant': 'Q6_K', 'label': '✨ Qualite (8 etapes, Q6)'},
        },
        "name": 'FLUX.1 schnell',
        "arch": 'flux',
        "repo": 'unsloth/FLUX.1-schnell-GGUF',
        "quants": ['Q4_K_M', 'Q5_K_M', 'Q6_K'],
        "default_quant": 'Q5_K_M',
        "file_for_quant": {'Q4_K_M': 'flux1-schnell-Q4_K_M.gguf', 'Q5_K_M': 'flux1-schnell-Q5_K_M.gguf', 'Q6_K': 'flux1-schnell-Q6_K.gguf'},
        "size_gb": {'Q4_K_M': 6.9, 'Q5_K_M': 8.4, 'Q6_K': 9.8},
        "deps": ['vae_flux', 'clip_l', 't5xxl'],
        "supports_neg": False,
        "needs_token": False,
        "supports_init": True,
        "supports_ref": False,
        "max_ref_images": 0,
        "supports_control": False,
        "supports_mask": False,
        "supports_ip_adapter": False,
        "license": 'Apache 2.0 (libre, commercial OK)',
        "hf_url": 'https://huggingface.co/unsloth/FLUX.1-schnell-GGUF',
        "vram_min_gb": 6,
        "desc": 'Tres rapide (4 etapes), excellent pour des tests expressifs.',
        "defaults": {'steps': 4, 'cfg': 1.0, 'sampler': 'euler'},
        "min_steps": 1,
        "max_steps": 8,
    },

    "z-image": {
        "presets": {
            "rapide": {'steps': 14, 'cfg': 3.0, 'quant': 'Q4_K_M', 'label': '⚡ Rapide (14 etapes, Q4)'},
            "equilibre": {'steps': 28, 'cfg': 4.0, 'quant': 'Q5_K_M', 'label': '⚖️ Equilibre (28 etapes, Q5)'},
            "qualite": {'steps': 40, 'cfg': 5.0, 'quant': 'Q6_K', 'label': '✨ Qualite (40 etapes, Q6)'},
        },
        "name": 'Z-Image',
        "arch": 'zimage',
        "repo": 'unsloth/Z-Image-GGUF',
        "quants": ['Q4_K_M', 'Q5_K_M', 'Q6_K'],
        "default_quant": 'Q5_K_M',
        "file_for_quant": {'Q4_K_M': 'z-image-Q4_K_M.gguf', 'Q5_K_M': 'z-image-Q5_K_M.gguf', 'Q6_K': 'z-image-Q6_K.gguf'},
        "size_gb": {'Q4_K_M': 5.1, 'Q5_K_M': 5.6, 'Q6_K': 6.1},
        "deps": ['vae_flux', 'qwen3_4b'],
        "supports_neg": True,
        "needs_token": False,
        "supports_init": True,
        "supports_ref": False,
        "max_ref_images": 0,
        "supports_control": False,
        "supports_mask": False,
        "supports_ip_adapter": False,
        "license": 'Apache 2.0 (libre, commercial OK)',
        "hf_url": 'https://huggingface.co/unsloth/Z-Image-GGUF',
        "vram_min_gb": 4,
        "desc": 'Modele fondamental polyvalent, excellent respect du prompt.',
        "defaults": {'steps': 28, 'cfg': 4.0, 'sampler': 'euler'},
        "min_steps": 10,
        "max_steps": 50,
    },

    "ernie-turbo": {
        "presets": {
            "rapide": {'steps': 8, 'cfg': 1.0, 'quant': 'Q4_K_M', 'label': '⚡ Rapide (8 etapes, Q4)'},
            "equilibre": {'steps': 12, 'cfg': 2.0, 'quant': 'Q5_K_M', 'label': '⚖️ Equilibre (12 etapes, Q5)'},
            "qualite": {'steps': 20, 'cfg': 3.5, 'quant': 'Q6_K', 'label': '✨ Qualite (20 etapes, Q6)'},
        },
        "name": 'ERNIE-Image Turbo',
        "arch": 'ernie',
        "repo": 'unsloth/ERNIE-Image-Turbo-GGUF',
        "quants": ['Q4_K_M', 'Q5_K_M', 'Q6_K'],
        "default_quant": 'Q5_K_M',
        "file_for_quant": {'Q4_K_M': 'ernie-image-turbo-Q4_K_M.gguf', 'Q5_K_M': 'ernie-image-turbo-Q5_K_M.gguf', 'Q6_K': 'ernie-image-turbo-Q6_K.gguf'},
        "size_gb": {'Q4_K_M': 5.0, 'Q5_K_M': 5.6, 'Q6_K': 6.1},
        "deps": ['vae_flux2', 'ministral_3b'],
        "supports_neg": False,
        "needs_token": False,
        "supports_init": True,
        "supports_ref": False,
        "max_ref_images": 0,
        "supports_control": False,
        "supports_mask": False,
        "supports_ip_adapter": False,
        "license": 'Apache 2.0 (libre, commercial OK)',
        "hf_url": 'https://huggingface.co/unsloth/ERNIE-Image-Turbo-GGUF',
        "vram_min_gb": 4,
        "desc": "Rapide (8 etapes), tres bon pour le texte dans l'image.",
        "defaults": {'steps': 8, 'cfg': 1.0, 'sampler': 'euler'},
        "min_steps": 4,
        "max_steps": 20,
        "diffusion_fa": False,
    },

    "ideogram4": {
        "presets": {
            "rapide": {'steps': 8, 'cfg': 3.0, 'quant': 'Q4_0', 'label': '⚡ Rapide (8 etapes)'},
            "equilibre": {'steps': 12, 'cfg': 4.0, 'quant': 'Q4_0', 'label': '⚖️ Equilibre (12 etapes)'},
            "qualite": {'steps': 20, 'cfg': 5.0, 'quant': 'Q4_0', 'label': '✨ Qualite (20 etapes)'},
        },
        "name": 'Ideogram 4',
        "arch": 'ideogram',
        "repo": 'leejet/ideogram-4-GGUF',
        "quants": ['Q4_0'],
        "default_quant": 'Q4_0',
        "file_for_quant": {'Q4_0': 'ideogram4-Q4_0.gguf'},
        "uncond_file_for_quant": {'Q4_0': 'ideogram4_uncond-Q4_0.gguf'},
        "size_gb": {'Q4_0': 11.3},
        "deps": ['vae_flux2', 'qwen3vl_8b'],
        "supports_neg": False,
        "needs_token": False,
        "supports_init": True,
        "supports_ref": False,
        "max_ref_images": 0,
        "supports_control": False,
        "supports_mask": False,
        "supports_ip_adapter": False,
        "license": 'Ideogram (lire les conditions)',
        "hf_url": 'https://huggingface.co/leejet/ideogram-4-GGUF',
        "vram_min_gb": 10,
        "desc": 'Rendu de texte top mais Q4_0 limite la qualite. Prompt converti en JSON automatiquement.',
        "defaults": {'steps': 12, 'cfg': 4.0, 'sampler': 'euler'},
        "min_steps": 4,
        "max_steps": 30,
    },

    "fhdr": {
        "presets": {
            "rapide": {'steps': 12, 'cfg': 2.5, 'quant': 'Q4_K_M', 'label': '⚡ Rapide (12 etapes)'},
            "equilibre": {'steps': 20, 'cfg': 3.5, 'quant': 'Q4_K_M', 'label': '⚖️ Equilibre (20 etapes)'},
            "qualite": {'steps': 35, 'cfg': 4.5, 'quant': 'Q4_K_M', 'label': '✨ Qualite (35 etapes)'},
        },
        "name": 'FHDR Uncensored (FLUX-dev)',
        "arch": 'flux',
        "repo": 'kpsss34/FHDR_Uncensored',
        "quants": ['Q4_K_M'],
        "default_quant": 'Q4_K_M',
        "file_for_quant": {'Q4_K_M': 'FHDR_ComfyUI-Q4_K_M.gguf'},
        "size_gb": {'Q4_K_M': 6.9},
        "deps": ['vae_flux', 'clip_l', 't5xxl'],
        "supports_neg": True,
        "needs_token": True,
        "supports_init": True,
        "supports_ref": False,
        "max_ref_images": 0,
        "supports_control": False,
        "supports_mask": False,
        "supports_ip_adapter": False,
        "license": 'FLUX.1-dev Non-Commercial (usage perso uniquement)',
        "hf_url": 'https://huggingface.co/kpsss34/FHDR_Uncensored',
        "vram_min_gb": 6,
        "desc": 'FLUX.1-dev sans censure. Necessite un token Hugging Face.',
        "defaults": {'steps': 20, 'cfg': 3.5, 'sampler': 'euler'},
        "min_steps": 8,
        "max_steps": 40,
    },

    "qwen-image-2512": {
        "presets": {
            "rapide": {'steps': 15, 'cfg': 2.0, 'quant': 'Q4_K_M', 'label': '⚡ Rapide (15 etapes, Q4)'},
            "equilibre": {'steps': 30, 'cfg': 4.0, 'quant': 'Q5_K_M', 'label': '⚖️ Equilibre (30 etapes, Q5)'},
            "qualite": {'steps': 50, 'cfg': 5.0, 'quant': 'Q6_K', 'label': '✨ Qualite (50 etapes, Q6)'},
            "optimise": {'steps': 25, 'cfg': 3.5, 'quant': 'Q5_K_M', 'label': '🎯 Optimise edition (25 etapes)'},
        },
        "name": 'Qwen-Image 2512',
        "arch": 'qwen_image',
        "repo": 'unsloth/Qwen-Image-2512-GGUF',
        "quants": ['Q4_K_M', 'Q5_K_M', 'Q6_K'],
        "default_quant": 'Q5_K_M',
        "file_for_quant": {'Q4_K_M': 'qwen-image-2512-Q4_K_M.gguf', 'Q5_K_M': 'qwen-image-2512-Q5_K_M.gguf', 'Q6_K': 'qwen-image-2512-Q6_K.gguf'},
        "size_gb": {'Q4_K_M': 13.2, 'Q5_K_M': 15.0, 'Q6_K': 16.8},
        "deps": ['vae_qwen', 'qwen25vl_7b'],
        "supports_neg": True,
        "needs_token": False,
        "supports_init": False,
        "supports_ref": True,
        "max_ref_images": 3,
        "supports_control": False,
        "supports_mask": False,
        "supports_ip_adapter": False,
        "license": 'Apache 2.0 (libre, commercial OK)',
        "hf_url": 'https://huggingface.co/unsloth/Qwen-Image-2512-GGUF',
        "vram_min_gb": 8,
        "desc": 'Realisme humain ameliore, details naturels et rendu de texte.',
        "defaults": {'steps': 30, 'cfg': 4.0, 'sampler': 'euler'},
        "min_steps": 10,
        "max_steps": 60,
    },

    "qwen-image-2.1": {
        "presets": {
            "rapide": {'steps': 15, 'cfg': 1.0, 'quant': 'Q4_K_M', 'label': '⚡ Rapide (15 etapes, Q4)'},
            "equilibre": {'steps': 25, 'cfg': 3.5, 'quant': 'Q5_K_M', 'label': '⚖️ Equilibre (25 etapes, Q5)'},
            "qualite": {'steps': 40, 'cfg': 6.0, 'quant': 'Q6_K', 'label': '✨ Qualite (40 etapes, Q6)'},
            "optimise": {'steps': 20, 'cfg': 1.0, 'quant': 'Q4_K_M', 'label': '🎯 Optimise edition (20 etapes, Q4)'},
        },
        "name": 'Qwen-Image-2.1',
        "arch": 'qwen_image',
        "repo": 'unsloth/Qwen-Image-2.1-GGUF',
        "quants": ['Q4_K_M', 'Q5_K_M', 'Q6_K'],
        "default_quant": 'Q5_K_M',
        "file_for_quant": {'Q4_K_M': 'qwen-image-2.1-Q4_K_M.gguf', 'Q5_K_M': 'qwen-image-2.1-Q5_K_M.gguf', 'Q6_K': 'qwen-image-2.1-Q6_K.gguf'},
        "size_gb": {'Q4_K_M': 4.2, 'Q5_K_M': 5.4, 'Q6_K': 6.3},
        "deps": ['vae_qwen_21', 'qwen3vl_8b', 'mmproj_qwen3vl_8b'],
        "supports_neg": False,
        "needs_token": False,
        "supports_img2img": True,
        "supports_init": False,
        "supports_ref": True,
        "max_ref_images": 10,
        "supports_control": False,
        "supports_mask": False,
        "supports_ip_adapter": False,
        "supports_transparency": True,
        "license": 'Qwen Research License (usage non-commercial)',
        "hf_url": 'https://huggingface.co/unsloth/Qwen-Image-2.1-GGUF',
        "vram_min_gb": 8,
        "desc": "Edition multi-images jusqu'a 10 refs + transparence RGBA + text2image. mmproj requis pour edition.",
        "defaults": {'steps': 25, 'cfg': 3.5, 'sampler': 'euler'},
        "min_steps": 10,
        "max_steps": 50,
    },

    "sd3.5-medium": {
        "presets": {
            "rapide": {'steps': 15, 'cfg': 3.5, 'quant': 'Q4_K_M', 'label': '⚡ Rapide (15 etapes, Q4)'},
            "equilibre": {'steps': 30, 'cfg': 4.5, 'quant': 'Q5_K_M', 'label': '⚖️ Equilibre (30 etapes, Q5)'},
            "qualite": {'steps': 45, 'cfg': 5.5, 'quant': 'Q6_K', 'label': '✨ Qualite (45 etapes, Q6)'},
        },
        "name": 'Stable Diffusion 3.5 Medium',
        "arch": 'sd3',
        "repo": 'city96/stable-diffusion-3.5-medium-gguf',
        "quants": ['Q4_K_M', 'Q5_K_M', 'Q6_K'],
        "default_quant": 'Q5_K_M',
        "file_for_quant": {'Q4_K_M': 'sd3.5_medium-Q4_K_M.gguf', 'Q5_K_M': 'sd3.5_medium-Q5_K_M.gguf', 'Q6_K': 'sd3.5_medium-Q6_K.gguf'},
        "size_gb": {'Q4_K_M': 1.8, 'Q5_K_M': 2.1, 'Q6_K': 2.3},
        "deps": ['vae_sd3', 'clip_l', 'clip_g', 't5xxl'],
        "supports_neg": True,
        "needs_token": True,
        "supports_init": True,
        "supports_ref": False,
        "max_ref_images": 0,
        "supports_control": True,
        "supports_mask": True,
        "supports_ip_adapter": True,
        "license": 'Stability AI Community (non-commercial <$1M)',
        "hf_url": 'https://huggingface.co/city96/stable-diffusion-3.5-medium-gguf',
        "vram_min_gb": 4,
        "desc": 'Modele compact 2.5B, VAE SD3 requis (gated). Bon equilibre qualite/vitesse.',
        "defaults": {'steps': 30, 'cfg': 4.5, 'sampler': 'euler'},
        "min_steps": 10,
        "max_steps": 50,
        "diffusion_fa": False,
    },

    "sd3.5-large": {
        "presets": {
            "rapide": {'steps': 15, 'cfg': 3.5, 'quant': 'Q5_0', 'label': '⚡ Rapide (15 etapes, Q5_0)'},
            "equilibre": {'steps': 30, 'cfg': 4.5, 'quant': 'Q5_1', 'label': '⚖️ Equilibre (30 etapes, Q5_1)'},
            "qualite": {'steps': 45, 'cfg': 5.5, 'quant': 'Q5_1', 'label': '✨ Qualite (45 etapes, Q5_1)'},
        },
        "name": 'Stable Diffusion 3.5 Large',
        "arch": 'sd3',
        "repo": 'city96/stable-diffusion-3.5-large-gguf',
        "quants": ['Q5_0', 'Q5_1'],
        "default_quant": 'Q5_1',
        "file_for_quant": {'Q5_0': 'sd3.5_large-Q5_0.gguf', 'Q5_1': 'sd3.5_large-Q5_1.gguf'},
        "size_gb": {'Q5_0': 5.8, 'Q5_1': 6.3},
        "deps": ['vae_sd3', 'clip_l', 'clip_g', 't5xxl'],
        "supports_neg": True,
        "needs_token": True,
        "supports_init": True,
        "supports_ref": False,
        "max_ref_images": 0,
        "supports_control": True,
        "supports_mask": True,
        "supports_ip_adapter": True,
        "license": 'Stability AI Community (non-commercial <$1M)',
        "hf_url": 'https://huggingface.co/city96/stable-diffusion-3.5-large-gguf',
        "vram_min_gb": 6,
        "desc": 'Modele 8B haute qualite. VAE SD3 requis (gated).',
        "defaults": {'steps': 30, 'cfg': 4.5, 'sampler': 'euler'},
        "min_steps": 10,
        "max_steps": 50,
        "diffusion_fa": False,
    },

    "sd3.5-large-turbo": {
        "presets": {
            "rapide": {'steps': 4, 'cfg': 0.4, 'quant': 'Q4_1', 'label': '⚡ Ultra-rapide (4 etapes, Q4_1)'},
            "equilibre": {'steps': 4, 'cfg': 0.4, 'quant': 'Q5_1', 'label': '⚖️ Equilibre (4 etapes, Q5_1)'},
            "qualite": {'steps': 6, 'cfg': 0.6, 'quant': 'Q5_1', 'label': '✨ Qualite (6 etapes, Q5_1)'},
        },
        "name": 'Stable Diffusion 3.5 Large Turbo',
        "arch": 'sd3',
        "repo": 'city96/stable-diffusion-3.5-large-turbo-gguf',
        "quants": ['Q4_1', 'Q5_1'],
        "default_quant": 'Q5_1',
        "file_for_quant": {'Q4_1': 'sd3.5_large_turbo-Q4_1.gguf', 'Q5_1': 'sd3.5_large_turbo-Q5_1.gguf'},
        "size_gb": {'Q4_1': 5.3, 'Q5_1': 6.3},
        "deps": ['vae_sd3', 'clip_l', 'clip_g', 't5xxl'],
        "supports_neg": False,
        "needs_token": True,
        "supports_init": True,
        "supports_ref": False,
        "max_ref_images": 0,
        "supports_control": False,
        "supports_mask": True,
        "supports_ip_adapter": False,
        "license": 'Stability AI Community (non-commercial <$1M)',
        "hf_url": 'https://huggingface.co/city96/stable-diffusion-3.5-large-turbo-gguf',
        "vram_min_gb": 6,
        "desc": 'Version distillee (4 etapes). VAE SD3 requis (gated). Ultra-rapide.',
        "defaults": {'steps': 4, 'cfg': 0.4, 'sampler': 'euler'},
        "min_steps": 1,
        "max_steps": 8,
        "diffusion_fa": False,
    },

    "flux2-klein-4b": {
        "presets": {
            "rapide": {'steps': 4, 'cfg': 1.0, 'quant': 'Q4_K_M', 'label': '⚡ Ultra-rapide (4 etapes, Q4)'},
            "equilibre": {'steps': 4, 'cfg': 1.0, 'quant': 'Q5_K_M', 'label': '⚖️ Equilibre (4 etapes, Q5)'},
            "qualite": {'steps': 6, 'cfg': 2.0, 'quant': 'Q6_K', 'label': '✨ Qualite (6 etapes, Q6)'},
            "optimise": {'steps': 4, 'cfg': 1.0, 'quant': 'Q4_K_M', 'label': '🎯 Optimise edition (4 etapes, Q4)'},
        },
        "name": 'FLUX.2 Klein 4B',
        "arch": 'flux2',
        "repo": 'unsloth/FLUX.2-klein-4B-GGUF',
        "quants": ['Q4_K_M', 'Q5_K_M', 'Q6_K'],
        "default_quant": 'Q5_K_M',
        "file_for_quant": {'Q4_K_M': 'flux-2-klein-4b-Q4_K_M.gguf', 'Q5_K_M': 'flux-2-klein-4b-Q5_K_M.gguf', 'Q6_K': 'flux-2-klein-4b-Q6_K.gguf'},
        "size_gb": {'Q4_K_M': 2.6, 'Q5_K_M': 2.9, 'Q6_K': 3.3},
        "deps": ['vae_flux2', 'qwen3_4b'],
        "supports_neg": False,
        "needs_token": False,
        "supports_img2img": True,
        "supports_init": True,
        "supports_ref": True,
        "max_ref_images": 4,
        "supports_control": False,
        "supports_mask": False,
        "supports_ip_adapter": False,
        "license": 'Apache 2.0 (libre, commercial OK)',
        "hf_url": 'https://huggingface.co/unsloth/FLUX.2-klein-4B-GGUF',
        "vram_min_gb": 4,
        "desc": "Ultra-rapide (4 etapes) + edition multi-ref (jusqu'a 4 images) + img2img.",
        "defaults": {'steps': 4, 'cfg': 1.0, 'sampler': 'euler'},
        "min_steps": 1,
        "max_steps": 10,
    },

    "flux2-klein-9b": {
        "presets": {
            "rapide": {'steps': 4, 'cfg': 1.0, 'quant': 'Q4_K_M', 'label': '⚡ Ultra-rapide (4 etapes, Q4)'},
            "equilibre": {'steps': 4, 'cfg': 1.0, 'quant': 'Q5_K_M', 'label': '⚖️ Equilibre (4 etapes, Q5)'},
            "qualite": {'steps': 6, 'cfg': 2.0, 'quant': 'Q6_K', 'label': '✨ Qualite (6 etapes, Q6)'},
            "optimise": {'steps': 4, 'cfg': 1.0, 'quant': 'Q4_K_M', 'label': '🎯 Optimise edition (4 etapes, Q4)'},
        },
        "name": 'FLUX.2 Klein 9B',
        "arch": 'flux2',
        "repo": 'unsloth/FLUX.2-klein-9B-GGUF',
        "quants": ['Q4_K_M', 'Q5_K_M', 'Q6_K'],
        "default_quant": 'Q5_K_M',
        "file_for_quant": {'Q4_K_M': 'flux-2-klein-9b-Q4_K_M.gguf', 'Q5_K_M': 'flux-2-klein-9b-Q5_K_M.gguf', 'Q6_K': 'flux-2-klein-9b-Q6_K.gguf'},
        "size_gb": {'Q4_K_M': 5.9, 'Q5_K_M': 6.7, 'Q6_K': 7.5},
        "deps": ['vae_flux2', 'qwen3_8b'],
        "supports_neg": False,
        "needs_token": True,
        "supports_img2img": True,
        "supports_init": True,
        "supports_ref": True,
        "max_ref_images": 4,
        "supports_control": False,
        "supports_mask": False,
        "supports_ip_adapter": False,
        "license": 'FLUX Non-Commercial (usage perso uniquement)',
        "hf_url": 'https://huggingface.co/unsloth/FLUX.2-klein-9B-GGUF',
        "vram_min_gb": 8,
        "desc": 'Modele phare BFL + edition multi-ref (4 images) + img2img. Non-commercial.',
        "defaults": {'steps': 4, 'cfg': 1.0, 'sampler': 'euler'},
        "min_steps": 1,
        "max_steps": 10,
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
    elif dep_id == "qwen3vl_8b":
        return ("qwen3" in name or "qwen_3" in name) and "vl" in name and "mmproj" not in name
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
                  ref_images=None, init_image=None, control_image=None,
                  mask_image=None, ip_adapter_image=None,
                  control_strength=None, ip_adapter_strength=None):
    """
    Construit la commande sd-cli.
    - source_image : legacy, pour compatibilité (mappe vers init ou ref selon arch)
    - ref_images : liste d'images de référence (édition multi-images, Qwen-Image 2.1 jusqu'à 10, FLUX.2 Klein)
    - init_image : image initiale pour img2img classique (SD3.5, FLUX, etc)
    - control_image : image de contrôle / pose (ControlNet)
    - mask_image : masque pour inpainting
    - ip_adapter_image : image pour IP-Adapter (style / référence)
    - strength : force img2img (0..1)
    - control_strength : force du control
    - ip_adapter_strength : force IP-Adapter
    """
    m = MODELS[model_id]
    arch = m["arch"]
    args = [sd_cli]

    # Compatibilité ascendante : si source_image fourni mais pas ref/init, mapper selon arch
    if source_image and not ref_images and not init_image:
        if arch in ("sd3", "sd") or m.get("supports_init") and not m.get("supports_ref"):
            init_image = source_image
        else:
            ref_images = [source_image]

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
            vae_key = "vae_qwen_21" if model_id == "qwen-image-2.1" else "vae_qwen"
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
    elif arch == "qwen_image":
        llm_key = "qwen3vl_8b" if model_id == "qwen-image-2.1" else "qwen25vl_7b"
        llm = _dep_path(manifest, llm_key)
        if llm:
            args += ["--llm", str(llm)]
        # mmproj pour l'edition (Qwen-Image-2.1)
        if model_id == "qwen-image-2.1":
            mmproj = _dep_path(manifest, "mmproj_qwen3vl_8b")
            if mmproj:
                args += ["--llm_vision", str(mmproj)]

    # Prompt
    if arch == "ideogram":
        args += ["-p", build_ideogram_prompt(prompt, negative, width, height)]
    else:
        args += ["-p", prompt or " "]
        if negative and m.get("supports_neg"):
            args += ["-n", negative]

    # --- Images d'entrée (nouvelle API multi-images) ---
    # Image initiale (img2img classique)
    if init_image:
        args += ["-i", init_image]
        if strength is not None:
            args += ["--strength", f"{strength}"]

    # Images de référence (édition multi-images) - Qwen-Image 2.1 supporte jusqu'à 10 via -r répété
    if ref_images:
        # Limiter au max supporté par le modèle (sécurité)
        max_ref = m.get("max_ref_images", 10) or 10
        # Si max_ref == 0, on autorise quand même 1 pour compatibilité (certains modèles supportent ref sans l'annoncer)
        if max_ref == 0:
            max_ref = 4
        for img_path in ref_images[:max_ref]:
            args += ["-r", img_path]
        # Si ref_images présent et strength fourni mais pas d'init_image, strength s'applique parfois à l'édition ?
        # Pour Qwen-Image 2.1, strength n'est pas utilisé, mais on le garde pour d'autres modèles
        if not init_image and strength is not None and arch in ("sd3", "sd"):
            # Dans le cas où l'utilisateur a fourni ref_images mais voulait init, on a déjà géré via compatibilité
            pass

    # Image de contrôle / pose (ControlNet)
    if control_image:
        args += ["--control-image", control_image]
        if control_strength is not None:
            args += ["--control-strength", f"{control_strength}"]

    # Masque (inpainting)
    if mask_image:
        args += ["--mask", mask_image]

    # IP-Adapter image (style / référence supplémentaire)
    if ip_adapter_image:
        args += ["--ip-adapter-image", ip_adapter_image]
        if ip_adapter_strength is not None:
            args += ["--ip-adapter-strength", f"{ip_adapter_strength}"]

    # Legacy: si source_image encore présent après mapping et pas déjà traité (cas où ref_images et init_image déjà traités)
    # On ne refait rien, déjà mappé

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

    # --flow-shift pour Wan (Qwen-Image 2512 et ERNIE) ; Qwen-Image 2.1 utilise un flow schedule automatique
    if arch == "ernie" or model_id == "qwen-image-2512":
        args += ["--flow-shift", "3"]

    # zero-cond-t pour meilleure qualite d'edition Qwen-Image-2.1 quand ref_images présent
    has_ref = bool(ref_images) or bool(source_image)
    if model_id == "qwen-image-2.1" and has_ref:
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
