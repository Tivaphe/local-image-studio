# -*- coding: utf-8 -*-
"""
Utilitaires image : lecture des dimensions d'un fichier + resolution du format
de sortie pour l'img2img / edition.

Le projet veut rester installable sans compilateur (pas de Pillow obligatoire) :
les dimensions sont donc lues directement dans l'en-tete des fichiers
(PNG / JPEG / WEBP, + GIF et BMP en bonus). Pillow est utilise en secours s'il
est deja installe.
"""
import struct
from pathlib import Path

import config
from registry import (RATIOS, SOURCE_DEFAULT_MODE, SOURCE_MODES, SOURCE_RATIO,
                      clamp_user_size, ratio_label, source_size_options)

# Taille max lue pour trouver l'en-tete (les metadonnees EXIF peuvent etre
# volumineuses sur les JPEG de telephone).
_MAX_SCAN_BYTES = 32 * 1024 * 1024


# --------------------------------------------------------------------------- #
#  Lecture des dimensions (pur Python, sans dependance)
# --------------------------------------------------------------------------- #
def _png_size(f):
    head = f.read(33)
    if len(head) < 33 or not head.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    if head[12:16] != b"IHDR":
        return None
    w, h = struct.unpack(">II", head[16:24])
    return (w, h) if w and h else None


def _jpeg_size(f):
    if f.read(2) != b"\xff\xd8":
        return None
    # marqueurs SOFn (0xC0..0xCF sauf C4/C8/CC) : precision + hauteur + largeur
    while f.tell() < _MAX_SCAN_BYTES:
        b = f.read(1)
        if not b:
            return None
        if b != b"\xff":
            continue
        # les 0xFF de remplissage se suivent parfois
        marker = f.read(1)
        while marker == b"\xff":
            marker = f.read(1)
        if not marker:
            return None
        m = marker[0]
        if m == 0xD8 or m == 0xD9 or m == 0x01 or 0xD0 <= m <= 0xD7:
            continue                      # marqueurs sans payload
        length_raw = f.read(2)
        if len(length_raw) < 2:
            return None
        length = struct.unpack(">H", length_raw)[0]
        if m == 0xDA:                     # debut des donnees : on arrete
            return None
        if 0xC0 <= m <= 0xCF and m not in (0xC4, 0xC8, 0xCC):
            payload = f.read(max(0, length - 2))
            if len(payload) < 5:
                return None
            h, w = struct.unpack(">HH", payload[1:5])
            return (w, h) if w and h else None
        f.seek(max(0, length - 2), 1)     # saute le marqueur
    return None


def _webp_size(f):
    head = f.read(30)
    if len(head) < 30 or head[:4] != b"RIFF" or head[8:12] != b"WEBP":
        return None
    fourcc = head[12:16]
    body = head[20:30]
    if fourcc == b"VP8 " and len(body) >= 10:
        # perte : code de demarrage 9D 01 2A puis largeur/hauteur sur 14 bits
        if body[3:6] != b"\x9d\x01\x2a":
            return None
        w, h = struct.unpack("<HH", body[6:10])
        return (w & 0x3FFF, h & 0x3FFF)
    if fourcc == b"VP8L" and len(body) >= 5:
        # sans perte : signature 0x2F puis 14 bits largeur-1, 14 bits hauteur-1
        if body[0] != 0x2F:
            return None
        b1, b2, b3, b4 = body[1], body[2], body[3], body[4]
        w = 1 + (((b2 & 0x3F) << 8) | b1)
        h = 1 + (((b4 & 0x0F) << 10) | (b3 << 2) | ((b2 & 0xC0) >> 6))
        return (w, h)
    if fourcc == b"VP8X" and len(body) >= 10:
        # etendu : canvas width-1 / height-1 sur 3 octets little-endian
        w = 1 + (body[4] | (body[5] << 8) | (body[6] << 16))
        h = 1 + (body[7] | (body[8] << 8) | (body[9] << 16))
        return (w, h)
    return None


def _gif_size(f):
    head = f.read(10)
    if len(head) < 10 or head[:6] not in (b"GIF87a", b"GIF89a"):
        return None
    w, h = struct.unpack("<HH", head[6:10])
    return (w, h) if w and h else None


def _bmp_size(f):
    head = f.read(26)
    if len(head) < 26 or head[:2] != b"BM":
        return None
    w, h = struct.unpack("<ii", head[18:26])
    return (w, abs(h)) if w and h else None


_PARSERS = (_png_size, _jpeg_size, _webp_size, _gif_size, _bmp_size)


def read_image_size(path):
    """Retourne (largeur, hauteur) d'un fichier image, ou None si illisible."""
    if not path:
        return None
    try:
        p = Path(path)
    except (TypeError, ValueError):
        return None
    if not p.exists() or not p.is_file():
        return None
    try:
        with open(p, "rb") as f:
            for parse in _PARSERS:
                f.seek(0)
                try:
                    size = parse(f)
                except Exception:
                    size = None
                if size and size[0] > 0 and size[1] > 0:
                    return (int(size[0]), int(size[1]))
    except Exception:
        return None
    # secours : Pillow (s'il est installe)
    try:
        from PIL import Image
        with Image.open(p) as im:
            return (int(im.width), int(im.height))
    except Exception:
        return None


def safe_source_path(rel):
    """Valide un chemin d'image source (relatif au projet) -> Path absolue.

    Empeche toute sortie du dossier source_images/ (path traversal).
    Retourne None si le chemin est invalide ou si le fichier est absent.
    """
    if not rel:
        return None
    raw = str(rel).replace("\\", "/").strip()
    if raw.startswith("/") or ".." in raw.split("/"):
        return None
    base = config.SOURCE_IMAGES_DIR.resolve()
    try:
        p = (config.ROOT / raw).resolve()
        p.relative_to(base)
    except Exception:
        return None
    return p if p.is_file() else None


# --------------------------------------------------------------------------- #
#  Resolution du format de sortie
# --------------------------------------------------------------------------- #
def resolve_output_size(ratio=None, source_image=None, size_mode=None,
                        width=None, height=None):
    """Determine la taille (largeur, hauteur) a envoyer au moteur.

    Trois cas :
      1. width/height explicites  -> format libre (aligne sur 16, borne)
      2. ratio == "source"        -> on garde le format de l'image uploadee
      3. sinon                    -> un des presets RATIOS

    Retourne (width, height, info) ; leve ValueError avec un message utilisateur
    quand la taille ne peut pas etre determinee.
    """
    # 1) taille libre fournie par le client
    try:
        if width and height:
            w, h = clamp_user_size(int(width), int(height))
            return w, h, {"mode": "custom", "ratio": ratio_label(w, h),
                          "width": w, "height": h}
    except (TypeError, ValueError):
        raise ValueError("Largeur/hauteur invalides.")

    # 2) format de l'image source
    if ratio == SOURCE_RATIO:
        if not source_image:
            raise ValueError(
                "Le format « image source » demande une image : uploadez-en une "
                "dans « Image source (img2img / édition) ».")
        src = safe_source_path(source_image)
        if not src:
            raise ValueError("Image source introuvable (fichier supprimé ?). "
                             "Uploadez-la à nouveau.")
        dims = read_image_size(src)
        if not dims:
            raise ValueError("Impossible de lire les dimensions de l'image "
                             "source. Utilisez un PNG, JPG ou WEBP valide.")
        mode = size_mode if size_mode in SOURCE_MODES else SOURCE_DEFAULT_MODE
        opts = source_size_options(dims[0], dims[1])
        fit = opts[mode]
        info = {"mode": "source", "size_mode": mode,
                "source_width": dims[0], "source_height": dims[1],
                "source_ratio": opts["ratio"],
                "ratio": ratio_label(fit["width"], fit["height"]),
                "width": fit["width"], "height": fit["height"],
                "downscaled": fit["downscaled"], "upscaled": fit["upscaled"],
                "source": src.name}
        return fit["width"], fit["height"], info

    # 3) preset de ratio
    if ratio not in RATIOS:
        raise ValueError(f"Format inconnu : {ratio}")
    w, h = RATIOS[ratio]
    return w, h, {"mode": "preset", "ratio": ratio, "width": w, "height": h}
