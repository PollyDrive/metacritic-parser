"""Email delivery via Resend's HTTP API — no SMTP server needed.

`RESEND_API_KEY` comes from the environment (.env), never hardcoded. The
default sender (`onboarding@resend.dev`) works without a verified domain,
which is enough for a single-operator alert channel.
"""
from __future__ import annotations

import os

import resend


def send_alert_email(subject: str, body: str) -> None:
    resend.api_key = os.environ["RESEND_API_KEY"]
    resend.Emails.send(
        {
            "from": "onboarding@resend.dev",
            "to": os.environ["ALERT_EMAIL_TO"],
            "subject": f"[metacritic-game-tracker] {subject}",
            "text": body,
        }
    )
