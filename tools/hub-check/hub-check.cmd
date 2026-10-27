@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set NODE="%USERPROFILE%\HubApps\runtime\node\node.exe"
if not exist %NODE% (
  echo.
  echo [FAIL] Node runtime not found: %USERPROFILE%\HubApps\runtime\node\node.exe
  echo        The hub agent is not installed yet. Run the hub installer first.
  echo.
  pause
  exit /b 1
)
%NODE% "%~dp0hub-check.mjs" %*
echo.
echo Exit code: %ERRORLEVEL%   ^(0 = no FAIL, 1 = has FAIL^)
if "%~1"=="" pause
