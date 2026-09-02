@echo off
REM ===========================================================================
REM  Reparation de l'environnement LangGraph (projet IntelliMail_Backend)
REM  Double-cliquez ce fichier, OU lancez-le depuis votre terminal.
REM  Il reinstalle l'ensemble LangGraph coherent dans le .venv du projet.
REM ===========================================================================
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo ===========================================================================
echo   Correction de l'environnement LangGraph
echo ===========================================================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [ERREUR] .venv introuvable dans ce dossier :
    echo   %cd%
    echo Placez ce script a la racine du projet IntelliMail_Backend, puis relancez.
    echo.
    pause
    exit /b 1
)

echo [1/3] Mise a jour de pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip

echo.
echo [2/3] Reinstallation de l'ensemble LangGraph coherent (requirements.txt)...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [ERREUR] L'installation a echoue. Verifiez votre connexion internet.
    pause
    exit /b 1
)

echo.
echo [3/3] Verification de l'import qui plantait...
".venv\Scripts\python.exe" -c "from langgraph_api import feature_flags, graph; import langgraph_runtime_inmem, langgraph_api; print('OK : langgraph-api', langgraph_api.__version__, '+ runtime-inmem', langgraph_runtime_inmem.__version__, '-> feature_flags importe sans erreur')"
if errorlevel 1 (
    echo.
    echo [ERREUR] L'import echoue encore. Copiez le message ci-dessus et envoyez-le.
    pause
    exit /b 1
)

echo.
echo ===========================================================================
echo   TERMINE. Vous pouvez maintenant lancer :   langgraph dev
echo ===========================================================================
echo.
pause
