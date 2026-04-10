from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CODEX_ROOT = ROOT.parent
OPENCODE_CONFIG = CODEX_ROOT / "opencode.jsonc"
OUT_DIR = ROOT / "docs"
OUT_JSON = OUT_DIR / "openwebui_model_policy.json"
OUT_MD = OUT_DIR / "openwebui_model_policy.md"


def _load_jsonc(path: Path) -> dict:
    text = path.read_text(encoding="utf-8-sig")
    return json.loads(text)


def main() -> int:
    config = _load_jsonc(OPENCODE_CONFIG)
    provider = config.get("provider", {}).get("volcengine-plan", {})
    models = provider.get("models", {})

    primary = config.get("model")
    small = config.get("small_model")
    if not primary or not small:
        raise SystemExit("opencode.jsonc is missing model or small_model")

    policy = {
        "source": str(OPENCODE_CONFIG),
        "provider": {
            "name": "volcengine-plan",
            "base_url": provider.get("options", {}).get("baseURL"),
            "model_family": provider.get("name"),
        },
        "openwebui": {
            "default_model": "minimax-m2.5",
            "pinned_models": [
                "minimax-m2.5",
                "kimi-k2.5",
                "vision-pro",
                "vision-lite",
            ],
        },
        "models": {
            "primary": {
                "alias": "minimax-m2.5",
                "upstream": primary.split("/", 1)[-1],
                "label": models.get(primary.split("/", 1)[-1], {}).get("name", primary),
            },
            "small": {
                "alias": "kimi-k2.5",
                "upstream": small.split("/", 1)[-1],
                "label": models.get(small.split("/", 1)[-1], {}).get("name", small),
            },
            "vision_pro": {
                "alias": "vision-pro",
                "upstream": "doubao-1.5-vision-pro-250328",
                "label": "doubao-1.5-vision-pro-250328",
            },
            "vision_lite": {
                "alias": "vision-lite",
                "upstream": "doubao-1.5-vision-lite-250315",
                "label": "doubao-1.5-vision-lite-250315",
            },
        },
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(policy, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_MD.write_text(
        "\n".join(
            [
                "# Open WebUI Model Policy",
                "",
                f"- Source: `{OPENCODE_CONFIG}`",
                f"- Provider: `{policy['provider']['name']}`",
                f"- Base URL: `{policy['provider']['base_url']}`",
                f"- Default model: `{policy['openwebui']['default_model']}`",
                f"- Pinned models: `{', '.join(policy['openwebui']['pinned_models'])}`",
                f"- Primary alias: `{policy['models']['primary']['alias']}` -> `{policy['models']['primary']['upstream']}`",
                f"- Small alias: `{policy['models']['small']['alias']}` -> `{policy['models']['small']['upstream']}`",
                f"- Multimodal alias: `{policy['models']['vision_pro']['alias']}` -> `{policy['models']['vision_pro']['upstream']}`",
                f"- Multimodal alias: `{policy['models']['vision_lite']['alias']}` -> `{policy['models']['vision_lite']['upstream']}`",
                "",
                "Open WebUI is configured to prefer the primary model for routine control, the small model for cheaper reasoning or fallback, and two multimodal models for vision-heavy tasks.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"wrote {OUT_JSON}")
    print(f"wrote {OUT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
