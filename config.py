import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("PRATYAKSH_DB", BASE_DIR / "pratyaksh.db"))
CORS_ORIGINS = [o.strip() for o in os.getenv("PRATYAKSH_CORS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()]
ADMIN_KEY = os.getenv("PRATYAKSH_ADMIN_KEY", "admin-demo-key")          # change in production
DASHBOARD_TOKEN = os.getenv("PRATYAKSH_DASHBOARD_TOKEN")               # optional bearer token for read APIs
SCORE_WINDOW_DAYS = int(os.getenv("PRATYAKSH_SCORE_WINDOW_DAYS", "14"))
EVIDENCE_RETENTION_DAYS = int(os.getenv("PRATYAKSH_EVIDENCE_RETENTION_DAYS", "30"))
