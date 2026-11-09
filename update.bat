@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1
cd /d "%~dp0"

echo ============================================
echo   Local Image Studio - Mise a jour
echo ============================================
echo.

REM ==========================================================
REM  0- Prerequis : git + dossier = clone Git
REM ==========================================================
where git >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Git est introuvable.
    echo.
    echo Installez Git pour Windows : https://git-scm.com/download/win
    echo ^(Option par defaut a l'installeur : « Git from the command line »^)
    echo.
    echo Si vous utilisez une archive ZIP telechargee depuis GitHub, la mise a jour
    echo automatique n'est pas disponible : re-telechargez le ZIP, puis recopiez
    echo vos dossiers models/ output/ source_images/, history.db et settings.json.
    pause
    exit /b 1
)

if not exist ".git\" (
    echo [ERREUR] Ce dossier n'est pas un clone Git ^(pas de dossier .git^).
    echo.
    echo La mise a jour automatique fonctionne seulement si le depot a ete clone avec :
    echo     git clone https://github.com/Tivaphe/local-image-studio.git
    echo.
    echo Si vous utilisez le ZIP : re-telechargez le ZIP puis recopiez vos dossiers
    echo ^(models/ output/ source_images/, history.db, settings.json^) par-dessus.
    pause
    exit /b 1
)

git remote get-url origin >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Le remote « origin » n'est pas configure sur ce clone.
    pause
    exit /b 1
)

REM ==========================================================
REM  1- Modifications locales non validees ? -hors fichiers ignores-
REM     models/ output/ source_images/ history.db settings.json sont
REM     ignores par git : ils ne risquent JAMAIS rien ici.
REM ==========================================================
set "LOCAL_CHANGES="
for /f "delims=" %%i in ('git status --porcelain') do set "LOCAL_CHANGES=1"
set "DID_STASH="
if defined LOCAL_CHANGES (
    echo Des modifications locales non enregistrees sont presentes :
    echo.
    git status --short
    echo.
    echo ^(vos models/ output/ source_images/ history.db settings.json ne sont pas suivis par git et ne risquent rien^)
    echo.
    set /p "STASH_OK=Les mettre de cote automatiquement ^(git stash^) puis continuer ? [o/N] : "
    if /i "!STASH_OK!"=="o" goto :do_stash
    if /i "!STASH_OK!"=="oui" goto :do_stash
    echo Mise a jour annulee — aucune modification effectuee.
    pause
    exit /b 1
    :do_stash
    git stash push -u -m "update.bat backup %DATE% %TIME%"
    if errorlevel 1 (
        echo [ERREUR] git stash a echoue. Mise a jour annulee.
        pause
        exit /b 1
    )
    set "DID_STASH=1"
)

REM ==========================================================
REM  2- Recuperation des branches
REM ==========================================================
echo Recuperation des branches depuis GitHub...
git fetch origin --prune
if errorlevel 1 (
    echo [ERREUR] « git fetch » a echoue ^(connexion Internet ? droit d'acces ?^).
    if defined DID_STASH echo Vos modifications sont dans « git stash » ^(git stash pop pour les recuperer^).
    pause
    exit /b 1
)

REM ==========================================================
REM  3- Choix de la branche : [0] actuelle, [1..] main puis les autres
REM ==========================================================
set "CURRENT="
for /f "delims=" %%i in ('git branch --show-current') do set "CURRENT=%%i"
if "!CURRENT!"=="" set "CURRENT=DETACHED"

set "N=0"
set "HAS_MAIN="
for /f "delims=" %%i in ('git branch -r --format="%%(refname:short)" ^| findstr /v /c:"origin/HEAD"') do (
    if /i "%%i"=="origin/main" set "HAS_MAIN=1"
)
if defined HAS_MAIN (
    set /a N+=1
    set "CHOICE_!N!=main"
)
for /f "delims=" %%i in ('git branch -r --format="%%(refname:short)" ^| findstr /v /c:"origin/HEAD"') do (
    set "RB=%%i"
    set "RB=!RB:origin/=!"
    if /i not "!RB!"=="main" (
        set /a N+=1
        set "CHOICE_!N!=!RB!"
    )
)

echo.
echo Branche actuelle : !CURRENT!
echo.
echo Branches disponibles sur origin :
echo   [0] Rester sur « !CURRENT! » ^(git pull uniquement^)
set "i=0"
for /l %%i in (1,1,!N!) do (
    if /i "!CHOICE_%%i!"=="main" (
        echo   [%%i] main  ^<- recommandee ^(version stable^)
    ) else (
        echo   [%%i] !CHOICE_%%i!
    )
)
echo.
set /p "SEL=Votre choix ^(numero ou nom exact de branche, Entree = 0^) : "
if "!SEL!"=="" set "SEL=0"

if "!SEL!"=="0" (
    if "!CURRENT!"=="DETACHED" (
        echo [ERREUR] HEAD detache : choisissez une branche dans la liste.
        pause
        exit /b 1
    )
    set "TARGET=!CURRENT!"
    goto :checkout
)

REM Numero ?
set "TARGET="
for /l %%i in (1,1,!N!) do (
    if "!SEL!"=="%%i" set "TARGET=!CHOICE_%%i!"
)
REM Sinon : nom exact de branche -valide contre origin ou les branches locales-
if not defined TARGET set "TARGET=!SEL!"
git show-ref --verify --quiet "refs/remotes/origin/!TARGET!"
set "REMOTE_OK=!errorlevel!"
git show-ref --verify --quiet "refs/heads/!TARGET!"
set "LOCAL_OK=!errorlevel!"
if not "!REMOTE_OK!"=="0" if not "!LOCAL_OK!"=="0" (
    echo [ERREUR] Branche inconnue : « !TARGET! ».
    echo Relancez update.bat et choisissez un numero dans la liste.
    if defined DID_STASH echo Vos modifications sont dans « git stash » ^(git stash pop^).
    pause
    exit /b 1
)

:checkout
echo.
if /i "!TARGET!"=="!CURRENT!" (
    echo Vous restez sur « !TARGET! ».
) else (
    if "!LOCAL_OK!"=="0" (
        echo Bascule sur la branche locale « !TARGET! »...
        git checkout "!TARGET!"
    ) else (
        echo Bascule sur « !TARGET! » ^(suivi de origin/!TARGET!^)...
        git checkout -b "!TARGET!" --track "origin/!TARGET!"
    )
    if errorlevel 1 (
        echo [ERREUR] Le checkout de « !TARGET! » a echoue.
        if defined DID_STASH echo Vos modifications sont dans « git stash » ^(git stash pop^).
        pause
        exit /b 1
    )
)

REM ==========================================================
REM  4- Mise a jour -avance rapide uniquement-
REM ==========================================================
echo.
echo Mise a jour de « !TARGET! »...
git pull --ff-only origin "!TARGET!"
if errorlevel 1 (
    echo.
    echo [ERREUR] La mise a jour en avance rapide ^(ff-only^) a echoue.
    echo C'est le cas si votre branche locale a diverge ou contient des commits
    echo que le depot distant n'a pas.
    echo.
    echo Pour repartir proprement sur la version du depot ^(vos fichiers
    echo models/ output/ history.db settings.json ne sont PAS touches^) :
    echo     git checkout !TARGET!
    echo     git reset --hard origin/!TARGET!
    echo.
    if defined DID_STASH echo Vos modifications sont dans « git stash » ^(git stash pop^).
    pause
    exit /b 1
)

REM ==========================================================
REM  5- Rafraichissement de l'environnement virtuel -.venv-
REM ==========================================================
echo.
echo [5/5] Mise a jour de l'environnement virtuel .venv...

if exist ".venv\Scripts\python.exe" goto :venv_install
echo .venv absent - creation d'un nouvel environnement...
set "PYEXE="
python -c "import sys;sys.exit(0 if sys.version_info[0]==3 else 1)" >nul 2>&1 && set "PYEXE=python"
if defined PYEXE goto :venv_create
py -3 -c "import sys;sys.exit(0)" >nul 2>&1 && set "PYEXE=py -3"
if defined PYEXE goto :venv_create
py -c "import sys;sys.exit(0 if sys.version_info[0]==3 else 1)" >nul 2>&1 && set "PYEXE=py"
:venv_create
if not defined PYEXE (
    echo [ERREUR] Python 3 introuvable. Lancez start.bat - il explique comment
    echo installer Python - puis relancez update.bat.
    pause
    exit /b 1
)
echo Creation de .venv avec : !PYEXE!
!PYEXE! -m venv .venv
if errorlevel 1 (
    echo [ERREUR] La creation de .venv a echoue.
    pause
    exit /b 1
)

:venv_install

".venv\Scripts\python.exe" -m pip install --upgrade pip >nul 2>&1

if exist "requirements.txt" (
    echo Installation des dependances via requirements.txt...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERREUR] L'installation des dependances a echoue.
        echo Verifiez votre connexion internet puis relancez update.bat.
        if defined DID_STASH echo Vos modifications sont dans « git stash » ^(git stash pop^).
        pause
        exit /b 1
    )
) else (
    echo Installation des dependances de base...
    ".venv\Scripts\python.exe" -m pip install "Flask>=3.0" "huggingface_hub>=0.24" "Pillow>=10.0"
    if errorlevel 1 (
        echo [ERREUR] L'installation des dependances a echoue.
        pause
        exit /b 1
    )
)

REM llama-cpp-python -optionnel : enrichissement / traduction- — jamais bloquant
echo Mise a jour de llama-cpp-python (optionnel)...
".venv\Scripts\python.exe" -m pip install "llama-cpp-python>=0.3.0"
if errorlevel 1 (
    echo [!] llama-cpp-python n'a pas pu etre mis a jour — l'app fonctionne sans
    echo     ^(enrichissement / traduction desactives^).
)

REM ==========================================================
REM  6- Resume
REM ==========================================================
echo.
echo ============================================
echo   Mise a jour terminee !
echo ============================================
git log -1 --format="Branche : %%D%%nDernier commit : %%h — %%s"
echo.
if defined DID_STASH (
    echo Note : vos modifications locales sont dans « git stash » —
    echo        retrouvez-les avec : git stash pop
    echo.
)
echo Double-cliquez sur start.bat pour lancer l'application mise a jour.
pause
exit /b 0
