@ECHO off
SETLOCAL
SET "OPENCODE_STATE_ROOT_OVERRIDE=D:\codex\oi-state-opencode-fast"
SET "OPENCODE_FAST_WORKSPACE=D:\codex\opencode-workspace-fast"
CALL "D:\codex\opencode.cmd" %*
