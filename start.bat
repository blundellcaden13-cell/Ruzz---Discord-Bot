@echo off
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo Python not found. Install from https://www.python.org/downloads/
    exit /b 1
)

if not exist venv (
    echo Creating venv...
    python -m venv venv
)

call venv\Scripts\activate.bat

set REQ_HASH_FILE=venv\.requirements.hash
for /f %%H in ('certutil -hashfile requirements.txt SHA256 ^| findstr /v "hash CertUtil"') do set CURRENT_HASH=%%H

set OLD_HASH=
if exist "%REQ_HASH_FILE%" set /p OLD_HASH=<"%REQ_HASH_FILE%"

if not "%CURRENT_HASH%"=="%OLD_HASH%" (
    echo Installing dependencies...
    python -m pip install --upgrade pip -q
    pip install -r requirements.txt -q
    echo %CURRENT_HASH%> "%REQ_HASH_FILE%"
) else (
    echo Dependencies up to date.
)

python launcher.py
