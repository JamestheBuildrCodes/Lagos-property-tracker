"""Small live connectivity check for the configured Groq-hosted model."""
from __future__ import annotations

import json
import os
import sys

import requests

URL = "https://api.groq.com/openai/v1/chat/completions"


def main() -> int:
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    model = os.environ.get("GROQ_MODEL", "qwen/qwen3.8-27b").strip() or "qwen/qwen3.8-27b"
    if not api_key:
        raise SystemExit("GROQ_API_KEY is missing; Groq live check cannot run.")

    response = requests.post(
        URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": "Return a JSON object only."},
                {"role": "user", "content": "Return exactly this JSON object: {\\"ok\\":true}"},
            ],
            "temperature": 0,
            "max_tokens": 30,
            "response_format": {"type": "json_object"},
        },
        timeout=(10, 45),
    )
    if response.status_code >= 300:
        print(f"Groq API live check failed: HTTP {response.status_code}.")
        return 1
    try:
        body = response.json()
        content = body["choices"][0]["message"]["content"]
        parsed = json.loads(content)
    except (ValueError, KeyError, IndexError, TypeError):
        print("Groq API returned a successful HTTP status but not valid JSON chat output.")
        return 1
    if parsed.get("ok") is not True:
        print("Groq API responded, but the JSON-mode validation payload was unexpected.")
        return 1
    usage = body.get("usage", {})
    print(f"Groq API live check passed: model={model}; JSON mode=working; prompt_tokens={usage.get('prompt_tokens', 'n/a')}; completion_tokens={usage.get('completion_tokens', 'n/a')}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
