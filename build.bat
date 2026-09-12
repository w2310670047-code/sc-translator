@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ============================================
echo  SC Translator 打包（PyInstaller onedir）
echo ============================================
echo.

set PY=.venv\Scripts\python.exe
if not exist "%PY%" (
  echo [错误] 未找到虚拟环境 %PY%
  echo        请先双击 run.bat 完成一次环境安装。
  pause
  exit /b 1
)

"%PY%" -c "import PyInstaller" 2>nul
if errorlevel 1 (
  echo [1/2] 安装 PyInstaller ...
  "%PY%" -m pip install --upgrade pyinstaller || goto :fail
) else (
  echo [1/2] PyInstaller 已安装，跳过。
)

echo [2/2] 开始打包 ...
"%PY%" -m PyInstaller --noconfirm --clean SCTranslator.spec || goto :fail

echo.
echo 打包完成：dist\SCTranslator\SCTranslator.exe
echo 自检命令：dist\SCTranslator\SCTranslator.exe --doctor
echo 在线自检：dist\SCTranslator\SCTranslator.exe --doctor --online
pause
exit /b 0

:fail
echo.
echo [失败] 打包未完成，请查看上方错误信息。
pause
exit /b 1
