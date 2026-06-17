@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1
cd /d "%~dp0"

echo ============================================
echo   Local Image Studio - Lanceur
echo ============================================
echo.

REM ==========================================================
REM  0) Detection de Python 3 (plusieurs methodes)
REM ==========================================================
set "PYEXE="

REM a) Environnement virtuel deja existant ?
if exist ".venv\Scripts\python.exe" (
    set "PYEXE=.venv\Scripts\python.exe"
    goto :have_python
)

REM b) python sur le PATH (on exclut l alias Microsoft Store)
python -c "import sys;sys.exit(0 if ('WindowsApps' not in sys.executable) and (sys.version_info[0]==3) else 1)" >nul 2>&1 && set "PYEXE=python"
if defined PYEXE goto :have_python

REM c) Lanceur py - 3.11
py -3.11 -c "import sys;sys.exit(0)" >nul 2>&1 && set "PYEXE=py -3.11"
if defined PYEXE goto :have_python

REM d) Lanceur py - 3
py -3 -c "import sys;sys.exit(0)" >nul 2>&1 && set "PYEXE=py -3"
if defined PYEXE goto :have_python

REM e) Lanceur py generique (Python 3 uniquement)
py -c "import sys;sys.exit(0 if sys.version_info[0]==3 else 1)" >nul 2>&1 && set "PYEXE=py"
if defined PYEXE goto :have_python

REM f) Secours : demander le chemin a l utilisateur
echo [!] Python n a pas ete trouve automatiquement.
echo.
echo Si vous avez installe le lanceur py, voici les versions detectees :
py -0p 2>nul
echo.
echo Copiez l un des chemins python.exe ci-dessus,
echo ou collez le chemin complet de votre Python 3.11, par exemple :
echo   C:\Users\VotreNom\AppData\Local\Programs\Python\Python311\python.exe
echo.
set /p "PYEXE=Chemin complet de python.exe (ou Entree pour quitter) : "
if "!PYEXE!"=="" goto :no_python

:have_python
echo Python utilise : !PYEXE!
echo.

REM Controle que c est bien Python 3
!PYEXE! -c "import sys;sys.exit(0 if sys.version_info[0]==3 else 1)" >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Le Python trouve n est pas une version 3.
    goto :no_python
)

REM ==========================================================
REM  1) Creation de l environnement virtuel
REM ==========================================================
if not exist ".venv\Scripts\python.exe" (
    echo [1/4] Creation de l environnement virtuel...
    !PYEXE! -m venv .venv
    if errorlevel 1 (
        echo [ERREUR] La creation de l environnement virtuel a echoue.
        goto :no_python
    )
    set "PYEXE=.venv\Scripts\python.exe"
)

REM ==========================================================
REM  2) Installation des dependances CORE (obligatoires)
REM ==========================================================
echo [2/4] Installation des dependances obligatoires (Flask, huggingface_hub)...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul 2>&1
".venv\Scripts\python.exe" -m pip install "Flask>=3.0" "huggingface_hub>=0.24"
if errorlevel 1 (
    echo [ERREUR] L installation des dependances obligatoires a echoue.
    echo         Verifiez votre connexion internet puis relancez ce fichier.
    pause
    exit /b 1
)

REM ==========================================================
REM  3) Installation de llama-cpp-python (optionnel : enrichissement/traduction)
REM     Si echec, l app demarre quand meme sans cette fonctionnalite.
REM ==========================================================
echo [3/4] Installation de llama-cpp-python (enrichissement de prompt, optionnel)...
".venv\Scripts\python.exe" -m pip install "llama-cpp-python>=0.3.0"
if errorlevel 1 (
    echo.
    echo [!] llama-cpp-python n a pas pu etre installe.
    echo     L enrichissement et la traduction de prompt seront desactives.
    echo     Le reste de l application fonctionne normalement.
    echo     Pour l activer plus tard : installez les "C++ Build Tools" Microsoft.
    echo.
)

REM ==========================================================
REM  4) Lancement de l application
REM ==========================================================
echo [4/4] Lancement...
echo.
echo   +  Ouvrez http://127.0.0.1:7860 dans votre navigateur
echo   +  Fermez cette fenetre pour arreter l application
echo.
".venv\Scripts\python.exe" app.py

echo.
echo Application arretee.
pause
exit /b 0

:no_python
echo.
echo ============================================================
echo Python 3 est requis. Telechargez-le ici :
echo   https://www.python.org/downloads/
echo Lors de l installation, COCHEZ la case :
echo   "Add Python to PATH"
echo Puis relancez ce fichier.
echo ============================================================
echo.
pause
exit /b 1
