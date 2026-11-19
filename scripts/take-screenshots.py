#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Génère les captures d'écran de l'interface dans ``docs/screenshots/``.

Pourquoi un script ? Les captures ne sont pas versionnées depuis l'environnement
de développement ; lancez-le une fois sur VOTRE machine (avec un navigateur) —
les images sont écrites prêtes à être commitées (JPG, ~1500 px de large).

Prérequis (une seule fois) :
    pip install playwright
    playwright install chromium

Utilisation :
    # 1) lancer l'app (autre terminal) :
    python3 app.py --no-browser
    # 2) capturer :
    python3 scripts/take-screenshots.py
    # ou avec un port/URL :
    python3 scripts/take-screenshots.py --url http://127.0.0.1:7860

Ensuite, commitez : ``git add docs/screenshots && git commit``.
"""
import argparse
import sys
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "screenshots"

# (route, thème, fichier)
SHOTS = [
    ("/generate", "dark",  "generate-dark.jpg"),
    ("/generate", "light", "generate-light.jpg"),
    ("/edit",     "dark",  "edit-dark.jpg"),
    ("/history",  "dark",  "history-dark.jpg"),
    ("/models",   "dark",  "models-dark.jpg"),
    ("/settings", "light", "settings-light.jpg"),
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:7860", help="Racine de l'app (défaut: %(default)s)")
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("❌ playwright n'est pas installé. Lancez d'abord :\n"
              "   pip install playwright && playwright install chromium", file=sys.stderr)
        return 2

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1500, "height": 950}, device_scale_factor=1)
        for route, theme, name in SHOTS:
            # poser le thème AVANT le premier rendu (le script inline de base.html le lit)
            page.goto(args.url + "/settings", wait_until="domcontentloaded")
            page.evaluate("t => localStorage.setItem('lis-theme', t)", theme)
            page.goto(args.url + route, wait_until="networkidle")
            page.wait_for_timeout(2500)  # laisse les fetch /api/... se terminer
            target = OUT_DIR / name
            page.screenshot(path=str(target), type="jpeg", quality=88, full_page=True)
            print(f"✓ {target}")
        browser.close()
    print("\nTerminé. Images dans docs/screenshots/ — commitez-les puis vérifiez le README.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
