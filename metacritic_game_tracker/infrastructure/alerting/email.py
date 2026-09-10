"""Email delivery via Resend's HTTP API — no SMTP server needed.

`RESEND_API_KEY` comes from the environment (.env), never hardcoded. The
default sender (`onboarding@resend.dev`) works without a verified domain,
which is enough for a single-operator alert channel.
"""
from __future__ import annotations

import logging
import os

import resend

log = logging.getLogger(__name__)


def send_alert_email(subject: str, body: str) -> None:
    api_key = os.environ.get("RESEND_API_KEY")
    recipient = os.environ.get("ALERT_EMAIL_TO")
    if not api_key or not recipient:
        # A deployment that hasn't configured the alert channel still runs; the
        # underlying failure is already logged CRITICAL by its own caller.
        log.warning("Alert email not sent — RESEND_API_KEY/ALERT_EMAIL_TO unset: %s", subject)
        return

    resend.api_key = api_key
    resend.Emails.send(
        {
            "from": "onboarding@resend.dev",
            "to": recipient,
            "subject": f"[metacritic-game-tracker] {subject}",
            "text": body,
        }
    )
