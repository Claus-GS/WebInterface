import csv
import hashlib
import io
import json
import math
import os
import secrets
import smtplib
import sys
import threading
import time
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from email.message import EmailMessage
from functools import wraps
from hmac import compare_digest
from pathlib import Path

import psutil
import requests
from flask import (
    Flask,
    Response,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_socketio import SocketIO

import config

# Root of the drive the app runs from ("C:\\" on Windows, "/" on Linux).
# psutil.disk_usage("/") raises on Windows, so resolve a valid path once.
DISK_PATH = os.path.abspath(os.sep)
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
ALLOWED_AXES = {"x", "y", "z"}
OCTOPRINT_OK = {200, 201, 204}

app = Flask(__name__)
app.secret_key = config.FLASK_SECRET_KEY
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Strict",
    SESSION_COOKIE_SECURE=config.SESSION_COOKIE_SECURE,
)
socketio = SocketIO(app, async_mode="threading")

PRINTERS = config.PRINTERS
DATA_PATH = Path(config.DATA_FILE)
DATA_LOCK = threading.Lock()
TRACKER_LOCK = threading.Lock()
HEALTH_LOCK = threading.Lock()
PRINT_TRACKER = {}
PRINTER_HEALTH = {}
HISTORY_LIMIT = 200
ACTIVITY_LIMIT = 300
ACTIVITY_SEVERITIES = {"ok", "info", "warn", "danger"}
HISTORY_STATUSES = {"finished", "cancelled", "failed"}


def _now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _default_filament():
    return {
        "brand": "",
        "material": "PLA",
        "color": "",
        "spool_weight_g": 1000.0,
        "remaining_g": 0.0,
        "cost": 0.0,
        "diameter_mm": config.FILAMENT_DEFAULT_DIAMETER_MM,
        "density_g_cm3": config.FILAMENT_DEFAULT_DENSITY_G_CM3,
        "low_threshold_g": config.FILAMENT_LOW_G,
        "auto_deduct": True,
        "notes": "",
    }


def _empty_data():
    return {
        "history": [],
        "activity": [],
        "filament": {pid: _default_filament() for pid in PRINTERS},
        "maintenance": [],
        "control_locks": {pid: False for pid in PRINTERS},
    }


def _stable_record_id(prefix, index, item):
    payload = json.dumps(item, sort_keys=True, default=str)
    digest = hashlib.sha1(f"{prefix}:{index}:{payload}".encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _normalize_records(items, limit=None, prefix="record"):
    if not isinstance(items, list):
        return []

    records = []
    for index, item in enumerate(items[:limit]):
        if not isinstance(item, dict):
            continue
        record = dict(item)
        if not record.get("id"):
            record["id"] = _stable_record_id(prefix, index, record)
        records.append(record)
    return records


def _normalize_data(data):
    if not isinstance(data, dict):
        data = {}

    normalized = _empty_data()

    history = data.get("history", [])
    if isinstance(history, list):
        normalized["history"] = _normalize_records(history, HISTORY_LIMIT, "history")

    activity = data.get("activity", [])
    if isinstance(activity, list):
        normalized["activity"] = _normalize_records(activity, ACTIVITY_LIMIT, "activity")

    filament = data.get("filament", {})
    if isinstance(filament, dict):
        for pid in PRINTERS:
            current = filament.get(pid, {})
            if isinstance(current, dict):
                merged = _default_filament()
                merged.update(current)
                normalized["filament"][pid] = merged

    maintenance = data.get("maintenance", [])
    if isinstance(maintenance, list):
        normalized["maintenance"] = _normalize_records(maintenance, prefix="maintenance")

    locks = data.get("control_locks", {})
    if isinstance(locks, dict):
        for pid in PRINTERS:
            normalized["control_locks"][pid] = bool(locks.get(pid, False))

    return normalized


def _read_data_unlocked():
    if not DATA_PATH.exists():
        return _empty_data()

    try:
        data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_data()

    return _normalize_data(data)


def _save_data_unlocked(data):
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = DATA_PATH.with_suffix(DATA_PATH.suffix + ".tmp")
    content = json.dumps(data, indent=2)
    try:
        tmp_path.write_text(content, encoding="utf-8")
        tmp_path.replace(DATA_PATH)
    except PermissionError:
        DATA_PATH.write_text(content, encoding="utf-8")
        try:
            tmp_path.unlink()
        except OSError:
            pass


def _get_data():
    with DATA_LOCK:
        return deepcopy(_read_data_unlocked())


def _update_data(mutator):
    with DATA_LOCK:
        data = _read_data_unlocked()
        result = mutator(data)
        _save_data_unlocked(data)
        return result


def _clean_text(value, max_len=160):
    return str(value or "").strip()[:max_len]


def _clean_float(value, name, minimum=0.0, maximum=1000000.0):
    parsed = _finite_float(value, name)
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{name} must be between {minimum:g} and {maximum:g}")
    return parsed


def _safe_float(value, default=0.0):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(parsed):
        return default
    return parsed


def _notification_channels():
    return {
        "browser": True,
        "email": bool(config.SMTP_HOST and config.SMTP_TO and config.SMTP_FROM),
        "discord": bool(config.DISCORD_WEBHOOK_URL),
        "telegram": bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID),
        "webhook": bool(config.NOTIFY_WEBHOOK_URL),
        "sms": bool(config.SMS_WEBHOOK_URL),
    }


def _history_stats(history):
    total = len(history)
    finished = sum(1 for item in history if item.get("status") == "finished")
    failed = sum(1 for item in history if item.get("status") == "failed")
    cancelled = sum(1 for item in history if item.get("status") == "cancelled")
    filament_used_g = round(sum(_safe_float(item.get("filament_used_g"), 0) for item in history), 1)
    filament_cost = round(sum(_safe_float(item.get("filament_cost"), 0) for item in history), 2)
    success_rate = round((finished / total) * 100, 1) if total else 0.0
    return {
        "total": total,
        "finished": finished,
        "failed": failed,
        "cancelled": cancelled,
        "filament_used_g": filament_used_g,
        "filament_cost": filament_cost,
        "success_rate": success_rate,
    }


def _density_for_material(material):
    densities = {
        "PLA": 1.24,
        "PLA+": 1.24,
        "PETG": 1.27,
        "ABS": 1.04,
        "ASA": 1.07,
        "TPU": 1.21,
        "NYLON": 1.14,
        "PA": 1.14,
        "PC": 1.20,
        "PVA": 1.23,
    }
    return densities.get(str(material or "").strip().upper(), config.FILAMENT_DEFAULT_DENSITY_G_CM3)


def _filament_length_mm(job):
    filament = (job.get("job") or {}).get("filament") or {}
    if not isinstance(filament, dict):
        return 0.0

    total = 0.0
    for info in filament.values():
        if isinstance(info, dict):
            try:
                total += float(info.get("length") or 0)
            except (TypeError, ValueError):
                continue
    return round(total, 1)


def _grams_from_length(length_mm, filament):
    if length_mm <= 0:
        return 0.0
    diameter = _safe_float(filament.get("diameter_mm"), config.FILAMENT_DEFAULT_DIAMETER_MM)
    density = _safe_float(filament.get("density_g_cm3"), _density_for_material(filament.get("material")))
    radius = diameter / 2
    volume_mm3 = math.pi * radius * radius * length_mm
    return round((volume_mm3 / 1000) * density, 2)


def _apply_filament_usage(data, entry):
    pid = entry.get("printer")
    length_mm = float(entry.get("filament_used_mm") or 0)
    if pid not in data["filament"] or length_mm <= 0:
        return entry

    filament = data["filament"][pid]
    used_g = _grams_from_length(length_mm, filament)
    spool_g = _safe_float(filament.get("spool_weight_g"), 0)
    cost = _safe_float(filament.get("cost"), 0)
    cost_per_g = cost / spool_g if spool_g > 0 else 0

    entry["filament_used_g"] = used_g
    entry["filament_cost"] = round(used_g * cost_per_g, 2)
    entry["filament_material"] = filament.get("material") or ""

    if filament.get("auto_deduct", True):
        remaining = max(0.0, _safe_float(filament.get("remaining_g"), 0) - used_g)
        filament["remaining_g"] = round(remaining, 1)
        threshold = _safe_float(filament.get("low_threshold_g"), config.FILAMENT_LOW_G)
        entry["filament_remaining_g"] = filament["remaining_g"]
        if remaining <= threshold:
            entry["filament_low"] = True

    return entry


def _record_activity(action, printer=None, detail="", severity="info"):
    entry = {
        "id": uuid.uuid4().hex,
        "at": _now_iso(),
        "action": _clean_text(action, 80),
        "printer": printer or "",
        "printer_label": PRINTERS.get(printer, {}).get("label", "") if printer else "",
        "detail": _clean_text(detail, 240),
        "severity": severity,
    }

    def add_activity(data):
        data["activity"].insert(0, entry)
        del data["activity"][ACTIVITY_LIMIT:]
        return entry

    saved = _update_data(add_activity)
    socketio.emit("activity_event", saved)
    return saved


def _default_health(pid):
    return {
        "printer": pid,
        "label": PRINTERS[pid]["label"],
        "online": False,
        "configured": bool(PRINTERS[pid].get("key")),
        "latency_ms": None,
        "last_ok": None,
        "last_error": "Not checked yet",
    }


def _set_printer_health(pid, **updates):
    with HEALTH_LOCK:
        health = PRINTER_HEALTH.get(pid, _default_health(pid))
        health.update(updates)
        PRINTER_HEALTH[pid] = health
        return deepcopy(health)


def _get_printer_health():
    with HEALTH_LOCK:
        return {
            pid: deepcopy(PRINTER_HEALTH.get(pid, _default_health(pid)))
            for pid in PRINTERS
        }


def _camera_snapshot_url(printer):
    configured = PRINTERS[printer].get("snapshot")
    if configured:
        return configured

    camera_url = PRINTERS[printer].get("camera", "")
    if "action=stream" in camera_url:
        return camera_url.replace("action=stream", "action=snapshot")
    if "action=cam" in camera_url:
        return camera_url.replace("action=cam", "action=snapshot")
    return ""


def _print_event_message(entry):
    printer = entry.get("printer_label") or entry.get("printer") or "Printer"
    status = entry.get("status", "updated")
    file_name = entry.get("file_name") or "Unknown file"
    duration = int(entry.get("duration_s") or 0)
    minutes = max(0, duration // 60)
    return f"{printer}: print {status} - {file_name} ({minutes}m)"


def _send_external_notifications(entry):
    message = _print_event_message(entry)
    payload = {"event": "print_status", "message": message, "print": entry}

    def post_json(url, body, label):
        try:
            requests.post(url, json=body, timeout=config.NOTIFY_TIMEOUT)
        except Exception as exc:
            print(f"{label} notification failed: {exc}")

    if config.DISCORD_WEBHOOK_URL:
        post_json(config.DISCORD_WEBHOOK_URL, {"content": message}, "Discord")

    if config.NOTIFY_WEBHOOK_URL:
        post_json(config.NOTIFY_WEBHOOK_URL, payload, "Webhook")

    if config.SMS_WEBHOOK_URL:
        post_json(config.SMS_WEBHOOK_URL, payload, "SMS webhook")

    if config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID:
        telegram_url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
        post_json(
            telegram_url,
            {"chat_id": config.TELEGRAM_CHAT_ID, "text": message},
            "Telegram",
        )

    if config.SMTP_HOST and config.SMTP_TO and config.SMTP_FROM:
        try:
            msg = EmailMessage()
            msg["Subject"] = f"Printer dashboard: {entry.get('status', 'print update')}"
            msg["From"] = config.SMTP_FROM
            msg["To"] = ", ".join(config.SMTP_TO)
            msg.set_content(message)

            with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=config.NOTIFY_TIMEOUT) as smtp:
                if config.SMTP_USE_TLS:
                    smtp.starttls()
                if config.SMTP_USERNAME:
                    smtp.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
                smtp.send_message(msg)
        except Exception as exc:
            print(f"Email notification failed: {exc}")


def _queue_notifications(entry):
    socketio.emit("print_event", entry)
    threading.Thread(
        target=_send_external_notifications,
        args=(deepcopy(entry),),
        daemon=True,
    ).start()


def _record_history(entry):
    entry = dict(entry)
    entry.setdefault("id", uuid.uuid4().hex)
    entry.setdefault("ended_at", _now_iso())

    def add_event(data):
        _apply_filament_usage(data, entry)
        data["history"].insert(0, entry)
        del data["history"][HISTORY_LIMIT:]
        return entry

    saved = _update_data(add_event)
    severity = "ok" if saved.get("status") == "finished" else "warn"
    if saved.get("status") == "failed":
        severity = "danger"
    _record_activity(
        f"Print {saved.get('status', 'updated')}",
        saved.get("printer"),
        saved.get("file_name", ""),
        severity,
    )
    if saved.get("filament_low"):
        _record_activity(
            "Filament low",
            saved.get("printer"),
            f"{saved.get('filament_remaining_g', 0)}g remaining",
            "warn",
        )
    _queue_notifications(saved)
    return saved


def _is_print_active_state(state):
    state = state.lower()
    return ("print" in state or "pause" in state) and "not configured" not in state


def _is_print_closed_state(state):
    state = state.lower()
    return (
        "operational" in state
        or "error" in state
        or "closed" in state
        or "cancel" in state
    )


def _job_file_name(job):
    return (
        ((job.get("job") or {}).get("file") or {}).get("name")
        or ((job.get("job") or {}).get("file") or {}).get("path")
        or "Unknown file"
    )


def _job_progress(job):
    progress = (job.get("progress") or {}).get("completion")
    return progress if isinstance(progress, (int, float)) else 0.0


def _track_print_event(pid, printer, job):
    state = ((printer.get("state") or {}).get("text") or "").lower()
    progress = _job_progress(job)
    now = time.time()

    with TRACKER_LOCK:
        current = PRINT_TRACKER.get(pid)

        if _is_print_active_state(state):
            if not current:
                PRINT_TRACKER[pid] = {
                    "file_name": _job_file_name(job),
                    "started_at": _now_iso(),
                    "started_ts": now,
                    "last_progress": progress,
                    "last_print_time": (job.get("progress") or {}).get("printTime") or 0,
                    "filament_used_mm": _filament_length_mm(job),
                    "requested_cancel": False,
                    "emergency": False,
                }
            else:
                current["file_name"] = _job_file_name(job) or current["file_name"]
                current["last_progress"] = progress
                current["last_print_time"] = (job.get("progress") or {}).get("printTime") or current.get("last_print_time", 0)
                current["filament_used_mm"] = max(
                    current.get("filament_used_mm", 0),
                    _filament_length_mm(job),
                )
            return None

        if not current or not _is_print_closed_state(state):
            return None

        if current.get("emergency") or "error" in state:
            status = "failed"
        elif current.get("requested_cancel") or progress < 99:
            status = "cancelled"
        else:
            status = "finished"

        duration = int(current.get("last_print_time") or max(0, now - current.get("started_ts", now)))
        entry = {
            "printer": pid,
            "printer_label": PRINTERS[pid]["label"],
            "file_name": current.get("file_name") or _job_file_name(job),
            "status": status,
            "started_at": current.get("started_at"),
            "ended_at": _now_iso(),
            "duration_s": duration,
            "progress": round(progress, 1),
            "filament_used_mm": round(current.get("filament_used_mm", 0), 1),
        }
        del PRINT_TRACKER[pid]

    return _record_history(entry)


def _mark_cancel_requested(pid):
    with TRACKER_LOCK:
        if pid in PRINT_TRACKER:
            PRINT_TRACKER[pid]["requested_cancel"] = True


def _mark_emergency_requested(pid):
    with TRACKER_LOCK:
        current = PRINT_TRACKER.get(pid)
        if current:
            current["emergency"] = True
            entry = {
                "printer": pid,
                "printer_label": PRINTERS[pid]["label"],
                "file_name": current.get("file_name") or "Unknown file",
                "status": "failed",
                "started_at": current.get("started_at"),
                "ended_at": _now_iso(),
                "duration_s": int(time.time() - current.get("started_ts", time.time())),
                "progress": round(current.get("last_progress", 0.0), 1),
                "filament_used_mm": round(current.get("filament_used_mm", 0), 1),
                "note": "Firmware emergency stop sent",
            }
            del PRINT_TRACKER[pid]
        else:
            entry = None

    if entry:
        _record_history(entry)


def _set_control_locked(pid, locked):
    def update_lock(data):
        data["control_locks"][pid] = bool(locked)
        return data["control_locks"][pid]

    return _update_data(update_lock)


def _is_control_locked(pid):
    return bool(_get_data()["control_locks"].get(pid, False))


def _locked_response(pid):
    if _is_control_locked(pid):
        label = PRINTERS.get(pid, {}).get("label", pid)
        return jsonify({"ok": False, "error": f"{label} controls are locked"}), 423
    return None


def _safe_next(default="/"):
    next_url = request.values.get("next") or default
    if not next_url.startswith("/") or next_url.startswith("//"):
        return default
    return next_url


def _is_authenticated():
    return bool(session.get("authenticated"))


def _csrf_token():
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def _check_csrf():
    expected = session.get("csrf_token")
    provided = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
    return bool(expected and provided and compare_digest(expected, provided))


@app.before_request
def require_authentication():
    if request.endpoint in {"login", "static"}:
        return None

    if not _is_authenticated():
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": "authentication required"}), 401
        return redirect(url_for("login", next=request.path))

    if request.method not in SAFE_METHODS and not _check_csrf():
        return jsonify({"ok": False, "error": "invalid csrf token"}), 403

    return None


def control_endpoint(fn):
    @wraps(fn)
    def wrapper(printer, *args, **kwargs):
        url, headers, error = _printer_conn(printer)
        if error:
            return jsonify({"ok": False, "error": error}), 400 if error == "bad printer" else 503
        return fn(printer, url, headers, *args, **kwargs)

    return wrapper


def _printer_conn(printer_id):
    """Return (url, headers, error) for a printer id."""
    p = PRINTERS.get(printer_id)
    if not p:
        return None, None, "bad printer"
    if not p.get("key"):
        return None, None, "printer api key is not configured"
    return p["url"].rstrip("/"), {"X-Api-Key": p["key"]}, None


def _json_object():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError("request body must be a JSON object")
    return data


def _finite_float(value, name):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number") from None

    if not math.isfinite(parsed):
        raise ValueError(f"{name} must be finite")
    return parsed


def _bounded_float(value, name, minimum, maximum):
    parsed = _finite_float(value, name)
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{name} must be between {minimum:g} and {maximum:g}")
    return parsed


def _post_octoprint(url, headers, path, payload):
    response = requests.post(
        f"{url}{path}",
        headers=headers,
        json=payload,
        timeout=config.CONTROL_TIMEOUT,
    )
    if response.status_code not in OCTOPRINT_OK:
        detail = response.text.strip()[:300] or f"HTTP {response.status_code}"
        return False, detail
    return True, None


def fetch_octoprint(printer_id, url, headers):
    started = time.perf_counter()
    ok = True
    errors = []

    try:
        printer_response = requests.get(f"{url}/api/printer", headers=headers, timeout=3)
        printer_response.raise_for_status()
        printer = printer_response.json()
    except Exception as exc:
        ok = False
        errors.append(f"printer: {exc}")
        printer = {}

    try:
        job_response = requests.get(f"{url}/api/job", headers=headers, timeout=3)
        job_response.raise_for_status()
        job = job_response.json()
    except Exception as exc:
        ok = False
        errors.append(f"job: {exc}")
        job = {}

    latency_ms = int((time.perf_counter() - started) * 1000)
    _set_printer_health(
        printer_id,
        online=ok,
        configured=True,
        latency_ms=latency_ms,
        last_ok=_now_iso() if ok else _get_printer_health().get(printer_id, {}).get("last_ok"),
        last_error=None if ok else "; ".join(errors)[:240],
    )
    return printer, job


def fetch_system():
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage(DISK_PATH)
    cpu = psutil.cpu_percent(interval=None)
    uptime = int(time.time() - psutil.boot_time())

    return {
        "cpu": cpu,
        "mem_used": round(mem.used / (1024**3), 1),
        "mem_total": round(mem.total / (1024**3), 1),
        "mem_percent": mem.percent,
        "disk_used": round(disk.used / (1024**3), 1),
        "disk_total": round(disk.total / (1024**3), 1),
        "disk_percent": disk.percent,
        "uptime": uptime,
    }


def data_loop():
    while True:
        try:
            printers = {}
            for pid, p in PRINTERS.items():
                if not p.get("key"):
                    _set_printer_health(
                        pid,
                        online=False,
                        configured=False,
                        latency_ms=None,
                        last_error="Printer API key is not configured",
                    )
                    printers[pid] = {
                        "printer": {"state": {"text": "Not configured"}},
                        "job": {},
                    }
                    continue

                headers = {"X-Api-Key": p["key"]}
                printer, job = fetch_octoprint(pid, p["url"].rstrip("/"), headers)
                _track_print_event(pid, printer, job)
                printers[pid] = {"printer": printer, "job": job}

            socketio.emit(
                "update",
                {
                    "printers": printers,
                    "system": fetch_system(),
                    "health": _get_printer_health(),
                },
            )
        except Exception as e:
            # Never let one bad reading kill the update thread.
            print(f"data_loop error: {e}")

        socketio.sleep(config.UPDATE_INTERVAL)


@socketio.on("connect")
def handle_socket_connect():
    if not _is_authenticated():
        return False
    return None


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        password = request.form.get("password", "")
        if compare_digest(password, config.DASHBOARD_PASSWORD):
            session.clear()
            session["authenticated"] = True
            _csrf_token()
            return redirect(_safe_next())
        error = "Invalid password"

    return render_template("login.html", error=error, next_url=_safe_next())


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
def index():
    ui_printers = {
        pid: {"label": p["label"], "camera": p["camera"]}
        for pid, p in PRINTERS.items()
    }
    return render_template("index.html", printers=ui_printers, csrf_token=_csrf_token())


@app.route("/api/dashboard-data")
def dashboard_data():
    data = _get_data()
    return jsonify(
        {
            "ok": True,
            "history": data["history"],
            "history_stats": _history_stats(data["history"]),
            "activity": data["activity"],
            "filament": data["filament"],
            "maintenance": data["maintenance"],
            "control_locks": data["control_locks"],
            "notification_channels": _notification_channels(),
            "health": _get_printer_health(),
        }
    )


@app.route("/api/history/export.csv")
def export_history_csv():
    data = _get_data()
    output = io.StringIO()
    fields = [
        "ended_at",
        "started_at",
        "printer_label",
        "file_name",
        "status",
        "duration_s",
        "progress",
        "filament_used_mm",
        "filament_used_g",
        "filament_cost",
        "filament_material",
        "filament_remaining_g",
        "note",
    ]
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(data["history"])
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=printer-print-history.csv"
        },
    )


@app.route("/api/dashboard-data/export")
def export_dashboard_data():
    payload = {
        "exported_at": _now_iso(),
        "app": "3D Printer Dashboard",
        "data": _get_data(),
    }
    body = json.dumps(payload, indent=2)
    return Response(
        body,
        mimetype="application/json",
        headers={
            "Content-Disposition": "attachment; filename=printer-dashboard-data.json"
        },
    )


@app.route("/api/history/<entry_id>", methods=["POST"])
def update_history(entry_id):
    try:
        data = _json_object()
        printer = _clean_text(data.get("printer"), 40)
        if printer and printer not in PRINTERS:
            raise ValueError("bad printer")

        status = _clean_text(data.get("status"), 24).lower() or "finished"
        if status not in HISTORY_STATUSES:
            raise ValueError("status must be finished, cancelled, or failed")

        update = {
            "printer": printer,
            "printer_label": PRINTERS.get(printer, {}).get("label", "") if printer else "",
            "file_name": _clean_text(data.get("file_name"), 180) or "Unknown file",
            "status": status,
            "duration_s": int(_clean_float(data.get("duration_s", 0), "duration", 0, 365 * 24 * 3600)),
            "progress": round(_clean_float(data.get("progress", 0), "progress", 0, 100), 1),
            "filament_used_g": round(_clean_float(data.get("filament_used_g", 0), "filament used", 0, 100000), 1),
            "filament_cost": round(_clean_float(data.get("filament_cost", 0), "filament cost", 0, 100000), 2),
            "filament_material": _clean_text(data.get("filament_material"), 40),
            "note": _clean_text(data.get("note"), 300),
            "edited_at": _now_iso(),
        }

        ended_at = _clean_text(data.get("ended_at"), 40)
        if ended_at:
            datetime.fromisoformat(ended_at.replace("Z", "+00:00"))
            update["ended_at"] = ended_at
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    def edit_entry(store):
        for entry in store["history"]:
            if entry.get("id") == entry_id:
                entry.update(update)
                return entry
        return None

    saved = _update_data(edit_entry)
    if not saved:
        return jsonify({"ok": False, "error": "history entry not found"}), 404

    _record_activity("Print history edited", saved.get("printer"), saved.get("file_name", ""), "info")
    return jsonify({"ok": True, "history": saved})


@app.route("/api/history/<entry_id>/delete", methods=["POST"])
def delete_history(entry_id):
    def remove_entry(store):
        for index, entry in enumerate(store["history"]):
            if entry.get("id") == entry_id:
                return store["history"].pop(index)
        return None

    deleted = _update_data(remove_entry)
    if not deleted:
        return jsonify({"ok": False, "error": "history entry not found"}), 404

    _record_activity("Print history deleted", deleted.get("printer"), deleted.get("file_name", ""), "warn")
    return jsonify({"ok": True, "deleted": deleted})


@app.route("/api/camera/<printer>/snapshot")
def camera_snapshot(printer):
    if printer not in PRINTERS:
        return jsonify({"ok": False, "error": "bad printer"}), 400

    snapshot_url = _camera_snapshot_url(printer)
    if not snapshot_url:
        return jsonify({"ok": False, "error": "camera snapshot URL is not configured"}), 404

    try:
        response = requests.get(snapshot_url, timeout=config.CAMERA_TIMEOUT)
        response.raise_for_status()
    except Exception as exc:
        return jsonify({"ok": False, "error": f"snapshot failed: {exc}"}), 502

    content_type = response.headers.get("Content-Type", "image/jpeg").split(";")[0]
    if not content_type.startswith("image/"):
        content_type = "image/jpeg"

    return Response(
        response.content,
        mimetype=content_type,
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": f'inline; filename="{printer}-snapshot.jpg"',
        },
    )


@app.route("/api/printer/<printer>/lock", methods=["POST"])
def set_printer_lock(printer):
    if printer not in PRINTERS:
        return jsonify({"ok": False, "error": "bad printer"}), 400

    try:
        locked = bool(_json_object().get("locked", True))
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    saved = _set_control_locked(printer, locked)
    _record_activity(
        "Controls locked" if saved else "Controls unlocked",
        printer,
        "Manual dashboard lock toggle",
        "warn" if saved else "ok",
    )
    return jsonify({"ok": True, "printer": printer, "locked": saved})


@app.route("/api/activity/<entry_id>", methods=["POST"])
def update_activity(entry_id):
    try:
        data = _json_object()
        action = _clean_text(data.get("action"), 80)
        detail = _clean_text(data.get("detail"), 240)
        severity = _clean_text(data.get("severity"), 16) or "info"
        printer = _clean_text(data.get("printer"), 40)

        if not action:
            raise ValueError("activity title is required")
        if severity not in ACTIVITY_SEVERITIES:
            raise ValueError("severity must be info, ok, warn, or danger")
        if printer and printer not in PRINTERS:
            raise ValueError("bad printer")
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    def edit_entry(store):
        for entry in store["activity"]:
            if entry.get("id") == entry_id:
                entry.update(
                    {
                        "action": action,
                        "printer": printer,
                        "printer_label": PRINTERS.get(printer, {}).get("label", "") if printer else "",
                        "detail": detail,
                        "severity": severity,
                        "edited_at": _now_iso(),
                    }
                )
                return entry
        return None

    saved = _update_data(edit_entry)
    if not saved:
        return jsonify({"ok": False, "error": "activity entry not found"}), 404

    socketio.emit("activity_event", saved)
    return jsonify({"ok": True, "activity": saved})


@app.route("/api/activity/<entry_id>/delete", methods=["POST"])
def delete_activity(entry_id):
    def remove_entry(store):
        for index, entry in enumerate(store["activity"]):
            if entry.get("id") == entry_id:
                return store["activity"].pop(index)
        return None

    deleted = _update_data(remove_entry)
    if not deleted:
        return jsonify({"ok": False, "error": "activity entry not found"}), 404

    socketio.emit("activity_event", {"id": entry_id, "deleted": True})
    return jsonify({"ok": True, "deleted": deleted})


@app.route("/api/filament/<printer>", methods=["POST"])
def update_filament(printer):
    if printer not in PRINTERS:
        return jsonify({"ok": False, "error": "bad printer"}), 400

    try:
        data = _json_object()
        update = {
            "brand": _clean_text(data.get("brand"), 80),
            "material": _clean_text(data.get("material"), 24) or "PLA",
            "color": _clean_text(data.get("color"), 40),
            "auto_deduct": bool(data.get("auto_deduct", True)),
            "notes": _clean_text(data.get("notes"), 240),
        }

        for field, label in (
            ("spool_weight_g", "spool weight"),
            ("remaining_g", "remaining"),
            ("cost", "cost"),
            ("diameter_mm", "diameter"),
            ("density_g_cm3", "density"),
            ("low_threshold_g", "low threshold"),
        ):
            if field in data and data[field] not in (None, ""):
                update[field] = _clean_float(data[field], label)
        if "density_g_cm3" not in update:
            update["density_g_cm3"] = _density_for_material(update["material"])
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    def save_filament(store):
        store["filament"][printer].update(update)
        return store["filament"][printer]

    saved = _update_data(save_filament)
    _record_activity(
        "Filament updated",
        printer,
        f"{saved.get('brand', '')} {saved.get('material', '')} {saved.get('color', '')}".strip(),
        "info",
    )
    return jsonify({"ok": True, "filament": saved})


@app.route("/api/maintenance", methods=["POST"])
def add_maintenance():
    try:
        data = _json_object()
        printer = _clean_text(data.get("printer"), 40) or "all"
        if printer != "all" and printer not in PRINTERS:
            raise ValueError("bad printer")

        due_date = _clean_text(data.get("due_date"), 10)
        if due_date:
            datetime.strptime(due_date, "%Y-%m-%d")

        task = _clean_text(data.get("task"), 120)
        if not task:
            raise ValueError("task is required")

        entry = {
            "id": uuid.uuid4().hex,
            "printer": printer,
            "printer_label": "All printers" if printer == "all" else PRINTERS[printer]["label"],
            "task": task,
            "notes": _clean_text(data.get("notes"), 300),
            "due_date": due_date,
            "created_at": _now_iso(),
            "completed_at": None,
        }
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    def save_entry(store):
        store["maintenance"].insert(0, entry)
        return entry

    saved = _update_data(save_entry)
    _record_activity("Maintenance added", printer if printer != "all" else None, task, "info")
    return jsonify({"ok": True, "maintenance": saved})


@app.route("/api/maintenance/<entry_id>", methods=["POST"])
def update_maintenance(entry_id):
    try:
        data = _json_object()
        printer = _clean_text(data.get("printer"), 40) or "all"
        if printer != "all" and printer not in PRINTERS:
            raise ValueError("bad printer")

        due_date = _clean_text(data.get("due_date"), 10)
        if due_date:
            datetime.strptime(due_date, "%Y-%m-%d")

        task = _clean_text(data.get("task"), 120)
        if not task:
            raise ValueError("task is required")

        update = {
            "printer": printer,
            "printer_label": "All printers" if printer == "all" else PRINTERS[printer]["label"],
            "task": task,
            "notes": _clean_text(data.get("notes"), 300),
            "due_date": due_date,
            "edited_at": _now_iso(),
        }
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    def edit_entry(store):
        for entry in store["maintenance"]:
            if entry.get("id") == entry_id:
                entry.update(update)
                return entry
        return None

    saved = _update_data(edit_entry)
    if not saved:
        return jsonify({"ok": False, "error": "maintenance entry not found"}), 404

    _record_activity(
        "Maintenance edited",
        saved.get("printer") if saved.get("printer") != "all" else None,
        saved.get("task", ""),
        "info",
    )
    return jsonify({"ok": True, "maintenance": saved})


@app.route("/api/maintenance/<entry_id>/delete", methods=["POST"])
def delete_maintenance(entry_id):
    def remove_entry(store):
        for index, entry in enumerate(store["maintenance"]):
            if entry.get("id") == entry_id:
                return store["maintenance"].pop(index)
        return None

    deleted = _update_data(remove_entry)
    if not deleted:
        return jsonify({"ok": False, "error": "maintenance entry not found"}), 404

    _record_activity(
        "Maintenance deleted",
        deleted.get("printer") if deleted.get("printer") != "all" else None,
        deleted.get("task", ""),
        "warn",
    )
    return jsonify({"ok": True, "deleted": deleted})


@app.route("/api/maintenance/<entry_id>/complete", methods=["POST"])
def complete_maintenance(entry_id):
    def complete(store):
        for entry in store["maintenance"]:
            if entry.get("id") == entry_id:
                entry["completed_at"] = _now_iso()
                return entry
        return None

    saved = _update_data(complete)
    if not saved:
        return jsonify({"ok": False, "error": "maintenance entry not found"}), 404
    _record_activity(
        "Maintenance completed",
        saved.get("printer") if saved.get("printer") != "all" else None,
        saved.get("task", ""),
        "ok",
    )
    return jsonify({"ok": True, "maintenance": saved})


# ---------------- PRINTER CONTROL ENDPOINT ----------------
@app.route("/api/control/<printer>/<action>", methods=["POST"])
@control_endpoint
def control(printer, url, headers, action):
    if action == "emergency":
        label = PRINTERS[printer]["label"]
        try:
            data = _json_object()
            if data.get("confirm") != f"M112 {label}":
                raise ValueError(f'type "M112 {label}" to confirm firmware emergency stop')
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

        ok, detail = _post_octoprint(
            url,
            headers,
            "/api/printer/command",
            {"commands": ["M112"]},
        )
        if not ok:
            return jsonify({"ok": False, "error": f"OctoPrint rejected emergency stop: {detail}"}), 502

        _set_control_locked(printer, True)
        _mark_emergency_requested(printer)
        _record_activity("Emergency stop", printer, "M112 sent; controls locked", "danger")
        return jsonify({"ok": True, "locked": True})

    locked = _locked_response(printer)
    if locked:
        return locked

    if action in ("pause", "resume"):
        payload = {"command": "pause", "action": action}
    elif action == "cancel":
        payload = {"command": "cancel"}
    else:
        return jsonify({"ok": False, "error": "bad action"}), 400

    ok, detail = _post_octoprint(url, headers, "/api/job", payload)
    if not ok:
        return jsonify({"ok": False, "error": f"OctoPrint rejected action: {detail}"}), 502
    if action == "cancel":
        _mark_cancel_requested(printer)
    _record_activity(
        f"Print {action}",
        printer,
        "OctoPrint job command accepted",
        "warn" if action == "cancel" else "info",
    )
    return jsonify({"ok": True})


# ---------------- AXIS JOG ENDPOINT ----------------
@app.route("/api/control/<printer>/jog", methods=["POST"])
@control_endpoint
def jog(printer, url, headers):
    locked = _locked_response(printer)
    if locked:
        return locked

    try:
        axes = _json_object().get("axes", {})
        if not isinstance(axes, dict):
            raise ValueError("axes must be an object")

        unknown_axes = set(axes) - ALLOWED_AXES
        if unknown_axes:
            raise ValueError(f"unknown axis: {', '.join(sorted(unknown_axes))}")

        values = {
            axis: _bounded_float(axes.get(axis, 0), axis, -config.MAX_JOG_MM, config.MAX_JOG_MM)
            for axis in ALLOWED_AXES
        }
        if not any(values.values()):
            raise ValueError("at least one axis movement is required")

        payload = {"command": "jog", **values, "speed": config.JOG_SPEED}
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    ok, detail = _post_octoprint(url, headers, "/api/printer/printhead", payload)
    if not ok:
        return jsonify({"ok": False, "error": f"OctoPrint rejected jog: {detail}"}), 502

    print(f"{printer} jogging: {payload}")
    moved = ", ".join(f"{axis.upper()} {values[axis]:g}mm" for axis in sorted(values) if values[axis])
    _record_activity("Jog", printer, moved, "info")
    return jsonify({"ok": True})


# ---------------- AXIS HOME ENDPOINT ----------------
@app.route("/api/control/<printer>/home", methods=["POST"])
@control_endpoint
def home(printer, url, headers):
    locked = _locked_response(printer)
    if locked:
        return locked

    try:
        axes = _json_object().get("axes", ["x", "y", "z"])
        if not isinstance(axes, list):
            raise ValueError("axes must be a list")

        normalized_axes = []
        for axis in axes:
            if axis not in ALLOWED_AXES:
                raise ValueError(f"unknown axis: {axis}")
            if axis not in normalized_axes:
                normalized_axes.append(axis)

        if not normalized_axes:
            raise ValueError("at least one axis is required")

        payload = {"command": "home", "axes": normalized_axes}
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    ok, detail = _post_octoprint(url, headers, "/api/printer/printhead", payload)
    if not ok:
        return jsonify({"ok": False, "error": f"OctoPrint rejected home: {detail}"}), 502

    print(f"{printer} homing: {normalized_axes}")
    _record_activity(
        "Home axes",
        printer,
        ", ".join(axis.upper() for axis in normalized_axes),
        "info",
    )
    return jsonify({"ok": True})


# ---------------- TEMPERATURE ENDPOINT ----------------
@app.route("/api/control/<printer>/temp", methods=["POST"])
@control_endpoint
def set_temp(printer, url, headers):
    locked = _locked_response(printer)
    if locked:
        return locked

    try:
        data = _json_object()
        unknown = set(data) - {"tool", "bed"}
        if unknown:
            raise ValueError(f"unknown temperature field: {', '.join(sorted(unknown))}")
        if "tool" not in data and "bed" not in data:
            raise ValueError("tool or bed temperature is required")

        requests_to_send = []
        targets = {}
        if "tool" in data:
            tool = _bounded_float(data["tool"], "tool", 0, config.MAX_HOTEND_TEMP)
            targets["tool"] = tool
            requests_to_send.append(
                (
                    "/api/printer/tool",
                    {"command": "target", "targets": {"tool0": tool}},
                )
            )
        if "bed" in data:
            bed = _bounded_float(data["bed"], "bed", 0, config.MAX_BED_TEMP)
            targets["bed"] = bed
            requests_to_send.append(
                (
                    "/api/printer/bed",
                    {"command": "target", "target": bed},
                )
            )
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    for path, payload in requests_to_send:
        ok, detail = _post_octoprint(url, headers, path, payload)
        if not ok:
            return jsonify({"ok": False, "error": f"OctoPrint rejected temperature: {detail}"}), 502

    print(f"{printer} set temp: {data}")
    detail = ", ".join(f"{key} {value:g}C" for key, value in targets.items())
    _record_activity("Temperature set", printer, detail, "info")
    return jsonify({"ok": True})


# ---------------- EXTRUDE / RETRACT ENDPOINT ----------------
@app.route("/api/control/<printer>/extrude", methods=["POST"])
@control_endpoint
def extrude(printer, url, headers):
    locked = _locked_response(printer)
    if locked:
        return locked

    try:
        amount = _bounded_float(
            _json_object().get("amount", 0),
            "amount",
            -config.MAX_EXTRUDE_MM,
            config.MAX_EXTRUDE_MM,
        )
        if amount == 0:
            raise ValueError("amount must not be zero")
        payload = {"command": "extrude", "amount": amount}
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    ok, detail = _post_octoprint(url, headers, "/api/printer/tool", payload)
    if not ok:
        return jsonify({"ok": False, "error": f"OctoPrint rejected extrusion: {detail}"}), 502

    print(f"{printer} extrude: {amount} mm")
    _record_activity(
        "Extrude" if amount > 0 else "Retract",
        printer,
        f"{abs(amount):g}mm",
        "info",
    )
    return jsonify({"ok": True})


def run_server():
    if config.DASHBOARD_PASSWORD_GENERATED:
        print("Generated one-time DASHBOARD_PASSWORD:", config.DASHBOARD_PASSWORD)
        print("Set DASHBOARD_PASSWORD in .env to make this persistent.")
    if config.FLASK_SECRET_KEY_GENERATED:
        print("Generated one-time FLASK_SECRET_KEY. Set it in .env for stable sessions.")

    socketio.start_background_task(data_loop)
    run_kwargs = {}
    if not sys.stdin or not sys.stdin.isatty():
        run_kwargs["allow_unsafe_werkzeug"] = True

    socketio.run(app, host=config.HOST, port=config.PORT, **run_kwargs)


if __name__ == "__main__":
    run_server()
