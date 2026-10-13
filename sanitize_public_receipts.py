"""Redact email addresses from Mailjet receipt files committed to this public repository."""
from __future__ import annotations

import json
from pathlib import Path


def mask_email(value: str) -> str:
    if "@" not in value:
        return value
    local, domain = value.split("@", 1)
    if "***" in local:
        return value
    return f"{local[:1]}***@{domain}"


def redact(value):
    changed = False
    if isinstance(value, dict):
        for key, item in list(value.items()):
            if key.lower() in {"email", "emailaddress"} and isinstance(item, str) and "@" in item:
                masked = mask_email(item)
                if masked != item:
                    value[key] = masked
                    changed = True
            else:
                new_value, nested_changed = redact(item)
                value[key] = new_value
                changed = changed or nested_changed
        return value, changed
    if isinstance(value, list):
        out = []
        for item in value:
            new_value, nested_changed = redact(item)
            out.append(new_value)
            changed = changed or nested_changed
        return out, changed
    return value, False


def main() -> int:
    files = sorted(Path("data").glob("mailjet_*_receipt.json"))
    changed_files = []
    for path in files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        safe_payload, changed = redact(payload)
        if changed:
            path.write_text(
                json.dumps(safe_payload, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            changed_files.append(path)
    if changed_files:
        print("Redacted recipient addresses from: " + ", ".join(str(p) for p in changed_files))
    else:
        print("No unredacted recipient addresses found in archived Mailjet receipts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
