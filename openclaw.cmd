@ECHO off
SETLOCAL
SET "OPENCLAW_ROOT=D:\codex\tools\openclaw-home"
SET "NODE_ROOT=D:\codex\tools\node-v22.22.1-win-x64"
SET "PATH=D:\codex\tools\mingit-2.53.0-64-bit\cmd;%NODE_ROOT%;%PATH%"
"%NODE_ROOT%\node.exe" "%OPENCLAW_ROOT%\node_modules\openclaw\openclaw.mjs" %*