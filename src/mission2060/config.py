import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class SpotCredentials:
    host: str
    user: str | None = None
    password: str | None = None
    dock_id: int | None = None

def load_creds() -> SpotCredentials:
    host = os.getenv("SPOT_IP", "").strip()
    user = os.getenv("SPOT_USER", "").strip() or None
    password = os.getenv("SPOT_PASSWORD", "").strip() or None
    dock_id_raw = os.getenv("SPOT_DOCK_ID", "").strip()
    dock_id = int(dock_id_raw) if dock_id_raw.isdigit() else None

    if not host:
        raise RuntimeError("Missing SPOT_IP in .env")

    return SpotCredentials(host, user, password, dock_id)
