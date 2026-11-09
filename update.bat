@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1

REM ==========================================================
REM  Lanceur : une copie de ce script s'execute depuis %TEMP%
REM  pour que la mise a jour puisse REMPLACER update.bat lui-meme
REM  sans perturber la lecture du fichier en cours d'execution.
REM ==========================================================
if defined LIS_UPDATE_RUNNER goto :main
set "LIS_UPDATE_RUNNER=1"
set "RUNCOPY=%TEMP%\lis_update_%RANDOM%_%RANDOM%.bat"
copy /y "%~f0" "%RUNCOPY%" >nul 2>&1
if errorlevel 1 (
    echo [!] Copie temporaire impossible - poursuite avec le fichier original.
    set "LIS_UPDATE_RUNNER=1"
    set "ROOT=%~dp0"
    goto :main
)
call "%RUNCOPY%" "%~dp0"
set "RC=%errorlevel%"
del "%RUNCOPY%" >nul 2>&1
exit /b %RC%

:main
set "ROOT=%~1"
if "!ROOT!"=="" set "ROOT=%~dp0"
if not "!ROOT:~-1!"=="\" set "ROOT=!ROOT!\"
cd /d "!ROOT!"

echo ============================================
echo   Local Image Studio - Mise a jour
echo ============================================
echo.

REM ==========================================================
REM  0- Mode de mise a jour : clone Git recommande ou ZIP

REM     - Clone Git : mise a jour par avance rapide, stash possible
REM     - Archive ZIP sans git : telecharge le ZIP de la branche
REM       choisie depuis GitHub, sauvegarde puis ECRASE les fichiers
REM       de l'application. Vos donnees personnelles ne sont PAS
REM       dans l'archive ZIP : models/ output/ source_images/
REM       portraits/ history.db settings.json .venv bin/ sont TOUJOURS preserves.
REM ==========================================================
set "GITMODE=0"
where git >nul 2>&1
if errorlevel 1 goto :zip_mode
if not exist ".git\" goto :zip_mode
git remote get-url origin >nul 2>&1
if errorlevel 1 goto :zip_mode
set "GITMODE=1"
goto :git_flow

REM ==========================================================
REM  MODE ZIP - SANS GIT
REM ==========================================================
:zip_mode
echo Ce dossier n'est pas un clone Git^(ou git est introuvable^).
echo Mode ARCHIVE ZIP : la branche choisie sera telechargee depuis GitHub
echo puis les fichiers de l'application seront remplaces.
echo.
echo Les donnees personnelles ne sont PAS dans l'archive :
echo   models/  output/  source_images/  portraits/  history.db  settings.json  .venv  bin/
echo Elles ne seront JAMAIS modifiees ni supprimees.
echo.

REM --- PowerShell est requis pour telecharger et extraire le ZIP
powershell -NoProfile -Command "1" >nul 2>&1
if errorlevel 1 goto :no_powershell

REM --- Liste des branches depuis l'API GitHub
echo Recuperation de la liste des branches depuis GitHub...
for /f "delims=" %%i in ('powershell -NoProfile -Command "Get-Random -Maximum 999999"') do set "RAND=%%i"
if not defined RAND set "RAND=%RANDOM%"
set "BRFILE=%TEMP%\lis_branches_!RAND!.txt"
powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; [Console]::OutputEncoding=[Text.Encoding]::UTF8; try { (Invoke-RestMethod -Uri 'https://api.github.com/repos/Tivaphe/local-image-studio/branches?per_page=30' -Headers @{ 'User-Agent'='lis-updater' }).name } catch { exit 3 }" > "!BRFILE!"
if errorlevel 1 goto :no_network
goto :branch_menu

:no_powershell
echo [ERREUR] Windows PowerShell est introuvable.
echo.
echo Le mode ZIP requiert PowerShell ^(fourni avec Windows 7 SP1 et plus^).
echo Pour mettre a jour manuellement : telechargez le ZIP de la branche
echo voulue sur https://github.com/Tivaphe/local-image-studio/archive/refs/heads/main.zip
echo puis recopiez les fichiers du ZIP par-dessus ce dossier
echo ^(models/ output/ history.db settings.json ne sont pas dans le ZIP^).
pause
exit /b 1

:no_network
echo [ERREUR] GitHub est inaccessible ^(connexion Internet ? acces refuse ?^).
echo Verifiez votre connexion puis relancez update.bat.
pause
exit /b 1

:branch_menu
if not exist "!BRFILE!" goto :no_network
set "N=0"
findstr /i /x /l "main" "!BRFILE!" >nul 2>&1
if not errorlevel 1 (
    set /a N+=1
    set "CHOICE_!N!=main"
)
for /f "usebackq delims=" %%i in ("!BRFILE!") do (
    if /i not "%%i"=="main" (
        set /a N+=1
        set "CHOICE_!N!=%%i"
    )
)
if "!N!"=="0" goto :no_network

echo.
echo Branches disponibles sur GitHub :
set "i=0"
for /l %%i in (1,1,!N!) do (
    if /i "!CHOICE_%%i!"=="main" (
        echo   [%%i] main  ^<- recommandee ^(version stable^)
    ) else (
        echo   [%%i] !CHOICE_%%i!
    )
)
echo.
set /p "SEL=Votre choix ^(numero ou nom exact de branche, Entree = main^) : "
if "!SEL!"=="" set "SEL=main"

set "TARGET="
for /l %%i in (1,1,!N!) do (
    if "!SEL!"=="%%i" set "TARGET=!CHOICE_%%i!"
)
if not defined TARGET set "TARGET=!SEL!"
findstr /i /x /l "!TARGET!" "!BRFILE!" >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Branche inconnue : « !TARGET! ».
    echo Relancez update.bat et choisissez un numero dans la liste.
    del "!BRFILE!" >nul 2>&1
    pause
    exit /b 1
)

for /f "delims=" %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "STAMP=%%i"
if not defined STAMP set "STAMP=%RANDOM%%RANDOM%"

set "DLZIP=%TEMP%\lis_update_!STAMP!.zip"
set "DLDIR=%TEMP%\lis_extract_!STAMP!"
set "BACKUP=%TEMP%\lis_backup_!STAMP!"
set "URL=https://codeload.github.com/Tivaphe/local-image-studio/zip/refs/heads/!TARGET!"

echo.
echo Telechargement de la branche « !TARGET! »...
powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; try { Invoke-WebRequest -Uri '!URL!' -UseBasicParsing -OutFile '!DLZIP!' } catch { exit 3 }"
if errorlevel 1 goto :download_failed
for %%S in ("!DLZIP!") do set "DLSIZE=%%~zS"
if not defined DLSIZE set "DLSIZE=0"
if !DLSIZE! LSS 50000 goto :download_suspect

echo Extraction de l'archive...
powershell -NoProfile -Command "try { Expand-Archive -LiteralPath '!DLZIP!' -DestinationPath '!DLDIR!' -Force } catch { exit 3 }"
if errorlevel 1 goto :extract_failed
set "SRCROOT="
for /d %%d in ("!DLDIR!\*") do set "SRCROOT=%%d"
if not defined SRCROOT goto :extract_failed
if not exist "!SRCROOT!" goto :extract_failed

echo Sauvegarde des fichiers actuels dans : !BACKUP!
robocopy "!ROOT!." "!BACKUP!" /E /NFL /NDL /NJH /NJS /XD ".venv" "bin" "models" "output" "source_images" "portraits" ".preview_cache" "node_modules"
if !errorlevel! GEQ 8 goto :backup_failed

echo.
echo Remplacement des fichiers de l'application ^(vos donnees sont preservees^)...
REM Dossiers de code qui n'existent plus dans le nouveau ZIP
REM suppression avant copie pour eviter de garder du code mort
REM cas rare - changement de structure entre deux versions
for %%D in (src static templates tests scripts docs) do (
    if exist "%%~D" if not exist "!SRCROOT!\%%~D" (
        echo Ancien dossier « %%~D » absent du nouveau ZIP : suppression.
        rmdir /s /q "%%~D"
    )
)
robocopy "!SRCROOT!" "!ROOT!." /E /NFL /NDL /NJH /NJS
if !errorlevel! GEQ 8 goto :overlay_failed

del "!DLZIP!" >nul 2>&1
rmdir /s /q "!DLDIR!" >nul 2>&1
del "!BRFILE!" >nul 2>&1
echo Fichiers de l'application mis a jour depuis la branche « !TARGET! ».
echo Sauvegarde des fichiers remplaces : !BACKUP!
goto :venv_update

:download_failed
echo [ERREUR] Le telechargement a echoue ^(connexion ? acces a GitHub ?^).
echo Vos fichiers n'ont PAS ete modifies.
del "!DLZIP!" >nul 2>&1
del "!BRFILE!" >nul 2>&1
pause
exit /b 1

:download_suspect
echo [ERREUR] Le fichier telecharge est anormalement petit ^(!DLSIZE! octets^).
echo GitHub a peut-etre refuse la requete. Vos fichiers n'ont PAS ete modifies.
del "!DLZIP!" >nul 2>&1
del "!BRFILE!" >nul 2>&1
pause
exit /b 1

:extract_failed
echo [ERREUR] Impossible d'extraire l'archive telechargee.
echo Vos fichiers n'ont PAS ete modifies.
del "!DLZIP!" >nul 2>&1
rmdir /s /q "!DLDIR!" >nul 2>&1
del "!BRFILE!" >nul 2>&1
pause
exit /b 1

:backup_failed
echo [ERREUR] La sauvegarde a echoue - mise a jour ANNULEE. Vos fichiers n'ont PAS ete modifies.
del "!DLZIP!" >nul 2>&1
rmdir /s /q "!DLDIR!" >nul 2>&1
del "!BRFILE!" >nul 2>&1
pause
exit /b 1

:overlay_failed
echo.
echo [ERREUR] La copie des nouveaux fichiers a partiellement echoue.
echo Une sauvegarde complete de l'etat AVANT mise a jour est disponible ici :
echo     !BACKUP!
echo Restaurez-la par-dessus ce dossier pour revenir en arriere.
del "!DLZIP!" >nul 2>&1
rmdir /s /q "!DLDIR!" >nul 2>&1
del "!BRFILE!" >nul 2>&1
pause
exit /b 1

REM ==========================================================
REM  MODE GIT - clone du depot
REM ==========================================================
:git_flow
REM --- Modifications locales non commitees ? -hors fichiers ignores-
REM models/ output/ history.db settings.json sont ignores par git : ils ne risquent JAMAIS rien.
set "LOCAL_CHANGES="
for /f "delims=" %%i in ('git status --porcelain') do set "LOCAL_CHANGES=1"
set "DID_STASH="
if defined LOCAL_CHANGES goto :local_changes_yes
goto :local_changes_no
:local_changes_yes
echo Des modifications locales non enregistrees sont presentes :
echo.
git status --short
echo.
echo ^(vos models/ output/ history.db settings.json ne sont pas suivis par git et ne risquent rien^)
echo.
set /p "STASH_OK=Les mettre de cote automatiquement ^(git stash^) puis continuer ? [o/N] : "
if /i "!STASH_OK!"=="o" goto :do_stash
if /i "!STASH_OK!"=="oui" goto :do_stash
echo Mise a jour annulee - aucune modification effectuee.
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
:local_changes_no

REM --- Recuperation des branches
echo Recuperation des branches depuis GitHub...
git fetch origin --prune
if errorlevel 1 (
    echo [ERREUR] « git fetch » a echoue ^(connexion Internet ? droit d'acces ?^).
    if defined DID_STASH echo Vos modifications sont dans « git stash » ^(git stash pop pour les recuperer^).
    pause
    exit /b 1
)

REM --- Choix de la branche : [0] actuelle, [1..] main puis les autres
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
    set "LOCAL_OK=0"
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

REM --- Mise a jour -avance rapide uniquement-
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
goto :venv_update

REM ==========================================================
REM  Venv commun aux deux modes
REM ==========================================================
:venv_update
echo.
echo Mise a jour de l'environnement virtuel .venv...

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

echo Mise a jour de llama-cpp-python ^(optionnel^)...
".venv\Scripts\python.exe" -m pip install "llama-cpp-python>=0.3.0"
if errorlevel 1 (
    echo [!] llama-cpp-python n'a pas pu etre mis a jour - l'app fonctionne sans
    echo     ^(enrichissement / traduction desactives^).
)

REM ==========================================================
REM  Resume
REM ==========================================================
echo.
echo ============================================
echo   Mise a jour terminee !
echo ============================================
if "!GITMODE!"=="1" (
    git log -1 --format="Branche : %%D%%nDernier commit : %%h — %%s"
    if defined DID_STASH (
        echo Note : vos modifications locales sont dans « git stash » —
        echo        retrouvez-les avec : git stash pop
        echo.
    )
) else (
    echo Branche installee : !TARGET! ^(archive ZIP^)
    echo Sauvegarde des fichiers remplaces : !BACKUP!
    echo ^(conservee jusqu'au prochain nettoyage de %%TEMP%% par Windows^)
    echo Comportement des mises a jour ZIP : les fichiers du depot sont ECRASES,
    echo les fichiers absents du depot ^(votre dossier models/, vos images...^) sont preserves.
)
echo.
echo Double-cliquez sur start.bat pour lancer l'application mise a jour.
pause
exit /b 0
