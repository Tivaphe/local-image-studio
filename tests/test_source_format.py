# -*- coding: utf-8 -*-
"""
Tests du format de sortie : presets de ratio, format « image source »
(on garde le cadrage du fichier uploade) et format libre.

Lancement :  python -m unittest discover -s tests -v
Aucune dependance obligatoire (Pillow est utilise seulement pour fabriquer les
images de test ; sans lui, un PNG minimal est construit a la main).
"""
import io
import json
import struct
import sys
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config                      # noqa: E402
import image_utils                 # noqa: E402
import registry                    # noqa: E402
from registry import (RATIOS, SOURCE_MAX_SIDE, SOURCE_MIN_SIDE, SOURCE_MODES,  # noqa: E402
                      SOURCE_RATIO, clamp_user_size, ratio_label,
                      source_size_options, source_target_size)

try:
    from PIL import Image
    HAS_PIL = True
except Exception:
    HAS_PIL = False


# --------------------------------------------------------------------------- #
#  Fabrique d'images de test
# --------------------------------------------------------------------------- #
def _handmade_png(w, h):
    """PNG minimal valide (sans Pillow)."""
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\x80\x40\x20" * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) +
            chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def make_image(path, w, h, fmt="PNG"):
    path = Path(path)
    if HAS_PIL and fmt != "PNG-RAW":
        Image.new("RGB", (w, h), (120, 80, 200)).save(str(path), fmt)
    else:
        path.write_bytes(_handmade_png(w, h))
    return path


class TempDirCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(config.SOURCE_IMAGES_DIR) / "_tests"
        self.tmp.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        for f in self.tmp.iterdir():
            try:
                f.unlink()
            except Exception:
                pass
        try:
            self.tmp.rmdir()
        except Exception:
            pass


# --------------------------------------------------------------------------- #
#  Lecture des dimensions
# --------------------------------------------------------------------------- #
class TestReadImageSize(TempDirCase):
    def test_png_sans_pillow(self):
        p = make_image(self.tmp / "a.png", 640, 480, "PNG-RAW")
        self.assertEqual(image_utils.read_image_size(p), (640, 480))

    @unittest.skipUnless(HAS_PIL, "Pillow requis pour fabriquer les fixtures")
    def test_tous_formats(self):
        cases = [("png", "PNG"), ("jpg", "JPEG"), ("webp", "WEBP"),
                 ("gif", "GIF"), ("bmp", "BMP")]
        for (w, h) in [(1920, 1080), (800, 600), (512, 512), (300, 900)]:
            for ext, fmt in cases:
                p = make_image(self.tmp / f"t_{w}x{h}.{ext}", w, h, fmt)
                self.assertEqual(image_utils.read_image_size(p), (w, h),
                                 f"{fmt} {w}x{h}")

    @unittest.skipUnless(HAS_PIL, "Pillow requis")
    def test_webp_lossless_et_alpha(self):
        for w, h in [(1234, 567), (64, 2048)]:
            im = Image.new("RGBA", (w, h), (10, 200, 90, 128))
            p1 = self.tmp / f"ll_{w}.webp"
            im.save(str(p1), "WEBP", lossless=True)
            p2 = self.tmp / f"al_{w}.webp"
            im.save(str(p2), "WEBP")
            self.assertEqual(image_utils.read_image_size(p1), (w, h))
            self.assertEqual(image_utils.read_image_size(p2), (w, h))

    def test_fichiers_invalides(self):
        fake = self.tmp / "fake.png"
        fake.write_bytes(b"pas une image")
        self.assertIsNone(image_utils.read_image_size(fake))
        empty = self.tmp / "empty.jpg"
        empty.write_bytes(b"")
        self.assertIsNone(image_utils.read_image_size(empty))
        self.assertIsNone(image_utils.read_image_size(self.tmp / "absent.png"))
        self.assertIsNone(image_utils.read_image_size(None))


# --------------------------------------------------------------------------- #
#  Securite du chemin d'image source
# --------------------------------------------------------------------------- #
class TestSafeSourcePath(TempDirCase):
    def test_chemin_valide(self):
        p = make_image(self.tmp / "ok.png", 64, 64, "PNG-RAW")
        rel = p.relative_to(config.ROOT).as_posix()
        self.assertEqual(image_utils.safe_source_path(rel), p.resolve())

    def test_traversal_refuse(self):
        for bad in ["../app.py", "source_images/../../app.py", "/etc/passwd",
                    "..\\app.py", "app.py", "", None, "source_images/absent.png"]:
            self.assertIsNone(image_utils.safe_source_path(bad), f"{bad!r} accepté à tort")


# --------------------------------------------------------------------------- #
#  Calcul de la taille « format image source »
# --------------------------------------------------------------------------- #
class TestSourceTargetSize(unittest.TestCase):
    SAMPLES = [(1920, 1080), (4000, 3000), (512, 512), (3000, 4000),
               (800, 600), (1080, 1920), (1000, 1500), (1366, 768),
               (2500, 2500), (300, 300), (6000, 200), (1, 1), (4032, 3024)]

    def test_multiple_de_16_et_bornes(self):
        for mode in SOURCE_MODES:
            for w, h in self.SAMPLES:
                nw, nh, _ = source_target_size(w, h, mode)
                self.assertEqual(nw % 16, 0, f"{w}x{h} {mode} largeur")
                self.assertEqual(nh % 16, 0, f"{w}x{h} {mode} hauteur")
                self.assertLessEqual(max(nw, nh), SOURCE_MAX_SIDE)
                self.assertGreaterEqual(min(nw, nh), 16)

    def test_cadrage_conserve(self):
        """Le ratio de sortie reste proche de celui du fichier (< 3 %)."""
        for mode in SOURCE_MODES:
            for w, h in self.SAMPLES:
                if w / h > 20 or h / w > 20:
                    continue          # ratios extremes : bornes prioritaires
                nw, nh, _ = source_target_size(w, h, mode)
                self.assertAlmostEqual(nw / nh, w / h, delta=0.03 * (w / h),
                                       msg=f"{w}x{h} {mode} -> {nw}x{nh}")

    def test_exact_conserve_la_taille(self):
        # deja multiple de 16 et sous le plafond -> inchangé
        self.assertEqual(source_target_size(1024, 1024, "exact")[:2], (1024, 1024))
        self.assertEqual(source_target_size(1920, 1088, "exact")[:2], (1920, 1088))
        self.assertEqual(source_target_size(640, 480, "exact")[:2], (640, 480))

    def test_exact_plafonne_les_tres_grandes_images(self):
        nw, nh, down = source_target_size(6000, 4000, "exact")
        self.assertTrue(down)
        self.assertLessEqual(nw * nh, registry.SOURCE_MAX_PIXELS + 16 * SOURCE_MAX_SIDE)
        self.assertLessEqual(max(nw, nh), SOURCE_MAX_SIDE)

    def test_adapte_vise_un_megapixel(self):
        for w, h in [(4000, 3000), (1920, 1080), (8000, 2000)]:
            nw, nh, _ = source_target_size(w, h, "adapted")
            self.assertLessEqual(nw * nh, registry.SOURCE_TARGET_PIXELS * 1.15)
        # une petite image est agrandie vers ~1 Mpx
        nw, nh, down = source_target_size(320, 240, "adapted")
        self.assertFalse(down)
        self.assertGreater(nw * nh, 512 * 512)

    def test_options_pour_l_interface(self):
        opts = source_size_options(1920, 1080)
        self.assertEqual(opts["ratio"], "16:9")
        self.assertEqual(opts["megapixels"], 2.07)
        self.assertEqual(set(opts) & set(SOURCE_MODES), set(SOURCE_MODES))
        for mode in SOURCE_MODES:
            self.assertIn("width", opts[mode])
            self.assertIn("height", opts[mode])
            self.assertIn("downscaled", opts[mode])
        self.assertEqual(source_size_options(1366, 768)["ratio"], "1.78:1")

    def test_ratio_label(self):
        self.assertEqual(ratio_label(1920, 1080), "16:9")
        self.assertEqual(ratio_label(1080, 1920), "9:16")
        self.assertEqual(ratio_label(1024, 1024), "1:1")
        self.assertEqual(ratio_label(4032, 3024), "4:3")
        self.assertEqual(ratio_label(1366, 768), "1.78:1")


# --------------------------------------------------------------------------- #
#  Format libre
# --------------------------------------------------------------------------- #
class TestClampUserSize(unittest.TestCase):
    def test_aligne_sur_16(self):
        self.assertEqual(clamp_user_size(1366, 768), (1360, 768))
        self.assertEqual(clamp_user_size(1000, 1000)[0] % 16, 0)

    def test_bornes(self):
        self.assertEqual(clamp_user_size(10, 10), (256, 256))
        w, h = clamp_user_size(9000, 9000)
        self.assertLessEqual(max(w, h), SOURCE_MAX_SIDE)

    def test_ratio_conserve_pour_les_petites_valeurs(self):
        # 2:1 trop petit -> agrandi en gardant le cadrage
        w, h = clamp_user_size(200, 100)
        self.assertAlmostEqual(w / h, 2.0, delta=0.1)
        self.assertGreaterEqual(min(w, h), SOURCE_MIN_SIDE)

    def test_invalide(self):
        for bad in [(0, 100), (100, 0), (-5, 100)]:
            with self.assertRaises(ValueError):
                clamp_user_size(*bad)


# --------------------------------------------------------------------------- #
#  Resolution complete (presets / image / libre)
# --------------------------------------------------------------------------- #
class TestResolveOutputSize(TempDirCase):
    def test_presets(self):
        for name, (w, h) in RATIOS.items():
            gw, gh, info = image_utils.resolve_output_size(ratio=name)
            self.assertEqual((gw, gh), (w, h))
            self.assertEqual(info["mode"], "preset")

    def test_ratio_inconnu(self):
        with self.assertRaises(ValueError):
            image_utils.resolve_output_size(ratio="21:9")

    def test_libre(self):
        w, h, info = image_utils.resolve_output_size(ratio="1:1", width=1500, height=1000)
        self.assertEqual(info["mode"], "custom")
        self.assertEqual(w % 16, 0)
        self.assertAlmostEqual(w / h, 1.5, delta=0.05)

    def test_source_sans_image(self):
        with self.assertRaises(ValueError) as ctx:
            image_utils.resolve_output_size(ratio=SOURCE_RATIO, source_image=None)
        self.assertIn("uploadez", str(ctx.exception).lower())

    def test_source_image_absente(self):
        with self.assertRaises(ValueError):
            image_utils.resolve_output_size(
                ratio=SOURCE_RATIO, source_image="source_images/absent.png")

    def test_source_traversal_refuse(self):
        with self.assertRaises(ValueError):
            image_utils.resolve_output_size(ratio=SOURCE_RATIO, source_image="../app.py")

    def test_source_adapte_et_exact(self):
        p = make_image(self.tmp / "photo.png", 1920, 1080, "PNG-RAW")
        rel = p.relative_to(config.ROOT).as_posix()

        w, h, info = image_utils.resolve_output_size(ratio=SOURCE_RATIO, source_image=rel)
        self.assertEqual(info["mode"], "source")
        self.assertEqual(info["size_mode"], "adapted")
        self.assertEqual((info["source_width"], info["source_height"]), (1920, 1080))
        self.assertEqual(info["source_ratio"], "16:9")
        self.assertEqual((w, h), (info["width"], info["height"]))
        self.assertAlmostEqual(w / h, 16 / 9, delta=0.05)

        w2, h2, info2 = image_utils.resolve_output_size(
            ratio=SOURCE_RATIO, source_image=rel, size_mode="exact")
        self.assertEqual(info2["size_mode"], "exact")
        self.assertGreater(w2 * h2, w * h)          # taille exacte > adaptée
        self.assertAlmostEqual(w2 / h2, 16 / 9, delta=0.05)

    def test_source_mode_inconnu_replie(self):
        p = make_image(self.tmp / "photo2.png", 800, 600, "PNG-RAW")
        rel = p.relative_to(config.ROOT).as_posix()
        _, _, info = image_utils.resolve_output_size(
            ratio=SOURCE_RATIO, source_image=rel, size_mode="nimporte")
        self.assertEqual(info["size_mode"], "adapted")

    def test_source_fichier_illisible(self):
        bad = self.tmp / "casse.png"
        bad.write_bytes(b"pas une image du tout")
        rel = bad.relative_to(config.ROOT).as_posix()
        with self.assertRaises(ValueError):
            image_utils.resolve_output_size(ratio=SOURCE_RATIO, source_image=rel)


# --------------------------------------------------------------------------- #
#  API Flask (sans lancer de generation)
# --------------------------------------------------------------------------- #
class TestApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import app as app_module
        except Exception as e:            # Flask absent -> on saute ce volet
            raise unittest.SkipTest(f"Flask indisponible : {e}")
        app_module.app.config["TESTING"] = True
        cls.client = app_module.app.test_client()
        cls.app_module = app_module

    def test_page_generer_expose_les_modes(self):
        r = self.client.get("/generate")
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        self.assertIn("window.SOURCE_RATIO", html)
        self.assertIn("window.SOURCE_MODES", html)
        self.assertIn("source-size-box", html)
        self.assertIn("custom-size-box", html)
        for mode in SOURCE_MODES:
            self.assertIn(json.dumps(mode), html)

    def test_upload_renvoie_les_dimensions(self):
        data = _handmade_png(1920, 1080)
        r = self.client.post("/api/upload-source-image",
                             data={"image": (io.BytesIO(data), "photo.png")},
                             content_type="multipart/form-data")
        self.assertEqual(r.status_code, 200)
        j = r.get_json()
        self.assertTrue(j["ok"])
        self.assertEqual((j["width"], j["height"]), (1920, 1080))
        self.assertEqual(j["ratio"], "16:9")
        self.assertEqual(set(j["sizes"]), set(SOURCE_MODES))
        self.assertEqual(j["sizes"]["exact"]["width"], 1920)
        self.assertTrue(j["filename"].startswith("source_images/"))
        # l'aperçu est servi
        r2 = self.client.get(j["url"])
        self.assertEqual(r2.status_code, 200)
        # et le recalcul a la demande fonctionne
        r3 = self.client.post("/api/source-size",
                              json={"source_image": j["filename"], "size_mode": "exact"})
        self.assertEqual(r3.status_code, 200)
        self.assertEqual(r3.get_json()["target"]["width"], 1920)
        # nettoyage
        (config.ROOT / j["filename"]).unlink(missing_ok=True)

    def test_upload_fichier_invalide(self):
        r = self.client.post("/api/upload-source-image",
                             data={"image": (io.BytesIO(b"niark"), "virus.png")},
                             content_type="multipart/form-data")
        self.assertEqual(r.status_code, 400)
        self.assertIn("illisible", r.get_json()["error"])

    def test_upload_extension_refusee(self):
        r = self.client.post("/api/upload-source-image",
                             data={"image": (io.BytesIO(b"x"), "note.txt")},
                             content_type="multipart/form-data")
        self.assertEqual(r.status_code, 400)

    def test_generate_erreurs_avant_lancement(self):
        mid = next(iter(registry.MODELS))
        # prompt vide
        r = self.client.post("/api/generate", json={"model_id": mid, "prompt": "  "})
        self.assertEqual(r.status_code, 400)
        # format « image » sans image uploadee
        r = self.client.post("/api/generate", json={
            "model_id": mid, "prompt": "hello", "ratio": SOURCE_RATIO})
        self.assertEqual(r.status_code, 400)
        self.assertIn("image", r.get_json()["error"].lower())
        # ratio inconnu
        r = self.client.post("/api/generate", json={
            "model_id": mid, "prompt": "hello", "ratio": "21:9"})
        self.assertEqual(r.status_code, 400)
        # modele inconnu
        r = self.client.post("/api/generate", json={"model_id": "nope", "prompt": "x"})
        self.assertEqual(r.status_code, 400)

    def test_generate_traversal_refuse(self):
        mid = next(iter(registry.MODELS))
        r = self.client.post("/api/generate", json={
            "model_id": mid, "prompt": "hello",
            "ratio": SOURCE_RATIO, "source_image": "../app.py"})
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main(verbosity=2)
