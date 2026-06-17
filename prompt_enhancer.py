# -*- coding: utf-8 -*-
"""
Enrichissement de prompt par LLM.
Reutilise le modele Qwen3-4B-Instruct-2507 deja telecharge comme dependance
de Z-Image / FLUX.2-klein-4B -> ZERO telechargement supplementaire.
Tourne via llama-cpp-python sur CPU (n'utilise pas de VRAM).
"""
import threading

_llm = None
_lock = threading.Lock()

SYSTEM_PROMPT_ENRICH = (
    "You are an expert prompt engineer for AI image generation. "
    "Given a short image description, rewrite it into a single, detailed, vivid prompt "
    "suitable for a text-to-image diffusion model. "
    "Include: subject details, artistic style, lighting, mood, composition, camera angle, "
    "color palette, and quality keywords. "
    "Write in English. Output ONLY the enriched prompt text, no explanations, no preamble. "
    "Keep it 2-4 sentences, concise but rich. Do not output any thinking."
)

SYSTEM_PROMPT_REPHRASE = (
    "You are an expert prompt engineer. Reformulate the given image description "
    "in a different way, with a fresh angle, while keeping the core subject. "
    "Output ONLY the prompt text in English. Do not output any thinking."
)


def _get_model_path():
    """Retrouve le chemin du Qwen3-4B depuis le manifeste (dependance partagee)."""
    import json
    from config import MANIFEST_PATH, LLM_DIR
    from pathlib import Path

    # 1) Cherche dans le manifeste
    if MANIFEST_PATH.exists():
        try:
            mf = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
            info = mf.get("qwen3_4b") or {}
            if info.get("path") and Path(info["path"]).exists():
                return info["path"]
        except Exception:
            pass

    # 2) Cherche directement dans le dossier LLM
    if LLM_DIR.exists():
        candidates = sorted(LLM_DIR.glob("*Qwen3-4B*Q*_M*.gguf"))
        if not candidates:
            candidates = sorted(LLM_DIR.glob("*Qwen3-4B*.gguf"))
        if candidates:
            return str(candidates[0])
    return None


def enhancer_available():
    """Verifie si un modele LLM est disponible pour l'enrichissement."""
    return _get_model_path() is not None


# Alias pour compatibilite avec l'ancien nom
def enhancer_downloaded():
    return enhancer_available()


def _get_llm():
    """Charge le LLM en memoire (lazy + cache)."""
    global _llm
    if _llm is not None:
        return _llm
    try:
        from llama_cpp import Llama
    except ImportError:
        raise RuntimeError(
            "llama-cpp-python n'est pas installe."
        )
    path = _get_model_path()
    if not path:
        raise RuntimeError(
            "Aucun modele LLM disponible. Telechargez d'abord Z-Image ou "
            "FLUX.2-klein-4B (ils incluent Qwen3-4B qui sert aussi d'enrichisseur)."
        )
    _llm = Llama(
        model_path=str(path),
        n_ctx=2048,
        n_gpu_layers=0,       # CPU pour ne pas concurrencer la generation d'images
        verbose=False,
    )
    return _llm


def enrich_prompt(user_prompt, mode="enrich"):
    """
    Enrichit ou reformule un prompt.
    mode: "enrich" (ajoute des details) ou "rephrase" (reformule differemment).
    Retourne le texte enrichi.
    """
    with _lock:
        llm = _get_llm()

    sys = SYSTEM_PROMPT_REPHRASE if mode == "rephrase" else SYSTEM_PROMPT_ENRICH

    response = llm.create_chat_completion(
        messages=[
            {"role": "system", "content": sys},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=250,
        temperature=0.7,
    )

    text = response["choices"][0]["message"]["content"].strip()
    # nettoyage : retire le bloc <think> si present (Qwen3 thinking mode)
    if "</think>" in text:
        text = text.split("</think>")[-1].strip()
    text = text.strip('"').strip("'").strip()
    return text


def translate_prompt(user_prompt):
    """
    Traduit un prompt de n'importe quelle langue vers l'anglais
    (langue preferee des modeles de generation d'images).
    """
    with _lock:
        llm = _get_llm()

    sys = (
        "You are a professional translator. Translate the given text into English. "
        "If the text is already in English, keep it as-is but you may slightly improve clarity. "
        "Output ONLY the translated text, nothing else. No explanations, no preamble."
    )

    response = llm.create_chat_completion(
        messages=[
            {"role": "system", "content": sys},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=300,
        temperature=0.3,
    )

    text = response["choices"][0]["message"]["content"].strip()
    if "</think>" in text:
        text = text.split("</think>")[-1].strip()
    text = text.strip('"').strip("'").strip()
    return text
