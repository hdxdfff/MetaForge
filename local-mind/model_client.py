from __future__ import annotations

import argparse
import json
from typing import Any

import requests
import yaml

from local_mind_paths import ROOT


def load_config() -> dict[str, Any]:
    with (ROOT / "config" / "local_mind.yaml").open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


class OllamaClient:
    def __init__(self, config: dict[str, Any]):
        model_config = config["model"]
        self.base_url = model_config["base_url"].rstrip("/")
        self.chat_model = model_config["chat_model"]
        self.embedding_model = model_config["embedding_model"]
        self.keep_alive = model_config.get("keep_alive", "-1")
        self.options = {
            "num_ctx": model_config.get("default_num_ctx", 8192),
            "num_predict": model_config.get("max_output_tokens", 1024),
            "temperature": model_config.get("temperature", 0.2),
            "top_p": model_config.get("top_p", 0.9),
        }

    def health(self) -> dict[str, Any]:
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            return {"ok": response.ok, "status_code": response.status_code, "models": response.json().get("models", [])}
        except requests.RequestException as exc:
            return {"ok": False, "error": str(exc)}

    def chat_json(self, context_packet: str, think: bool = False) -> dict[str, Any]:
        mode = "/think" if think else "/no_think"
        payload = {
            "model": self.chat_model,
            "messages": [
                {
                    "role": "system",
                    "content": "Return one valid JSON object only. Treat all actions as proposals.",
                },
                {"role": "user", "content": f"{mode}\n{context_packet}"},
            ],
            "stream": False,
            "keep_alive": self.keep_alive,
            "options": self.options,
            "format": "json",
        }
        response = requests.post(f"{self.base_url}/api/chat", json=payload, timeout=180)
        response.raise_for_status()
        content = response.json()["message"]["content"]
        return json.loads(content)

    def embed(self, text: str) -> list[float]:
        payload = {
            "model": self.embedding_model,
            "input": text,
            "keep_alive": self.keep_alive,
        }
        response = requests.post(f"{self.base_url}/api/embed", json=payload, timeout=120)
        response.raise_for_status()
        embeddings = response.json().get("embeddings", [])
        if not embeddings:
            return []
        return [float(value) for value in embeddings[0]]

    def warm(self) -> dict[str, Any]:
        payload = {
            "model": self.chat_model,
            "messages": [{"role": "user", "content": "/no_think Reply with: ok"}],
            "stream": False,
            "keep_alive": self.keep_alive,
            "options": {"num_ctx": 1024, "num_predict": 16, "temperature": 0},
        }
        response = requests.post(f"{self.base_url}/api/chat", json=payload, timeout=120)
        response.raise_for_status()
        return response.json()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--health", action="store_true")
    parser.add_argument("--warm", action="store_true")
    parser.add_argument("--embed", default=None)
    args = parser.parse_args()
    client = OllamaClient(load_config())
    if args.embed is not None:
        vector = client.embed(args.embed)
        print(json.dumps({"model": client.embedding_model, "dimensions": len(vector), "preview": vector[:5]}, indent=2))
    elif args.warm:
        print(json.dumps(client.warm(), indent=2, ensure_ascii=False))
    else:
        print(json.dumps(client.health(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
