@echo off
setlocal
cd /d "%~dp0"

set "PYW=.venv\Scripts\pythonw.exe"
set "PY=.venv\Scripts\python.exe"
set "MARKER=%~dp0data\logs\app_ready.marker"

if exist "%PYW%" goto :launch

echo [First run] Virtual environment not found, creating it...
set "PYEXE="
for %%F in ("%LOCALAPPDATA%\Programs\Python\Python3*\python.exe" "C:\Python3*\python.exe" "D:\Python3*\python.exe" "E:\Python3*\python.exe") do if not defined PYEXE if exist "%%~F" set "PYEXE=%%~F"
if not defined PYEXE where python >nul 2>nul && set "PYEXE=python"
if not defined PYEXE goto :nopython
echo Using interpreter: %PYEXE%
"%PYEXE%" -m venv .venv
if not exist "%PY%" goto :venv_bad
echo [First run] Installing dependencies, please wait...
"%PY%" -m pip install --upgrade pip -q
"%PY%" -m pip install -r requirements.txt
if errorlevel 1 goto :install_err

:launch
if exist "%MARKER%" del /q "%MARKER%"

start "" "%PYW%" -m sc_translator

set /a tries=0
:wait
if exist "%MARKER%" goto :ok
tasklist /fi "imagename eq pythonw.exe" 2>nul | find /i "pythonw.exe" >nul
if errorlevel 1 goto :timeout
timeout /t 1 /nobreak >nul
set /a tries+=1
if %tries% geq 20 goto :timeout
goto :wait

:ok
exit /b 0

:timeout
echo.
echo [Error] The translator did not start (no ready marker within 20s).
echo Startup log: %~dp0data\logs\startup.log
if exist "%~dp0data\logs\startup.log" (
  echo ---------- last lines of startup.log ----------
  powershell -NoProfile -Command "$p='%~dp0data\logs\startup.log'; if(Test-Path $p){ Get-Content $p -Tail 25 }"
  echo ----------------------------------------------
)
pause
exit /b 1

:nopython
echo [Error] Python 3.10+ not found. Please install the official version from
echo https://www.python.org/downloads/  (MSYS2/Git python is NOT supported).
pause
exit /b 1

:venv_bad
echo [Error] Failed to create virtual environment (unsupported python?).
echo Please install python.org official Python 3.10+ and run again.
pause
exit /b 1

:install_err
echo [Error] Dependency installation failed. Check your network and rerun.
pause
exit /b 1