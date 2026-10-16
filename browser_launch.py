# -*- coding: utf-8 -*-
"""
Ouverture automatique de l'interface dans le navigateur au démarrage du serveur.

- **Chrome est privilégié** (chemins connus sous Windows / macOS / Linux), avec repli
  sur le navigateur par défaut du système si Chrome n'est pas installé.
- L'attente puis l'ouverture se font dans un **thread** : le serveur Flask démarre
  immédiatement, le navigateur arrive dès que le port écoute.
- Désactivable de trois façons :
    1. option de ligne de commande `python app.py --no-browser`
    2. variable d'environnement `LIS_NO_BROWSER=1`
    3. réglage `"open_browser": false` dans `settings.json` (case dans Paramètres)
- Sur une machine sans écran (serveur, conteneur), l'ouverture est ignorée
  automatiquement : rien ne casse.
"""
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser

__all__ = ["find_chrome", "open_url", "schedule_open", "browser_disabled"]

# Noms usuels de l'exécutable Chrome (Windows) et (Linux)
_CHROME_WIN_NAMES = ("chrome.exe",)
_CHROME_UNIX_NAMES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser")


def _windows_chrome_paths():
    """Chemins d'installation classiques de Chrome sous Windows + registre « App Paths »."""
    paths = []
    for env in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        root = os.environ.get(env)
        if root:
            paths.append(os.path.join(root, "Google", "Chrome", "Application", "chrome.exe"))
    # Chrome Beta / Canary : utiles si seule une de ces versions est installée
    for env in ("ProgramFiles", "LOCALAPPDATA"):
        root = os.environ.get(env)
        if root:
            paths.append(os.path.join(root, "Google", "Chrome Beta", "Application", "chrome.exe"))
            paths.append(os.path.join(root, "Google", "Chrome SxS", "Application", "chrome.exe"))
    # Clé officielle « App Paths » (couvre les installations personnalisées)
    try:
        import winreg  # noqa: WPS433 (Windows uniquement)
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(
                    hive,
                    r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe",
                ) as key:
                    value = winreg.QueryValue(key, None)
                    if value:
                        paths.append(value)
            except OSError:
                continue
    except Exception:
        pass
    return paths


def find_chrome():
    """Retourne le chemin de Chrome si trouvé, sinon None."""
    if os.name == "nt":
        for name in _CHROME_WIN_NAMES:
            found = shutil.which(name)
            if found:
                return found
        for path in _windows_chrome_paths():
            if path and os.path.isfile(path):
                return path
        return None

    if sys.platform == "darwin":
        app = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        return app if os.path.isfile(app) else None

    for name in _CHROME_UNIX_NAMES:
        found = shutil.which(name)
        if found:
            return found
    return None


def _has_display():
    """False sur une machine sans écran (serveur / conteneur) : inutile d'ouvrir un onglet."""
    if os.name == "nt" or sys.platform == "darwin":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def browser_disabled():
    """Vrai si l'ouverture automatique est désactivée par variable d'environnement."""
    value = os.environ.get("LIS_NO_BROWSER", "").strip().lower()
    return value not in ("", "0", "false", "no")


def open_url(url, prefer_chrome=True):
    """
    Ouvre `url` dans Chrome si possible, sinon dans le navigateur par défaut.
    Retourne "chrome", "default", "headless" ou "none" (échec).
    """
    if not _has_display():
        return "headless"

    if prefer_chrome:
        chrome = find_chrome()
        if chrome:
            try:
                # --new-window : une fenêtre dédiée à l'app même si Chrome est déjà ouvert.
                subprocess.Popen(
                    [chrome, "--new-window", url],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return "chrome"
            except OSError:
                pass  # Chrome trouvé mais illançable -> on tente le navigateur par défaut
    try:
        if webbrowser.open(url):
            return "default"
    except Exception:
        pass
    return "none"


def _wait_for_port(host, port, timeout=30.0):
    """Attend que le port accepte une connexion TCP. Retourne True si le serveur répond."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.25)
    return False


def schedule_open(url, host="127.0.0.1", port=7860, timeout=30.0, prefer_chrome=True,
                  on_done=None):
    """
    Ouvre `url` dès que `host:port` écoute (thread daemon : n'empêche pas l'arrêt du serveur).
    `on_done(resultat)` est appelé avec "chrome" / "default" / "headless" / "none".
    """

    def worker():
        if not _wait_for_port(host, port, timeout):
            result = "none"
        else:
            time.sleep(0.3)  # laisse Flask finir d'enregistrer les routes
            result = open_url(url, prefer_chrome=prefer_chrome)
        if on_done:
            try:
                on_done(result)
            except Exception:
                pass

    thread = threading.Thread(target=worker, name="open-browser", daemon=True)
    thread.start()
    return thread
