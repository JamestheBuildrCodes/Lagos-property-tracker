"""Send Layer 1 executive brief to the configured distribution."""
from __future__ import annotations
import os,sys
from pathlib import Path
import resend
from report_builder import build_executive_html

def recipients(primary="",client=""):
    raw=",".join(x for x in (primary,client) if x)
    return list(dict.fromkeys(x.strip() for x in raw.split(",") if "@" in x.strip()))

def send_report(to_emails,html_body):
    if not resend.api_key: raise RuntimeError("RESEND_API_KEY is missing")
    tos=recipients(*to_emails) if isinstance(to_emails,tuple) else recipients(to_emails)
    if not tos: raise RuntimeError("No valid email recipients configured")
    resend.Emails.send({"from":"Lagos Property Report <onboarding@resend.dev>","to":tos,
        "subject":"Lagos Property Market — Weekly Intelligence Brief","html":html_body})
    print("Executive brief sent to: "+", ".join(tos))

def run():
    if len(sys.argv)<2: raise SystemExit("Usage: python email_report.py <listings.csv> [changes.csv] [to_email] [html_path]")
    listings=sys.argv[1]; changes=sys.argv[2] if len(sys.argv)>2 else "none"
    primary=sys.argv[3] if len(sys.argv)>3 else os.environ.get("REPORT_TO_EMAIL","")
    html_path=sys.argv[4] if len(sys.argv)>4 else ""
    html=Path(html_path).read_text(encoding="utf-8") if html_path and Path(html_path).exists() else build_executive_html(listings,changes)
    send_report((primary,os.environ.get("REPORT_CLIENT_EMAIL","")),html)

if __name__=="__main__": run()
