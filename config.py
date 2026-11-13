import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_DATABASE = PROJECT_ROOT / "workforce.db"


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "local-development-only")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{DEFAULT_DATABASE.as_posix()}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    AUTO_SEED = os.environ.get("AUTO_SEED", "true").lower() == "true"
    SEED = 20261022
    HORIZON_START = os.environ.get("HORIZON_START", "2026-01-01")
    HORIZON_WEEKS = int(os.environ.get("HORIZON_WEEKS", "52"))
