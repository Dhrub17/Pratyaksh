from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import PlainTextResponse

from ..config import ADMIN_KEY
from ..deps import dashboard_auth, get_db
from ..schemas import AlertUpdate, CentreIn
from ..services import core

router = APIRouter(prefix="/api/v1", tags=["monitoring"], dependencies=[Depends(dashboard_auth)])


@router.get("/dashboard/summary")
def summary(con=Depends(get_db)):
    return core.dashboard_summary(con)


@router.get("/centres")
def centres(state: Optional[str] = None, risk_level: Optional[str] = None, con=Depends(get_db)):
    return core.list_centres(con, state, risk_level)


@router.post("/centres", status_code=201)
def create_centre(body: CentreIn, con=Depends(get_db), x_admin_key: Optional[str] = Header(default=None)):
    if x_admin_key != ADMIN_KEY:
        raise HTTPException(401, "Admin key required")
    return core.create_centre(con, body.model_dump())


@router.get("/centres/{centre_id}")
def centre(centre_id: str, con=Depends(get_db)):
    return core.centre_detail(con, centre_id)


@router.get("/centres/{centre_id}/brief")
def brief(centre_id: str, con=Depends(get_db)):
    return core.brief(con, centre_id)


@router.get("/centres/{centre_id}/brief.txt", response_class=PlainTextResponse)
def brief_text(centre_id: str, con=Depends(get_db)):
    return core.brief(con, centre_id)["text"]


@router.get("/sessions/{session_id}")
def session(session_id: str, con=Depends(get_db)):
    return core.session_detail(con, session_id)


@router.get("/alerts")
def alerts(status: Optional[str] = None, severity: Optional[str] = None, centre_id: Optional[str] = None,
           limit: int = 200, con=Depends(get_db)):
    return core.list_alerts(con, status, severity, centre_id, min(limit, 1000))


@router.patch("/alerts/{alert_id}")
def update_alert(alert_id: int, body: AlertUpdate, con=Depends(get_db)):
    return core.update_alert(con, alert_id, body.status, body.note)


@router.get("/inspections/queue")
def queue(limit: int = 25, con=Depends(get_db)):
    return core.inspection_queue(con, limit)


@router.get("/fleet")
def fleet(con=Depends(get_db)):
    return core.fleet(con)


@router.post("/admin/rescore")
def rescore(con=Depends(get_db), x_admin_key: Optional[str] = Header(default=None)):
    if x_admin_key != ADMIN_KEY:
        raise HTTPException(401, "Admin key required")
    core.rescore_all(con)
    return {"status": "ok"}
