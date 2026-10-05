from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import ValidationError

from ..config import ADMIN_KEY
from ..deps import get_db
from ..schemas import RegisterIn, SessionEvent
from ..services import core

router = APIRouter(prefix="/api/v1", tags=["edge ingest"])


@router.post("/ingest/events", status_code=201, summary="Edge device uploads one hash-chained session event")
async def ingest(request: Request, con=Depends(get_db), x_device_key: Optional[str] = Header(default=None)):
    try:
        raw = await request.json()             # keep the raw dict: the hash covers every field
        if not isinstance(raw, dict):
            raise HTTPException(422, "Event must be a JSON object")
        SessionEvent.model_validate(raw)       # schema validation
    except ValidationError as exc:
        raise HTTPException(422, [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]) from exc
    except ValueError as exc:
        raise HTTPException(400, f"Invalid JSON: {exc}") from exc
    return core.ingest_event(con, raw, x_device_key, ADMIN_KEY)


@router.post("/centres/{centre_id}/attendance", status_code=201,
             summary="Attendance register (claimed count) for a session, from the scheme MIS or centre")
def register(centre_id: str, body: RegisterIn, con=Depends(get_db), x_device_key: Optional[str] = Header(default=None)):
    return core.submit_register(con, centre_id, body.model_dump(), x_device_key, ADMIN_KEY)
