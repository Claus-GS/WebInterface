import eventlet
eventlet.monkey_patch()

import time
import requests
import psutil

from flask import Flask, jsonify, render_template, request
from flask_socketio import SocketIO

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

# ---------------- OCTOPRINT ----------------
MINIMUS_URL = "http://127.0.0.1:5000"
SPRITE_URL  = "http://127.0.0.1:5001"

MINIMUS_KEY = "k1VzZxdY88PD_fvtOXXuwLxP3iFWNJRmi6alX3i6tNE"
SPRITE_KEY  = "S1J6JDg0XaZrDD3cCjQnwps0aa2aro7W6HqyCXhXCi0"

HEADERS_MINIMUS = {"X-Api-Key": MINIMUS_KEY}
HEADERS_SPRITE  = {"X-Api-Key": SPRITE_KEY}

# ---------------- WEATHER ----------------
WEATHER_API_KEY = "190fda66ebafad2e6eed5b6a1cac6fe7"
WEATHER_LAT = 44.3091
WEATHER_LON = -78.3197

_weather_cache = {}
_weather_last = 0


def fetch_octoprint(url, headers):
    try:
        printer = requests.get(f"{url}/api/printer", headers=headers, timeout=3).json()
    except:
        printer = {}

    try:
        job = requests.get(f"{url}/api/job", headers=headers, timeout=3).json()
    except:
        job = {}

    return printer, job


def fetch_weather():
    global _weather_cache, _weather_last

    if time.time() - _weather_last < 600 and _weather_cache:
        return _weather_cache

    try:
        c = requests.get(
            "https://api.openweathermap.org/data/2.5/weather",
            params={
                "lat": WEATHER_LAT,
                "lon": WEATHER_LON,
                "units": "metric",
                "appid": WEATHER_API_KEY
            },
            timeout=5
        ).json()

        f = requests.get(
            "https://api.openweathermap.org/data/2.5/forecast",
            params={
                "lat": WEATHER_LAT,
                "lon": WEATHER_LON,
                "units": "metric",
                "appid": WEATHER_API_KEY
            },
            timeout=5
        ).json()

        a = requests.get(
            "https://api.openweathermap.org/data/2.5/air_pollution",
            params={
                "lat": WEATHER_LAT,
                "lon": WEATHER_LON,
                "appid": WEATHER_API_KEY
            },
            timeout=5
        ).json()

        aq = a["list"][0]
        next_hour = f["list"][0]

        _weather_cache = {
            "temp": c["main"]["temp"],
            "feels": c["main"]["feels_like"],
            "humidity": c["main"]["humidity"],
            "pressure": c["main"]["pressure"],
            "wind": c["wind"]["speed"],
            "clouds": c["clouds"]["all"],
            "visibility": c.get("visibility", 0) / 1000,
            "temp_max": c["main"]["temp_max"],
            "temp_min": c["main"]["temp_min"],
            "rain_prob": next_hour.get("pop", 0) * 100,
            "sunrise": c["sys"]["sunrise"],
            "sunset": c["sys"]["sunset"],
            "aqi": aq["main"]["aqi"],
            "pm25": aq["components"]["pm2_5"]
        }

        _weather_last = time.time()
        return _weather_cache

    except:
        return {"error": True}


def fetch_system():
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
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
        "uptime": uptime
    }


def data_loop():
    while True:
        mp, mj = fetch_octoprint(MINIMUS_URL, HEADERS_MINIMUS)
        sp, sj = fetch_octoprint(SPRITE_URL, HEADERS_SPRITE)

        socketio.emit("update", {
            "minimus_printer": mp,
            "minimus_job": mj,
            "sprite_printer": sp,
            "sprite_job": sj,
            "weather": fetch_weather(),
            "system": fetch_system()
        })

        socketio.sleep(2)


@app.route("/")
def index():
    return render_template("index.html")


# ---------------- PRINTER CONTROL ENDPOINT ----------------
@app.route("/api/control/<printer>/<action>", methods=["POST"])
def control(printer, action):
    if printer == "minimus":
        url, headers = MINIMUS_URL, HEADERS_MINIMUS
    elif printer == "sprite":
        url, headers = SPRITE_URL, HEADERS_SPRITE
    else:
        return jsonify({"error": "bad printer"}), 400

    try:
        if action in ("pause", "resume"):
            payload = {
                "command": "pause",
                "action": action
            }
        elif action == "cancel":
            payload = {
                "command": "cancel"
            }
        else:
            return jsonify({"error": "bad action"}), 400

        requests.post(
            f"{url}/api/job",
            headers=headers,
            json=payload,
            timeout=5
        )

        return jsonify({"ok": True})

    except Exception as e:
        print("Control error:", e)
        return jsonify({"ok": False}), 500


# ---------------- AXIS JOG ENDPOINT ----------------
@app.route("/api/control/<printer>/jog", methods=["POST"])
def jog(printer):
    if printer == "minimus":
        url, headers = MINIMUS_URL, HEADERS_MINIMUS
    elif printer == "sprite":
        url, headers = SPRITE_URL, HEADERS_SPRITE
    else:
        return jsonify({"error": "bad printer"}), 400

    try:
        data = request.get_json()
        
        # Build jog payload for OctoPrint
        payload = {
            "command": "jog",
            "x": data.get("axes", {}).get("x", 0),
            "y": data.get("axes", {}).get("y", 0),
            "z": data.get("axes", {}).get("z", 0),
            "speed": 3000  # OctoPrint jog speed in mm/min
        }

        response = requests.post(
            f"{url}/api/printer/printhead",
            headers=headers,
            json=payload,
            timeout=5
        )

        if response.status_code == 204:
            print(f"🎯 {printer} jogging: {payload}")
            return jsonify({"ok": True})
        else:
            return jsonify({"error": "Failed to jog"}), 500

    except Exception as e:
        print(f"Jog error: {e}")
        return jsonify({"error": str(e)}), 500


# ---------------- AXIS HOME ENDPOINT ----------------
@app.route("/api/control/<printer>/home", methods=["POST"])
def home(printer):
    if printer == "minimus":
        url, headers = MINIMUS_URL, HEADERS_MINIMUS
    elif printer == "sprite":
        url, headers = SPRITE_URL, HEADERS_SPRITE
    else:
        return jsonify({"error": "bad printer"}), 400

    try:
        data = request.get_json()
        axes = data.get("axes", ["x", "y", "z"])
        
        # Build home payload for OctoPrint
        payload = {
            "command": "home",
            "axes": axes
        }

        response = requests.post(
            f"{url}/api/printer/printhead",
            headers=headers,
            json=payload,
            timeout=5
        )

        if response.status_code == 204:
            print(f"🏠 {printer} homing: {axes}")
            return jsonify({"ok": True})
        else:
            return jsonify({"error": "Failed to home"}), 500

    except Exception as e:
        print(f"Home error: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    socketio.start_background_task(data_loop)
    socketio.run(app, host="0.0.0.0", port=8100)
