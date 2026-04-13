$env:OPENCLAW_ROOT = "D:\codex\tools\openclaw-home"
$env:NODE_ROOT = "D:\codex\tools\node-v22.22.1-win-x64"
$env:PATH = "D:\codex\tools\mingit-2.53.0-64-bit\cmd;$env:NODE_ROOT;" + $env:PATH
& "$env:NODE_ROOT\node.exe" "$env:OPENCLAW_ROOT\node_modules\openclaw\openclaw.mjs" @args
exit $LASTEXITCODE