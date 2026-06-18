"""
Configuration for the 3D Printer Dashboard.

Secrets are read from environment variables or a local .env file. Keep .env out
of source control; use .env.example as the template for real deployments.
"""

import os
import secrets
from pathlib import Path


def _load_dotenv(path=".env"):
    env_path = Path(__file__).with_name(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _env_int(name, default):
    value = os.getenv(name)
    if value in (None, ""):
        return default
    return int(value)


def _env_float(name, default):
    value = os.getenv(name)
    if value in (None, ""):
        return default
    return float(value)


_load_dotenv()


# ---------------- PRINTERS ----------------
# Each entry is keyed by a short id used in URLs and in the UI.
PRINTERS = {
    "minimus": {
        "label": os.getenv("MINIMUS_LABEL", "Minimus"),
        "url": os.getenv("MINIMUS_URL", "http://127.0.0.1:5000"),
        "key": os.getenv("MINIMUS_API_KEY", ""),
        "camera": os.getenv(
            "MINIMUS_CAMERA_URL",
            "http://192.168.2.51/cam_Ender3minimus/?action=stream",
        ),
        "snapshot": os.getenv("MINIMUS_CAMERA_SNAPSHOT_URL", ""),
    },
    "sprite": {
        "label": os.getenv("SPRITE_LABEL", "Sprite"),
        "url": os.getenv("SPRITE_URL", "http://127.0.0.1:5001"),
        "key": os.getenv("SPRITE_API_KEY", ""),
        "camera": os.getenv(
            "SPRITE_CAMERA_URL",
            "http://192.168.2.51/cam_Ender3Sprite/?action=stream",
        ),
        "snapshot": os.getenv("SPRITE_CAMERA_SNAPSHOT_URL", ""),
    },
}


# ---------------- SERVER ----------------
HOST = os.getenv("HOST", "0.0.0.0")
PORT = _env_int("PORT", 8100)
UPDATE_INTERVAL = _env_float("UPDATE_INTERVAL", 2.0)
DATA_FILE = os.getenv(
    "DASHBOARD_DATA_FILE",
    str(Path(__file__).with_name("dashboard_data.json")),
)


# ---------------- AUTH ----------------
_configured_password = os.getenv("DASHBOARD_PASSWORD", "")
DASHBOARD_PASSWORD_GENERATED = not bool(_configured_password)
DASHBOARD_PASSWORD = _configured_password or secrets.token_urlsafe(18)

FLASK_SECRET_KEY_GENERATED = not bool(os.getenv("FLASK_SECRET_KEY", ""))
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY") or secrets.token_urlsafe(32)
SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "0") == "1"


# ---------------- NOTIFICATIONS ----------------
NOTIFY_TIMEOUT = _env_float("NOTIFY_TIMEOUT", 5.0)

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
NOTIFY_WEBHOOK_URL = os.getenv("NOTIFY_WEBHOOK_URL", "")
SMS_WEBHOOK_URL = os.getenv("SMS_WEBHOOK_URL", "")

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = _env_int("SMTP_PORT", 587)
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "1") == "1"
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USERNAME)
SMTP_TO = [
    addr.strip()
    for addr in os.getenv("SMTP_TO", "").split(",")
    if addr.strip()
]


# ---------------- CONTROL SAFETY LIMITS ----------------
CONTROL_TIMEOUT = _env_float("CONTROL_TIMEOUT", 5.0)
CAMERA_TIMEOUT = _env_float("CAMERA_TIMEOUT", 6.0)
FILAMENT_LOW_G = _env_float("FILAMENT_LOW_G", 100.0)
FILAMENT_DEFAULT_DIAMETER_MM = _env_float("FILAMENT_DEFAULT_DIAMETER_MM", 1.75)
FILAMENT_DEFAULT_DENSITY_G_CM3 = _env_float("FILAMENT_DEFAULT_DENSITY_G_CM3", 1.24)
JOG_SPEED = _env_int("JOG_SPEED", 3000)
MAX_JOG_MM = _env_float("MAX_JOG_MM", 50.0)
MAX_EXTRUDE_MM = _env_float("MAX_EXTRUDE_MM", 100.0)
MAX_HOTEND_TEMP = _env_float("MAX_HOTEND_TEMP", 300.0)
MAX_BED_TEMP = _env_float("MAX_BED_TEMP", 120.0)
