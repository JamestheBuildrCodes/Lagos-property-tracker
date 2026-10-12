"""Alert the internal owner when a scheduled scan fails before report delivery."""
from __future__ import annotations

import json
import os
from pathlib import Path

from mailjet_sender import send_message, valid_email


def successful_report_receipt() -> bool:
    current_run_id = os.environ.get("GITHUB_RUN_ID", "").strip()
    for path in (
        Path("mailjet_layer1_receipt.json"),
        Path("data/mailjet_layer1_receipt.json"),
    ):
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            custom_id = str(payload.get("custom_id") or "")
            # Historical receipts are archived in data/. Only a successful
            # receipt from THIS workflow run can suppress its failure alert.
            if current_run_id and f"-{current_run_id}-" not in custom_id:
                continue
            statuses = [
                item.get("status")
                for item in payload.get("message_results", [])
            ]
            if statuses and all(status == "success" for status in statuses):
                return True
        except (OSError, json.JSONDecodeError):
            continue
    return False


def main() -> int:
    if successful_report_receipt():
        print("A successful report email receipt exists; failure alert not needed.")
        return 0

    recipient = os.environ.get("REPORT_TO_EMAIL", "").strip()
    if not valid_email(recipient):
        raise SystemExit("Cannot alert: REPORT_TO_EMAIL is missing or invalid.")
    run_url = os.environ.get("GITHUB_RUN_URL", "").strip()
    run_name = os.environ.get("GITHUB_WORKFLOW", "Nigeria Property Market Scan")
    subject = "ACTION REQUIRED: Lagos Property Tracker scan failed"
    text = (
        "The automated property-market scan failed before a successful final "
        "report-delivery receipt was recorded. No client report should be "
        "assumed to have been delivered.\n\n"
        f"Workflow: {run_name}\n"
        f"Run details: {run_url or 'Open the repository Actions tab'}\n\n"
        "Open the failed workflow step, resolve the source/API/billing or "
        "publication error, then rerun the workflow. Do not send the old "
        "snapshot as if it were current."
    )
    html = (
        "<p><strong>The automated property-market scan failed.</strong></p>"
        "<p>No successful final report-delivery receipt was recorded. "
        "Do not assume the client received a report.</p>"
        f"<p>Workflow: {run_name}</p>"
        f"<p><a href=\"{run_url}\">Open failed workflow run</a></p>"
        "<p>Resolve the failing source/API/billing or publication step, then "
        "rerun the workflow. Do not send an old snapshot as current data.</p>"
    )
    send_message(
        to=[recipient],
        subject=subject,
        text_body=text,
        html_body=html,
        layer="failure-alert",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
