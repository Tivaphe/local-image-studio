# -*- coding: utf-8 -*-
"""Mode « 🧠 Thinking » : le prompt de l'utilisateur passe d'abord par un modèle
de raisonnement (texte pour la génération, vision pour l'édition) qui produit un
prompt final anglais, montré à l'utilisateur AVANT toute génération — aperçu
obligatoire avec confirmation, jamais de substitution silencieuse.

Réutilise la stack llama.cpp officielle des légendeurs (catalogue CAPTIONER_MODELS)
pour ne pas embarquer un second runtime. Limites assumées :
- réflexion limitée par THINK_MAX_TOKENS ; les modèles non « thinking » répondent
  sans blocs <think> (raisonnement absent, la fonctionnalité reste utile) ;
- sur machines modestes la latence peut être longue — un minuteur est affiché dans
  la modale et « Annuler » tue le sous-processus ;
- dégradation honnête : sans llama.cpp, Générer/Traduire/Enrichir retombent sur le
  Qwen3-4B CPU (prompt_enhancer, sans raisonnement) avec le moteur indiqué dans la
  réponse ; l'édition (vision indispensable) refuse net.
"""
import base64
import json
import re
import subprocess
import threading
import time
from pathlib import Path

import config
import engine

THINK_MAX_TOKENS = 2048      # génération / édition (raisonnement + réponse)
TEXT_MAX_TOKENS = 1024       # traduction / enrichissement

# --------------------------------------------------------------------------- #
#  Invites système
# --------------------------------------------------------------------------- #
GENERATE_THINK_SYSTEM = (
    "You are an expert prompt engineer for text-to-image diffusion models.\n"
    "The user writes a short description, often in French. Think step by step: "
    "subject and action, appearance, setting/background, composition and framing, "
    "lighting, color palette, art medium and style, mood, quality keywords.\n"
    "Then output ONLY the final prompt — a single dense paragraph in English, "
    "maximum 120 words, no preamble, no quotes, no markdown, no negative prompt."
)

EDIT_THINK_SYSTEM = (
    "You are an expert prompt engineer for instruction-based image editing.\n"
    "You are shown the source image plus the user's edit instruction, often in French. "
    "Think step by step: what the subject/identity is and what MUST stay unchanged "
    "(face, pose, composition, camera angle, background), and exactly what must change "
    "according to the instruction. Keep the prompt faithful to the source except for "
    "the requested change.\n"
    "Then output ONLY the final English edit prompt — a single dense paragraph, "
    "no preamble, no quotes, no markdown."
)

TRANSLATE_SYSTEM = (
    "You are a professional translator. Translate the given text into English. "
    "If the text is already in English, keep it as-is but you may slightly improve clarity. "
    "Output ONLY the translated text, nothing else. No explanations, no preamble."
)

ENRICH_SYSTEM = (
    "You are an expert prompt engineer for AI image generation. "
    "Given a short image description, rewrite it into a single, detailed, vivid prompt "
    "suitable for a text-to-image diffusion model. "
    "Include: subject details, artistic style, lighting, mood, composition, camera angle, "
    "color palette, and quality keywords. "
    "Write in English. Output ONLY the enriched prompt text, no explanations, no preamble. "
    "Keep it 2-4 sentences, concise but rich."
)

TASK_SYSTEMS = {
    "generate": GENERATE_THINK_SYSTEM,
    "edit": EDIT_THINK_SYSTEM,
    "translate": TRANSLATE_SYSTEM,
    "enrich": ENRICH_SYSTEM,
}

# --------------------------------------------------------------------------- #
#  Découpage raisonnement / réponse
# --------------------------------------------------------------------------- #
_THINK_RE = re.compile(r"<think>(.*?)</think>", re.S | re.I)
_THINK_TAIL_RE = re.compile(r"<think>(.*)$", re.S | re.I)


def split_think(text):
    """Retourne (reasoning, final) à partir de la sortie brute du modèle.

    Tolère un bloc <think> non terminé (modèle coupé par le budget de tokens)
    et plusieurs blocs. `final` est normalisé (espaces, guillemets enveloppants).
    """
    if not text:
        return "", ""
    reasoning_parts = [p.strip() for p in _THINK_RE.findall(text)]
    final = _THINK_RE.sub("", text)
    tail = _THINK_TAIL_RE.search(final)
    if tail:
        reasoning_parts.append(tail.group(1).strip())
        final = final[:tail.start()]
    reasoning = "\n".join(p for p in reasoning_parts if p).strip()
    final = re.sub(r"\s+", " ", final).strip().strip('"').strip("`").strip()
    # nettoyage des puces/« Prompt: » de tête que les modèles ajoutent parfois
    final = re.sub(r"^(final\s+(?:english\s+)?prompt\s*:\s*)", "", final, flags=re.I).strip()
    return reasoning, final


# --------------------------------------------------------------------------- #
#  Résolution du modèle + annulation coopérative
# --------------------------------------------------------------------------- #
def resolve_think_captioner_id(settings):
    """thinking_model (explicite) > captioner_model (explicite) > "" (auto côté appelant)."""
    from registry import CAPTIONER_MODELS
    explicit = str((settings or {}).get("thinking_model") or "").strip()
    if explicit:
        return explicit if explicit in CAPTIONER_MODELS else ""
    cm = str((settings or {}).get("captioner_model") or "").strip()
    return cm if cm in CAPTIONER_MODELS else ""


_cancel_lock = threading.Lock()
_cancel_proc = None


def _track(proc):
    global _cancel_proc
    with _cancel_lock:
        _cancel_proc = proc


def _untrack():
    global _cancel_proc
    with _cancel_lock:
        _cancel_proc = None


def cancel_current():
    """Tue le sous-processus du thinking en cours (s'il y en a un). Retourne True si un suivi existait."""
    with _cancel_lock:
        proc = _cancel_proc
    if proc is None:
        return False
    try:
        if proc.poll() is None:
            proc.terminate()
    except Exception:
        pass
    return True


def _resolve_image(image_rel):
    """Valide le chemin image fourni (dans le dépôt, fichier image existant)."""
    if not image_rel:
        return None
    rel = str(image_rel).strip()
    if not rel:
        return None
    p = Path(rel)
    if not p.is_absolute():
        p = (config.ROOT / rel).resolve()
    try:
        p.relative_to(config.ROOT.resolve())
    except Exception:
        raise ValueError("Chemin d'image invalide.")
    if not p.exists() or not p.is_file():
        raise ValueError("Image introuvable : " + rel)
    if p.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"):
        raise ValueError("Format d'image non pris en charge (png/jpg/webp/gif/bmp).")
    return p


# --------------------------------------------------------------------------- #
#  Backend llama-server (texte seul ou vision, raisonnement séparé si supporté)
# --------------------------------------------------------------------------- #
def _image_data_url(path: Path) -> str:
    mime = engine._guess_image_mime(path)
    raw = path.read_bytes()
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def _server_chat(server_path, model, mmproj, system, user_text, image_abs, max_tokens):
    """Retourne (content, reasoning_from_server, finish_reason)."""
    port = engine._pick_free_port()
    cmd = [str(server_path), "-m", str(model)]
    if mmproj:
        cmd += ["--mmproj", str(mmproj)]
    cmd += ["-ngl", "99", "--host", "127.0.0.1", "--port", str(port)]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, errors="replace")
    except Exception as e:
        raise RuntimeError(f"Impossible de lancer {server_path} : {e}")
    _track(proc)

    def _tail():
        try:
            if proc.stdout:
                return proc.stdout.read()[-1500:]
        except Exception:
            return ""
        return ""

    try:
        deadline = time.time() + engine.LLAMA_SERVER_START_TIMEOUT
        ready = False
        while time.time() < deadline:
            rc = proc.poll()
            if rc is not None:
                raise RuntimeError(f"llama-server s'est arrêté au démarrage (code {rc}) :\n{_tail().strip()[-1200:]}")
            try:
                from urllib.request import Request
                req = Request(f"http://127.0.0.1:{port}/health",
                              headers={"User-Agent": "local-image-studio"})
                with engine._local_urlopen(req, 2) as r:
                    if r.status == 200:
                        ready = True
                        break
            except Exception:
                time.sleep(0.5)
        if not ready:
            raise RuntimeError(
                f"llama-server n'a pas chargé le modèle en {engine.LLAMA_SERVER_START_TIMEOUT}s — "
                "essayez un légendeur plus petit ou passez sur un GPU.")

        # Message utilisateur : texte (+ image unique si fournie)
        if image_abs is not None:
            user_content = [{"type": "image_url", "image_url": {"url": _image_data_url(image_abs)}},
                            {"type": "text", "text": user_text}]
        else:
            user_content = user_text
        body = json.dumps({
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user_content}],
            "max_tokens": int(max_tokens),
            "temperature": 0.7, "top_p": 0.8, "top_k": 20,
            "presence_penalty": 1.2,
            # les modèles « thinking » (Bonsai-2, Qwen3.5, Qwen3-VL…) réfléchissent avant de répondre ;
            # les autres ignorent ce paramètre
            "chat_template_kwargs": {"enable_thinking": True},
            "stream": False,
        }).encode("utf-8")
        from urllib.request import Request
        req = Request(f"http://127.0.0.1:{port}/v1/chat/completions", data=body,
                      headers={"Content-Type": "application/json",
                               "User-Agent": "local-image-studio"}, method="POST")
        try:
            with engine._local_urlopen(req, engine.LLAMA_CAPTION_TIMEOUT) as r:
                data = json.loads(r.read().decode("utf-8"))
        except Exception as e:
            raise RuntimeError(f"llama-server a refusé la requête thinking : {e}")

        choices = data.get("choices") or []
        content = ""
        reasoning = ""
        finish = None
        if choices:
            msg = (choices[0] or {}).get("message") or {}
            content = msg.get("content") or ""
            reasoning = msg.get("reasoning_content") or ""
            finish = choices[0].get("finish_reason")
        if not (content or "").strip():
            hint = f"finish_reason={finish}" if finish else "finish_reason inconnu"
            if reasoning:
                hint += f" — le modèle a épuisé son budget en réflexion ({len(reasoning)} caractères)"
            raise RuntimeError(f"Le modèle n'a pas produit de prompt exploitable ({hint}).")
        return content, reasoning, finish
    finally:
        try:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()
        except Exception:
            pass
        _untrack()


def _mtmd_chat(bin_path, model, mmproj, system, user_text, image_abs, max_tokens):
    """Chemin vision via llama-mtmd-cli (pas de texte pur possible)."""
    if image_abs is None:
        raise RuntimeError(
            "llama-server introuvable — le chemin texte pur exige llama-server "
            "(Modèles → « 📦 llama.cpp » → mise à jour) ; llama-mtmd-cli ne fait que de la vision.")
    prompt = system + "\n\nUser instruction (in the user's language):\n" + user_text
    cmd = engine.build_caption_command(bin_path, model, mmproj, str(image_abs), prompt, max_tokens)
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, errors="replace")
    except Exception as e:
        raise RuntimeError(f"Impossible de lancer {bin_path} : {e}")
    _track(proc)
    try:
        out, err = proc.communicate(timeout=engine.LLAMA_CAPTION_TIMEOUT)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except Exception:
            pass
        raise RuntimeError(
            f"Le modèle a dépassé {engine.LLAMA_CAPTION_TIMEOUT}s — essayez un légendeur "
            "plus petit (ex. Bonsai-2 4B) ou passez sur un GPU.")
    finally:
        _untrack()
    if proc.returncode != 0:
        tail = ((err or "") + "\n" + (out or "")).strip()[-1200:]
        raise RuntimeError(f"llama-mtmd-cli a échoué (code {proc.returncode}) :\n{tail}")
    # nettoie les lignes de log, garde le bloc <think> pour le découpage
    kept = [ln.rstrip() for ln in (out or "").splitlines()
            if ln.strip() and not engine._CAPTION_LOG_RE.match(ln.rstrip())]
    raw = "\n".join(kept)
    return raw, None, None


def _cpu_fallback(kind, text):
    """Dégradation honnête sans llama.cpp : Qwen3-4B via llama-cpp-python (CPU, sans raisonnement)."""
    import prompt_enhancer
    if kind == "translate":
        out = prompt_enhancer.translate_prompt(text)
    else:
        out = prompt_enhancer.enrich_prompt(text, mode="enrich")
    return out, "llama-cpp-python (CPU)"


# --------------------------------------------------------------------------- #
#  Point d'entrée principal
# --------------------------------------------------------------------------- #
def run_think(kind, text, image_rel=None, settings=None, max_tokens=None):
    """Exécute l'étape « thinking » et retourne un dict :
    {prompt, reasoning, model_id, model_name, backend, elapsed, degraded}."""
    kind = str(kind or "").strip().lower()
    if kind not in TASK_SYSTEMS:
        raise ValueError("Type d'étape thinking inconnu : " + kind)
    text = str(text or "").strip()
    if not text:
        raise ValueError("Décrivez d'abord ce que vous voulez faire (champ vide).")

    t0 = time.time()
    settings = settings or {}
    captioner_id = resolve_think_captioner_id(settings)
    if not captioner_id:
        from registry import captioners_ready
        ready = captioners_ready()
        if ready:
            captioner_id = ready[0]
    if not captioner_id:
        # dégradation CPU pour le texte uniquement
        if image_rel or kind == "edit":
            raise RuntimeError(
                "Aucun légendeur installé — l'édition avec « thinking » requiert un VLM "
                "(Modèles → « 🧠 Légendeurs d'image »).")
        try:
            out, backend = _cpu_fallback(kind, text)
        except Exception as e:
            raise RuntimeError(
                f"Aucun légendeur installé et l'enrichisseur CPU est indisponible : {e}")
        return {"prompt": out, "reasoning": "", "model_id": "qwen3_4b",
                "model_name": "Qwen3-4B (CPU, sans raisonnement)",
                "backend": backend, "elapsed": round(time.time() - t0, 1),
                "degraded": True}

    from registry import CAPTIONER_MODELS
    from registry import captioner_files

    model, mmproj = captioner_files(captioner_id)  # RuntimeError explicite si absent

    source, info = engine.llama_available()
    if not source:
        raise RuntimeError(
            "llama.cpp est introuvable (ni dans l'app ni sur cette machine). "
            "Installez-le dans la page Modèles → « 📦 llama.cpp ».")
    if captioner_id.startswith("bonsai2_"):
        ok, reason = engine._llama_version_status(engine._llama_bin_version((info or {}).get("path")))
        if not ok:
            raise RuntimeError(
                f"llama.cpp trop ancien pour Bonsai-2 : {reason}. "
                "Mettez à jour dans la page Modèles → « 📦 llama.cpp », ou choisissez "
                "un autre légendeur (ex. Qwen3.5 4B).")

    image_abs = _resolve_image(image_rel) if image_rel else None
    budget = int(max_tokens) if max_tokens else (TEXT_MAX_TOKENS if kind in ("translate", "enrich") else THINK_MAX_TOKENS)
    system = TASK_SYSTEMS[kind]
    model_name = (CAPTIONER_MODELS.get(captioner_id) or {}).get("name", captioner_id)

    kind_info = info.get("kind") if isinstance(info, dict) else None
    if kind_info == "server":
        content, server_reasoning, _finish = _server_chat(
            info["path"], model, mmproj, system, text, image_abs, budget)
        reasoning, final = split_think(content)
        if server_reasoning and not reasoning:
            reasoning = server_reasoning.strip()
        backend = ("app (llama.cpp)" if source == "app" else f"machine ({info.get('version') or '?'})") + " · llama-server"
    else:
        raw, _r, _f = _mtmd_chat(info["path"], model, mmproj, system, text, image_abs, budget)
        reasoning, final = split_think(raw)
        backend = ("app (llama.cpp)" if source == "app" else f"machine ({info.get('version') or '?'})") + " · llama-mtmd-cli"

    if not final:
        raise RuntimeError("Le modèle n'a pas produit de prompt exploitable — réessayez avec un modèle « thinking » plus petit (ex. Bonsai-2 4B).")

    return {"prompt": final, "reasoning": reasoning,
            "model_id": captioner_id, "model_name": model_name,
            "backend": backend, "elapsed": round(time.time() - t0, 1),
            "degraded": False}
