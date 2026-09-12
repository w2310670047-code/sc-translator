@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set REPO=https://github.com/w2310670047-code/sc-translator.git
set ZIP=dist\SCTranslator-v0.1.0-win64.zip
set TAG=v0.1.0

echo ============================================
echo  发布到 GitHub：w2310670047-code/sc-translator
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
powershell -NoProfile -Command "Get-Content -Raw 'docs\RELEASE-v0.1.0.md' | Set-Clipboard" 2>nul
if not exist "%ZIP%" (
  echo [提示] 未找到 %ZIP%，先双击 build.bat 打包，或手动上传已有文件。
)
start "" "https://github.com/w2310670047-code/sc-translator/releases/new?tag=%TAG%"

echo.
echo 完成！接下来在浏览器里：
echo   1) Release title 填： v0.1.0 — 首个公开版本：星际公民双向文字翻译器
echo   2) 说明框粘贴 docs\RELEASE-v0.1.0.md 的内容（已复制到剪贴板）
echo   3) 附件区拖入 %ZIP%
echo   4) 点 Publish release
echo.
echo 说明文本已复制到剪贴板（若为空，手动打开 docs\RELEASE-v0.1.0.md 复制）。
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
