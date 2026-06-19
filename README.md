# 3D Printer Dashboard

A local web dashboard for monitoring and controlling multiple OctoPrint-backed 3D printers. The app uses Flask, Flask-SocketIO, Chart.js, and MJPEG camera streams.

## Current Features

- Real-time printer state, job, progress, hotend temperature, and bed temperature.
- Authenticated browser dashboard with server-side sessions.
- CSRF protection on all state-changing dashboard actions.
- Pause, resume, cancel print, jog, home, temperature, extrude, and retract controls.
- Guarded firmware M112 emergency stop and server-side control lock per printer.
- Print history for finished, cancelled, failed, and emergency-stopped jobs.
- Editable print history, maintenance entries, and recent activity entries.
- CSV export for print history and JSON export for all dashboard records.
- Recent activity log for dashboard actions and printer controls.
- Filament tracking with brand, material, color, remaining grams, and cost.
- Automatic filament usage and cost estimates from OctoPrint job filament length.
- Maintenance log with due dates and completed entries.
- Browser print notifications, plus optional email, Discord, Telegram, SMS/webhook notifications.
- Server-side safety limits for jog distance, extrusion amount, and temperature targets.
- Config-driven printer cards; printer API keys are not exposed to the browser.
- Per-printer health badges with online/offline state and request latency.
- Live host CPU, memory, disk, uptime, and clock display.
- Collapsible temperature, graph, camera, and axis-control panels.
- MJPEG camera stream refresh on focus/wake, fullscreen camera view, and snapshot download.
- Responsive dark UI for desktop and mobile.

## Project Structure

```text
WebInterface_fullwcam/
|-- WebInterface.py       # Flask + Socket.IO app
|-- config.py             # Environment/.env-backed settings
|-- .env.example          # Copy to .env for local secrets
|-- requirements.txt
|-- templates/
|   |-- index.html
|   `-- login.html
`-- static/
    `-- style.css
```

## Setup

1. Create and activate a virtual environment.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2. Install dependencies.

```powershell
pip install -r requirements.txt
```

3. Create local configuration.

```powershell
Copy-Item .env.example .env
```

4. Edit `.env`.

Required values:

```env
DASHBOARD_PASSWORD=use-a-long-private-password
FLASK_SECRET_KEY=use-a-long-random-secret

MINIMUS_URL=http://127.0.0.1:5000
MINIMUS_API_KEY=your-minimus-api-key
MINIMUS_CAMERA_URL=http://192.168.2.51/cam_Ender3minimus/?action=stream

SPRITE_URL=http://127.0.0.1:5001
SPRITE_API_KEY=your-sprite-api-key
SPRITE_CAMERA_URL=http://192.168.2.51/cam_Ender3Sprite/?action=stream
```

If `DASHBOARD_PASSWORD` is missing, the app prints a one-time generated password on startup. Put a real value in `.env` for normal use.

Print history, filament, maintenance, and control-lock state are stored in `dashboard_data.json` by default. The file is local runtime data and is ignored by git.

Filament auto-subtraction uses the spool diameter and material density configured in the Filament Tracker. It estimates grams from OctoPrint's reported filament length, then subtracts that from the selected printer's remaining spool amount.

5. Run the dashboard.

```powershell
python WebInterface.py
```

Open `http://localhost:8100`, then sign in with `DASHBOARD_PASSWORD`.

## Security Notes

- Do not commit `.env`; it is ignored by `.gitignore`.
- Rotate any OctoPrint or weather keys that were previously stored in source or shared.
- The app defaults to `HOST=0.0.0.0` for LAN access. Only expose it on networks you trust, or place it behind a proper reverse proxy/VPN.
- Browser control actions require both an authenticated session and a CSRF token.
- Server-side limits are configured in `.env`:

```env
MAX_HOTEND_TEMP=300
MAX_BED_TEMP=120
MAX_JOG_MM=50
MAX_EXTRUDE_MM=100
JOG_SPEED=3000
CONTROL_TIMEOUT=5
FILAMENT_LOW_G=100
FILAMENT_DEFAULT_DIAMETER_MM=1.75
FILAMENT_DEFAULT_DENSITY_G_CM3=1.24
```

## Adding Printers

The app currently defines Minimus and Sprite in `config.py`, with all sensitive values supplied by `.env`. To add more printers, add another entry to `PRINTERS` in `config.py` and follow the same pattern:

```python
"third": {
    "label": os.getenv("THIRD_LABEL", "Third Printer"),
    "url": os.getenv("THIRD_URL", "http://127.0.0.1:5002"),
    "key": os.getenv("THIRD_API_KEY", ""),
    "camera": os.getenv("THIRD_CAMERA_URL", "http://camera-ip/stream"),
},
```

## Control Endpoints

These endpoints are intended for the authenticated browser UI. Direct API calls must include the session cookie and `X-CSRF-Token` header.

- `POST /api/control/<printer>/pause`
- `POST /api/control/<printer>/resume`
- `POST /api/control/<printer>/cancel`
- `POST /api/control/<printer>/jog`
- `POST /api/control/<printer>/home`
- `POST /api/control/<printer>/temp`
- `POST /api/control/<printer>/extrude`
- `POST /api/control/<printer>/emergency`
- `POST /api/printer/<printer>/lock`

Dashboard data endpoints:

- `GET /api/dashboard-data`
- `GET /api/dashboard-data/export`
- `GET /api/history/export.csv`
- `POST /api/history/<entry_id>`
- `POST /api/history/<entry_id>/delete`
- `GET /api/camera/<printer>/snapshot`
- `POST /api/filament/<printer>`
- `POST /api/activity/<entry_id>`
- `POST /api/activity/<entry_id>/delete`
- `POST /api/maintenance`
- `POST /api/maintenance/<entry_id>`
- `POST /api/maintenance/<entry_id>/delete`
- `POST /api/maintenance/<entry_id>/complete`

Example request body for jog:

```json
{
  "axes": {
    "x": 10,
    "y": 0,
    "z": 0
  }
}
```

Example request body for temperature:

```json
{
  "tool": 200,
  "bed": 60
}
```

Emergency stop requires a typed confirmation:

```json
{
  "confirm": "M112 Minimus"
}
```

`cancel` asks OctoPrint to cancel the current print job normally. `emergency` sends firmware `M112`, records the job as failed, and locks controls for that printer.

## Notifications

Browser notifications work from the dashboard after permission is granted.
External channels are optional and stay disabled unless configured in `.env`:

```env
DISCORD_WEBHOOK_URL=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
NOTIFY_WEBHOOK_URL=
SMS_WEBHOOK_URL=

SMTP_HOST=
SMTP_PORT=587
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_USE_TLS=1
SMTP_FROM=
SMTP_TO=
```

`SMS_WEBHOOK_URL` is a generic webhook target. Use it with a service that can turn webhook posts into SMS messages.

## Troubleshooting

- If the login page appears unexpectedly, your session expired or `FLASK_SECRET_KEY` changed.
- If controls return `authentication required`, sign in through the browser first.
- If controls return `invalid csrf token`, refresh the dashboard page.
- If a printer shows `Not configured`, its API key is missing from `.env`.
- If a printer shows offline, verify OctoPrint URL, API key permissions, network reachability, and firewall rules.
- If cameras do not load, open the configured camera URL directly in the browser from the dashboard machine.
- If dependency issues appear after upgrading, recreate the virtual environment and reinstall from `requirements.txt`.

## Notes

This is designed for a private local workshop network. Treat printer movement and temperature controls as physical machine controls, not ordinary web buttons.
