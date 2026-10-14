@echo off
rem ============================================================
rem  iniciar.bat - Lanza el grabador en Windows (GUI por defecto).
rem  Uso:  iniciar.bat        -> interfaz grafica
rem        iniciar.bat cli    -> menu de terminal
rem  No necesita permisos de administrador: crea un entorno
rem  virtual (.venv) dentro de esta carpeta.
rem ============================================================
setlocal
cd /d "%~dp0"

set "PY="
where py >nul 2>&1 && py -3 -c "import sys" >nul 2>&1 && set "PY=py -3"
if not defined PY (
    where python >nul 2>&1 && python -c "import sys" >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo [ERROR] No se encontro Python.
    echo   Instalalo con:  winget install Python.Python.3.12
    echo   o desde https://www.python.org/downloads/  ^(marca "Add python.exe to PATH"^)
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [INFO] Creando entorno virtual en .venv ...
    %PY% -m venv .venv
    if errorlevel 1 (
        echo [ERROR] No se pudo crear el entorno virtual.
        pause
        exit /b 1
    )
)

set "VPY=.venv\Scripts\python.exe"
if not exist ".venv\.deps_ok2" (
    echo [INFO] Instalando dependencias basicas ^(audio + ffmpeg^) ...
    "%VPY%" -m pip install --upgrade pip
    "%VPY%" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Fallo la instalacion. Revisa tu conexion a internet.
        pause
        exit /b 1
    )
    echo ok> ".venv\.deps_ok2"
)

if /i "%~1"=="cli" (
    "%VPY%" -m grabar_app cli
    if errorlevel 1 pause
) else (
    rem GUI sin ventana de consola: pythonw + start, y esta ventana se cierra
    start "" ".venv\Scripts\pythonw.exe" -m grabar_app
)
endlocal
