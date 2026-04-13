from __future__ import annotations

import base64
import mimetypes
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def configure_client() -> tuple[OpenAI, str]:
    dashscope_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    if dashscope_key:
        api_key = dashscope_key
        base_url = os.getenv(
            "DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
        model = os.getenv("DASHSCOPE_VISION_MODEL", "qwen-vl-plus")
    else:
        api_key = require_env("OPENAI_API_KEY")
        base_url = os.getenv("OPENAI_BASE_URL", "").strip() or None
        model = os.getenv("OPENAI_MODEL_NAME", "gpt-4o")

    client = OpenAI(api_key=api_key, base_url=base_url)
    return client, model


def image_to_data_url(path: Path) -> str:
    mime_type, _ = mimetypes.guess_type(path.name)
    if not mime_type:
        mime_type = "application/octet-stream"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Usage: vision_demo.py <image_path> [question]")

    image_path = Path(sys.argv[1]).expanduser().resolve()
    if not image_path.exists():
        raise SystemExit(f"Image not found: {image_path}")

    question = (
        sys.argv[2]
        if len(sys.argv) > 2
        else "请一步步解释这张截图里用户正在做什么，并给出下一步建议。"
    )

    client, model = configure_client()
    data_url = image_to_data_url(image_path)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": "你是一位大学计算机专业学习导师。请根据图片中的界面和操作，给出清晰、分步骤、可执行的中文指导。",
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": question},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ],
    )
    print(response.choices[0].message.content or "")


if __name__ == "__main__":
    main()
