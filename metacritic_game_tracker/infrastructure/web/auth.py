"""HTTP Basic Auth for the operator console (FR-022/026) — a single
username/password pair from `.env`, never in code."""
from __future__ import annotations

import os
import secrets

from fastapi import Depends, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials

_security = HTTPBasic()


def require_operator(credentials: HTTPBasicCredentials = Depends(_security)) -> str:
    user_ok = secrets.compare_digest(credentials.username, os.environ["MONITORING_USERNAME"])
    pass_ok = secrets.compare_digest(credentials.password, os.environ["MONITORING_PASSWORD"])
    if not (user_ok and pass_ok):
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username
