@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set REPO=https://github.com/wangcangxing/sc-translator.git
set "PY=.venv\Scripts\python.exe"

rem 版本号一律从 sc_translator\__init__.py 现读，避免像 v0.1.0 那样写死后忘记改
if not exist "%PY%" (
  echo [错误] 未找到 %PY%
  echo        请先双击 run.bat 完成环境安装。
  pause
  exit /b 1
)
rem 注意：for /f 里给 exe 路径加引号会被 cmd 的引号剥离规则弄坏（实测 C 形失败），
rem 这里用不加引号的相对路径——.venv\Scripts\python.exe 本身不含空格，且已 cd 到脚本目录。
for /f "delims=" %%v in ('%PY% -c "import sc_translator; print(sc_translator.__version__)"') do set "VER=%%v"
if not defined VER (
  echo [错误] 无法从 sc_translator\__init__.py 读取版本号。
  pause
  exit /b 1
)
set "ZIP=dist\SCTranslator-v%VER%-win64.zip"
set "TAG=v%VER%"
set "NOTES=docs\RELEASE-v%VER%.md"

echo ============================================
echo  发布到 GitHub：wangcangxing/sc-translator  版本 v%VER%
echo ============================================
echo.

echo [1/3] 配置远程仓库 origin ...
git remote get-url origin >nul 2>nul
if errorlevel 1 (
  git remote add origin %REPO%
) else (
  git remote set-url origin %REPO%
)
git remote -v

echo.
echo [2/3] 推送 main 分支（首次会弹出浏览器登录 GitHub，授权即可）...
git push -u origin main
if errorlevel 1 goto :fail

echo.
echo [3/3] 复制发行说明到剪贴板，并打开 Release 页面 ...
if not exist "%NOTES%" (
  echo [提示] 未找到 %NOTES%，请先写好这一版的发行说明再发布。
)
powershell -NoProfile -Command "if (Test-Path '%NOTES%') { Get-Content -Raw '%NOTES%' | Set-Clipboard }" 2>nul
if not exist "%ZIP%" (
  echo [提示] 未找到 %ZIP%，先双击 build.bat 打包，或手动上传已有文件。
)
start "" "https://github.com/wangcangxing/sc-translator/releases/new?tag=%TAG%"

echo.
echo 完成！接下来在浏览器里：
echo   1) Release title 填： v%VER%
echo   2) 说明框粘贴 %NOTES% 的内容（已复制到剪贴板）
echo   3) 附件区拖入 %ZIP%
echo   4) 点 Publish release
echo.
echo 说明文本已复制到剪贴板（若为空，手动打开 %NOTES% 复制）。
pause
exit /b 0

:fail
echo.
echo [失败] 推送未完成。常见原因：
echo   - 仓库还没建：先打开 https://github.com/new 建一个空的 sc-translator（不要勾 README）
echo   - 权限/登录失败：改用 PAT（Settings - Developer settings - Tokens classic，勾 repo）
echo   - 远程已有提交：先执行 git pull --rebase origin main 再试
pause
exit /b 1
