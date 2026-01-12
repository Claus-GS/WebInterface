# 3D Printer Dashboard
<img width="2163" height="1111" alt="image" src="https://github.com/user-attachments/assets/32ccee51-551f-494a-ae79-17da808919ce" />
A real-time web-based dashboard for monitoring and controlling multiple 3D printers running OctoPrint. Built with Flask, Socket.IO, and Chart.js.

## Features

### 🖨️ Printer Management
- **Real-time Status Monitoring** - Live printer state (printing, paused, idle, offline)
- **Temperature Tracking** - Live hotend and bed temperature display with stability indicator
- **Print Progress** - Visual progress bar with estimated time remaining
- **Pause/Resume Control** - Smart pause/resume buttons that appear when printing
- **Cancel Print** - One-click print cancellation with confirmation
- **XYZ Axis Control** - Manual jog control with adjustable movement distance
- **Homing** - Home individual axes or all at once

### 📊 Monitoring & Analytics
- **Temperature Graph** - Real-time line chart (last 60 readings) showing hotend and bed temperatures
- **Collapsible Sections** - Expandable panels for camera, graphs, and axis control
- **Persistent UI State** - Remembers which sections are expanded via localStorage

### 📷 Live Camera Feed
- **MJPEG Stream** - Live camera view for each printer
- **Auto-Reconnect** - Automatically recovers MJPEG streams on phone wake/unlock
- **Connectivity Status** - Visual indicator for camera online/offline status

### 🌤️ Weather Integration
- **Local Weather** - Real-time temperature, humidity, wind, pressure
- **Air Quality** - AQI and PM2.5 levels
- **Forecast** - Rain probability, min/max temperatures
- **Sun Times** - Sunrise/sunset times

### 💻 System Monitoring
- **CPU Usage** - Real-time CPU percentage
- **Memory** - RAM usage and percentage
- **Disk Space** - Storage usage and percentage
- **Uptime** - System uptime display
- **Live Clock** - Current time with automatic updates

### 📱 Responsive Design
- **Mobile Optimized** - Fully responsive for phones and tablets
- **Dark Theme** - Easy on the eyes with dark background
- **Touch-Friendly** - Large buttons and controls for mobile use
- **Adaptive Layout** - Grid layout adjusts to screen size

---

## Project Structure

`-WebInterface/
  -WebInterface.py
  -templates/
    -index.html
  -static/
    -style.css`
---

## Installation

### Prerequisites
- Python 3.7+
- Two OctoPrint instances running on your network
- OpenWeatherMap API key (free tier available)

### Setup

1. **Clone the repository**

`git clone https://github.com/Claus-GS/WebInterface`
`cd printer-dashboard`


2. **Create a virtual environment**

`python -m venv venv source venv/bin/activate  # On Windows: venv\Scripts\activate`

3. **Install dependencies**

`pip install -r requirements.txt`

4. **Configure OctoPrint URLs and API Keys**

Edit `WebInterface.py` and update:

OctoPrint Instances
`printer1_URL = "http://your-printer1-ip:5000" printer2_URL  = "http://your-printer2-ip:5001"`
`printer1_KEY = "your-printer1-api-key" printer2_KEY  = "your-printer2-api-key"`

Weather API Configuration
`WEATHER_API_KEY = "your-openweathermap-key" WEATHER_LAT = 44.3091      # Your latitude WEATHER_LON = -78.3197     # Your longitude`

5. **Update Camera URLs**

In `templates/index.html`, find and replace:

-- Replace these with your actual camera URLs --> `<img src="http://localhost:5000/<printername>/?action=stream"> <img src="http://localhost:5001<printername>/?action=stream">**`

Common camera URL formats:
- **OctoPrint webcam**: `http://printer-ip:8080/?action=stream`
- **Network IP camera**: `http://camera-ip/stream`
- **RTSP stream**: `http://camera-ip:554/stream`

6. **Run the application**
python WebInterface.py


The dashboard will be available at: `http://localhost:8100`

---

Test camera connectivity:
1. Open your camera URL directly in browser
2. Verify it loads and streams video
3. Check firewall/network settings if camera is unreachable

---

## API Endpoints

### Job Control

`POST /api/control/<printer>/<action>
Parameters: printer: "printer1" or "printer2" action:  "pause", "resume", or "cancel"
Response: { "ok": true }`

### Axis Movement (Jog)

`POST /api/control/<printer>/jog
Request body: { "command": "jog", "axes": { "x": 10,   // mm (positive = right) "y": -5,   // mm (positive = forward) "z": 2     // mm (positive = up) } }
Response: { "ok": true }`

### Homing

`POST /api/control/<printer>/home
Request body: { "command": "home", "axes": ["x", "y", "z"]  // or ["x"], ["y"], ["z"] for individual axes }
Response: { "ok": true }`

---

## Real-Time Updates

The dashboard uses **Socket.IO** to receive real-time updates every 2 seconds:

**Emitted data includes:**
- Printer status and job information
- Current temperatures (hotend and bed)
- System metrics (CPU, RAM, disk, uptime)
- Weather data (cached for 10 minutes)

---

## Browser Compatibility

- ✅ Chrome/Chromium (latest)
- ✅ Firefox (latest)
- ✅ Safari (latest)
- ✅ Edge (latest)
- ✅ Mobile browsers (iOS Safari, Chrome Android)

---

## Dependencies
`flask==2.3.0 flask-socketio==5.3.0 python-socketio==5.9.0 python-engineio==4.7.0 requests==2.31.0 psutil==5.9.5 eventlet==0.33.3`

`Install with:  pip install -r requirements.txt`

---

## Troubleshooting

### Cameras Not Loading
**Problem:** Camera feed shows blank or "loading"

**Solutions:**
- Verify camera URLs are correct and accessible
- Test camera URL directly in your browser
- Check network connectivity to camera
- Ensure camera IP/port is reachable from dashboard host
- Look for CORS issues in browser console (F12)
- Verify firewall allows access to camera ports

### Printer Connection Issues
**Problem:** Printer shows "Offline" or no data updates

**Solutions:**
- Verify OctoPrint URLs and API keys in `WebInterface.py`
- Check that OctoPrint instances are running and accessible
- Ensure network connectivity between dashboard and printers
- Verify API keys have correct permissions in OctoPrint settings
- Monitor `print()` statements in terminal for error messages
- Check browser console for connection errors

### Weather Data Not Loading
**Problem:** Weather section shows blank or errors

**Solutions:**
- Verify API key is correct and active
- Check latitude/longitude values are valid
- Ensure internet connectivity on dashboard server
- OpenWeatherMap free tier has rate limits (60 calls/min)
- Wait 10 minutes for cache to refresh
- Check for API errors in terminal output

### Axis Control Not Working
**Problem:** Jog/Home buttons don't move axes

**Solutions:**
- Verify printer is NOT currently printing (must be idle)
- Test manual axis control in OctoPrint web interface
- Ensure API key has `control` permissions
- Check that printer firmware supports jog commands
- Monitor browser console for error messages
- Verify printer is connected and operational

---

## Customization

### Styling
Edit `static/style.css` to customize:
- Colors and themes
- Font sizes
- Button styles
- Layout and spacing
- Responsive breakpoints

### Adding More Printers
To add a third printer:

1. **Add configuration in `WebInterface.py`:**


`THIRD_PRINTER_URL = "http://printer-ip:5002" THIRD_PRINTER_KEY = "api-key" HEADERS_THIRD = {"X-Api-Key": THIRD_PRINTER_KEY}`


2. **Update `data_loop()` function:**

`tp, tj = fetch_octoprint(THIRD_PRINTER_URL, HEADERS_THIRD)`


3. **Add to emitted data:**

`socketio.emit("update", { # ... existing data ... "third_printer": tp, "third_job": tj, })`


4. **Duplicate printer section in HTML** and update printer name

### Changing Update Frequency
In `WebInterface.py`, modify the sleep interval:
`socketio.sleep(2)  # Change 2 to desired seconds`

---

## Performance

- **Update Rate**: 2 seconds (configurable)
- **Weather Cache**: 10 minutes
- **Memory Usage**: ~50-100 MB
- **Network**: Real-time Socket.IO connections
- **Mobile**: Optimized for slow connections with minimal data usage

---

## License

MIT License - Feel free to use and modify as needed.

---

## Support

For issues or questions:
1. **Check browser console** - Press F12, look for error messages
2. **Monitor terminal output** - Watch for errors from `WebInterface.py`
3. **Verify configuration** - Double-check all URLs and API keys
4. **Test connectivity** - Ensure OctoPrint and cameras are accessible
5. **Check logs** - Look at system logs for network/service issues

---

## Future Enhancements

- [ ] Multi-printer print queue management
- [ ] Print history and statistics
- [ ] Filament tracking
- [ ] Email/SMS alerts for print completion
- [ ] Bed leveling assistant
- [ ] Remote file upload
- [ ] Dark/light theme toggle

---

**Built with ❤️ for 3D printing enthusiasts using AI**

For more information about OctoPrint, visit: [octoprint.org](https://octoprint.org)
