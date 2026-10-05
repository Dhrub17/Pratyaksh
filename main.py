"""PRATYAKSH monitoring API.

  uvicorn app.main:app --reload            # http://localhost:8000/docs for interactive API docs
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import db
from .config import CORS_ORIGINS
from .routers import ingest, monitoring
from .seed import seed_if_empty
from .services.core import ServiceError


@asynccontextmanager
async def lifespan(app: FastAPI):
    con = db.connect()
    db.init(con)
    seed_if_empty(con)
    con.close()
    yield


app = FastAPI(title="PRATYAKSH API", version="0.1.0", lifespan=lifespan,
              description="AI-based real-time monitoring of training centres for attendance and infrastructure compliance.")
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS + ["*"], allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(ServiceError)
async def service_error(_: Request, exc: ServiceError):
    return JSONResponse(status_code=exc.status, content={"detail": exc.message})


@app.get("/api/v1/health", tags=["meta"])
def health():
    return {"status": "ok", "service": "pratyaksh", "version": app.version}


app.include_router(ingest.router)
app.include_router(monitoring.router)
