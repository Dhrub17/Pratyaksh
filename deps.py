from typing import Iterator, Optional

from fastapi import Header, HTTPException

from . import db
from .config import DASHBOARD_TOKEN


def get_db() -> Iterator:
    con = db.connect()
    try:
        yield con
    finally:
        con.close()


def dashboard_auth(authorization: Optional[str] = Header(default=None)) -> None:
    """Read APIs are open in demo mode. Set PRATYAKSH_DASHBOARD_TOKEN to require a bearer token."""
    if DASHBOARD_TOKEN and authorization != f"Bearer {DASHBOARD_TOKEN}":
        raise HTTPException(401, "Missing or invalid dashboard token")
