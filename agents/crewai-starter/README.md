# CrewAI Starter

This project can run in two modes:

- text mode: standard CrewAI demo
- vision mode: analyze a screenshot with an OpenAI-compatible vision model

Supported providers:

- OpenAI
- Alibaba Cloud DashScope (OpenAI-compatible)

Recommended DashScope settings:

- `DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1`
- `DASHSCOPE_TEXT_MODEL=qwen-plus`
- `DASHSCOPE_VISION_MODEL=qwen-vl-plus`

Examples:

```powershell
powershell -ExecutionPolicy Bypass -File D:\codex\agents\crewai-starter\run.ps1
```

```powershell
powershell -ExecutionPolicy Bypass -File D:\codex\agents\crewai-starter\run.ps1 -ImagePath C:\path\to\screenshot.png
```

```powershell
powershell -ExecutionPolicy Bypass -File D:\codex\agents\crewai-starter\run.ps1 -ImagePath C:\path\to\screenshot.png -Question "请一步步指出我下一步该点哪里"
```
