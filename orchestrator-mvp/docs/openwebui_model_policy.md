# Open WebUI Model Policy

- Source: `D:\codex\opencode.jsonc`
- Provider: `volcengine-plan`
- Base URL: `https://ark.cn-beijing.volces.com/api/coding/v3`
- Default model: `minimax-m2.5`
- Pinned models: `minimax-m2.5, kimi-k2.5, vision-pro, vision-lite`
- Primary alias: `minimax-m2.5` -> `minimax-m2.5`
- Small alias: `kimi-k2.5` -> `kimi-k2.5`
- Multimodal alias: `vision-pro` -> `doubao-1.5-vision-pro-250328`
- Multimodal alias: `vision-lite` -> `doubao-1.5-vision-lite-250315`

Open WebUI is configured to prefer the primary model for routine control, the small model for cheaper reasoning or fallback, and two multimodal models for vision-heavy tasks.
