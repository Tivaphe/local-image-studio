# -*- coding: utf-8 -*-
"""
Metadonnees de generation dans les PNG (format WebUI / sdcpp).

Le moteur sd-cli ecrit deja un bloc de metadonnees (chunk tEXt « parameters »)
dans chaque PNG genere. Ce module :
  1. lit ces metadonnees (prompt, seed, modele…) pour restaurer un reglage ;
  2. pour les anciens PNG sans metadonnees (ou dont le moteur aurait ete
     desactive), injecte un bloc minimal apres coup a partir de l'historique —
     sans jamais modifier une image qui contient deja des metadonnees.

Format ecrit (identique a celui du moteur) :

    <prompt>
    Negative prompt: <negative>
    Steps: 28, Sampler: Euler, CFG scale: 4.0, Seed: 42, Size: 1024x1024, Model: flux-schnell, SDCPP: {json natif}

Necessite Pillow ; si Pillow est absent (installation legere), les deux
fonctions renvoient proprement un resultat « indisponible » au lieu de planter.
"""
import json
import re
from pathlib import Path

try:
    from PIL import Image
    from PIL.PngImagePlugin import PngInfo
    PIL_OK = True
except Exception:  # Pillow non installe -> fonction degradee
    PIL_OK = False

MAX_TEXT_LEN = 60000  # les chunks tEXt PNG supportent ~64 Ko : marge de securite


# --------------------------------------------------------------------------- #
#  Ecriture
# --------------------------------------------------------------------------- #
def build_webui_text(prompt="", negative="", steps=None, cfg=None, seed=None,
                     width=None, height=None, sampler=None, model_id=None,
                     native=None):
    """
    Construit la ligne de metadonnees au format WebUI, terminee par le JSON
    natif sd-cli (optionnel). Le jeu de cles volontairement limite permet au
    parseur ci-dessous de retrouver simplement chaque champ.
    """
    parts = []
    p = (prompt or "").strip()
    n = (negative or "").strip()
    if p:
        parts.append(p)
    if n:
        parts.append(f"Negative prompt: {n}")
    params = []
    if steps:
        params.append(f"Steps: {int(steps)}")
    if sampler:
        pretty = {"euler": "Euler"}.get(str(sampler), str(sampler))
        params.append(f"Sampler: {pretty}")
    if cfg is not None:
        try:
            params.append(f"CFG scale: {float(cfg):g}")
        except (TypeError, ValueError):
            pass
    if seed is not None:
        try:
            params.append(f"Seed: {int(seed)}")
        except (TypeError, ValueError):
            pass
    if width and height:
        params.append(f"Size: {int(width)}x{int(height)}")
    if model_id:
        params.append(f"Model: {model_id}")
    if isinstance(native, dict):
        try:
            params.append("SDCPP: " + json.dumps(native, ensure_ascii=False))
        except (TypeError, ValueError):
            pass
    if params:
        parts.append(", ".join(params))
    return "\n".join(parts)[:MAX_TEXT_LEN]


def embed_params(png_path: Path, text: str, only_if_missing: bool = True) -> bool:
    """
    Ecrit le chunk tEXt « parameters » dans un PNG existant.

    - Ne fait rien (False) si Pillow est absent, si le fichier n'est pas un
      PNG, ou si `only_if_missing` est vrai et que le bloc existe deja.
      Dans ce dernier cas l'image est verifiee puis ignoree sans reecriture.
    - Reecrit le fichier via un chemin temporaire (pas de corruption en cas
      d'erreur disque).
    """
    if not PIL_OK:
        return False
    try:
        with Image.open(png_path) as im:
            if (im.format or "") != "PNG":
                return False
            if only_if_missing and (im.text or {}).get("parameters"):
                return False
            im.load()
        pnginfo = PngInfo()
        pnginfo.add_text("parameters", text)
        tmp = png_path.with_suffix(png_path.suffix + ".meta-tmp")
        im.save(tmp, format="PNG", pnginfo=pnginfo)
        tmp.replace(png_path)
        return True
    except Exception:
        return False


# --------------------------------------------------------------------------- #
#  Lecture
# --------------------------------------------------------------------------- #
_SIZE_RE = re.compile(r"\bSize:\s*(\d+)\s*x\s*(\d+)", re.I)
_CFG_RE = re.compile(r"\bCFG\s*scale:\s*([0-9]+(?:\.[0-9]+)?)", re.I)
_STEPS_RE = re.compile(r"\bSteps:\s*(\d+)", re.I)
_SEED_RE = re.compile(r"\bSeed:\s*(-?\d+)", re.I)
_SAMPLER_RE = re.compile(r"\bSampler:\s*([^,\n]+)", re.I)
_MODEL_RE = re.compile(r"\bModel:\s*([^,\n]+)", re.I)


def read_params(source):
    """
    Lit les metadonnees d'un PNG. `source` = chemin (str/Path) ou flux binaire
    (io.BytesIO). Renvoie None si rien de lisible, sinon :
      {prompt, negative, steps, cfg, seed, width, height, model, native, raw}
    « native » contient le JSON sdcpp brut quand il est present.
    """
    if not PIL_OK:
        return None
    try:
        with Image.open(source) as im:
            text = (getattr(im, "text", None) or {}).get("parameters")
        if not text:
            return None
        return parse_parameters_text(text)
    except Exception:
        return None


def parse_parameters_text(text: str):
    """Analyse le contenu du chunk « parameters » (tolerant aux variantes)."""
    if not text:
        return None
    raw = text[:MAX_TEXT_LEN]
    native = None
    m = re.search(r",\s*SDCPP:\s*(\{.*\})\s*$", raw, re.S)
    if m:
        try:
            native = json.loads(m.group(1))
        except Exception:
            native = None
        raw_body = raw[: m.start()]
    else:
        raw_body = raw

    lines = raw_body.split("\n")
    negative = ""
    if len(lines) > 1 and lines[1].lower().startswith("negative prompt:"):
        negative = lines[1].split(":", 1)[1].strip()
        prompt = lines[0].strip()
        params_line = "\n".join(lines[2:])
    else:
        # Derniere ligne = parametres si elle contient « Steps: », sinon prompt long
        tail = lines[-1]
        if _STEPS_RE.search(tail) or _SIZE_RE.search(tail):
            params_line = tail
            prompt = "\n".join(lines[:-1]).strip()
        else:
            params_line = ""
            prompt = raw_body.strip()

    out = {
        "prompt": prompt,
        "negative": negative,
        "steps": None, "cfg": None, "seed": None,
        "width": None, "height": None,
        "sampler": None, "model": None,
        "native": native,
        "raw": text[:MAX_TEXT_LEN],
    }
    m = _STEPS_RE.search(params_line)
    if m:
        out["steps"] = int(m.group(1))
    m = _CFG_RE.search(params_line)
    if m:
        out["cfg"] = float(m.group(1))
    m = _SEED_RE.search(params_line)
    if m:
        out["seed"] = int(m.group(1))
    m = _SIZE_RE.search(params_line)
    if m:
        out["width"], out["height"] = int(m.group(1)), int(m.group(2))
    m = _SAMPLER_RE.search(params_line)
    if m:
        out["sampler"] = m.group(1).strip()
    m = _MODEL_RE.search(params_line)
    if m:
        out["model"] = m.group(1).strip()

    if not out["prompt"] and native is None:
        return None
    return out


# --------------------------------------------------------------------------- #
#  Conversion pratique vers le formulaire de generation
# --------------------------------------------------------------------------- #
def to_form_settings(meta: dict, models: dict):
    """
    Transforme les metadonnees lues en un dictionnaire directement injectable
    dans le formulaire « Generer » (front-end). Les champs absents sont omis.
    """
    if not meta:
        return {}
    out = {}
    if meta.get("prompt"):
        out["prompt"] = meta["prompt"]
    if meta.get("negative"):
        out["negative"] = meta["negative"]
    for key in ("width", "height", "steps", "cfg", "seed"):
        if meta.get(key) is not None:
            out[key] = meta[key]
    # Modele : on prefere l'identifiant exact, sinon on tente le nom affiche
    model_token = (meta.get("model") or "").strip()
    if model_token:
        if model_token in models:
            out["model"] = model_token
        else:
            low = model_token.lower()
            for mid, m in models.items():
                if m.get("name", "").lower() == low or mid.lower() == low:
                    out["model"] = mid
                    break
            else:
                # nom de fichier type flux1-schnell (sd-cli stocke le nom)
                for mid, m in models.items():
                    fnames = {f.rsplit(".", 1)[0] for f in (m.get("file_for_quant") or {}).values()}
                    if model_token in fnames:
                        out["model"] = mid
                        break
    sampler = (meta.get("sampler") or "").strip()
    if sampler:
        out["sampler_name"] = sampler
        out["sampler"] = {"euler": "euler"}.get(sampler.lower().replace(" ", "_").lower(), None) or \
            sampler.lower().replace(" ", "_")
    native = meta.get("native")
    if isinstance(native, dict):
        out["native"] = native
        try:
            sp = native.get("sample_params") or {}
            if sp.get("sampler"):
                out["sampler"] = sp["sampler"]
            if sp.get("scheduler"):
                out["scheduler"] = sp["scheduler"]
            if sp.get("steps"):
                out["steps"] = out.get("steps") or int(sp["steps"])
            if sp.get("guidance") is not None:
                out["cfg"] = out.get("cfg") or float(sp["guidance"])
        except Exception:
            pass
    return out
