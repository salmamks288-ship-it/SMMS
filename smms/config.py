import os
from datetime import datetime, timezone

def _load_dotenv():
    """Read KEY=VALUE lines from a .env file in the project folder (no extra package needed). Real environment variables win."""
    path = os.path.join(os.path.dirname(__file__), "..", ".env")
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1); os.environ.setdefault(k.strip(), v.strip().strip("\"'"))
    except OSError:
        pass
_load_dotenv()

class Config:
    SECRET_KEY = os.environ.get("SMMS_SECRET_KEY", "dev-secret-change-me")
    DATABASE = os.environ.get("SMMS_DATABASE", os.path.join(os.path.dirname(__file__), "..", "smms.db"))
    # Session lifetimes (NFR-16): 30 min visitors, 15 min staff/manager/admin
    SESSION_MINUTES = {"Visitor": 30, "Staff": 15, "Manager": 15, "ITAdmin": 15}
    LOCK_AFTER_FAILURES = 5          # NFR-16
    LOCK_MINUTES = 15                # NFR-16
    HOLD_MINUTES = 10                # FR-19
    RESET_LINK_MINUTES = 30          # FR-05
    ENTRY_GRACE_MINUTES = 15         # FR-24 (grace period set by management)
    CHATBOT_THRESHOLD = 0.20         # minimum relevance for an answer (FR-32)
    MAX_AR_MB = 20                   # NFR-05
    DEV_MODE = os.environ.get("SMMS_DEV", "1") == "1"   # returns e-mail links in responses
    HELPDESK = "Help desk: +971 2 000 0000 / helpdesk@smms.example"
    # Slot dates/times, "today" and the cancellation deadline are museum wall-clock time. NOW() stays UTC (stored timestamps, JWT).
    MUSEUM_UTC_OFFSET_HOURS = int(os.environ.get("SMMS_TZ_OFFSET", "4"))   # UAE = UTC+4
    AUDIT_RETENTION_DAYS = 365       # FR-43: audit log kept 12 months
    NOW = staticmethod(lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    # Chatbot language model (real-time streamed answers). Without ANTHROPIC_API_KEY the chatbot falls back to the knowledge-base-only mode.
    LLM_MODEL = os.environ.get("SMMS_LLM_MODEL", "claude-haiku-5-5")
    LLM_TIMEOUT_SECONDS = 30
    TESTING = False
