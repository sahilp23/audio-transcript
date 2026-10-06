@echo off
rem Run by the installer (hidden): downloads Python 3.12 and the app's core packages
rem with the bundled uv.exe, so the first launch is quick. Output goes to setup.log.
setlocal
if "%CONCALL_SUPPORT_DIR%"=="" set "CONCALL_SUPPORT_DIR=%LOCALAPPDATA%\Concall Player"
set "CONCALL_SUPPORT_DIR=%CONCALL_SUPPORT_DIR:/=\%"
set "UV_PYTHON_INSTALL_DIR=%CONCALL_SUPPORT_DIR%\python"
set "UV_CACHE_DIR=%CONCALL_SUPPORT_DIR%\cache\uv"
set UV_MANAGED_PYTHON=1
set UV_NO_CONFIG=1
if not exist "%CONCALL_SUPPORT_DIR%\logs" mkdir "%CONCALL_SUPPORT_DIR%\logs"
set "LOG=%CONCALL_SUPPORT_DIR%\logs\setup.log"
echo === %DATE% %TIME% setup from %~dp0 >> "%LOG%"
"%~dp0uv.exe" venv --allow-existing --python 3.12 "%CONCALL_SUPPORT_DIR%\venv" >> "%LOG%" 2>&1 || exit /b 1
"%~dp0uv.exe" pip install --python "%CONCALL_SUPPORT_DIR%\venv\Scripts\python.exe" -r "%~dp0app\requirements.txt" >> "%LOG%" 2>&1 || exit /b 2
exit /b 0
