# 3D Printer Dashboard
---

<img width="2163" height="1111" alt="image" src="https://github.com/user-attachments/assets/32ccee51-551f-494a-ae79-17da808919ce" />

---

A real-time, web-based dashboard for monitoring and controlling multiple 3D printers running OctoPrint. The application is built using Flask, Socket.IO, and Chart.js, providing centralized visibility and control across multiple printers from a single interface.

---

## Overview

The 3D Printer Dashboard provides live printer status, temperature monitoring, print control, system metrics, and environmental data through a responsive web interface. It is optimized for both desktop and mobile use and supports multiple OctoPrint instances running on the same network.

---

## Features

### Printer Management
- Real-time printer status monitoring (printing, paused, idle, offline)
- Live hotend and bed temperature tracking with stability indicators
- Print progress visualization with estimated time remaining
- Pause, resume, and cancel print functionality
- Manual XYZ axis jog controls with configurable movement distance
- Axis homing (individual axes or all axes)

### Monitoring and Analytics
- Real-time temperature graph displaying recent hotend and bed readings
- Collapsible UI sections for improved layout organization
- Persistent UI state using browser local storage

### Live Camera Feed
- MJPEG-based live camera streams per printer
- Automatic reconnection on device wake or network interruption
- Visual status indicator for camera connectivity

### Weather Integration
- Local weather data including temperature, humidity, wind, and pressure
- Air quality metrics (AQI and PM2.5)
- Forecast data with precipitation probability and daily min/max temperatures
- Sunrise and sunset times

### System Monitoring
- CPU usage
- Memory usage
- Disk usage
- System uptime
- Live clock display

### Responsive Design
- Fully responsive layout for desktop, tablet, and mobile devices
- Dark theme optimized for extended use
- Touch-friendly controls
- Adaptive grid layout

---

## Project Structure
```
WebInterface/
├── WebInterface.py
├── templates/
│   └── index.html
└── static/
└── style.css
```
---

## Installation

Prerequisites
- Python 3.7 or newer
- Two or more OctoPrint instances running on the same network
- OpenWeatherMap API key (free tier supported)

---
## Setup

### Clone the repository:

`git clone https://github.com/Claus-GS/WebInterface
cd printer-dashboard`

### Create and activate a virtual environment:
```
python -m venv venv
source venv/bin/activate
Windows: venv\Scripts\activate
```
### Install dependencies:

`pip install -r requirements.txt`

### Configure OctoPrint instances in `WebInterface.py`:
```
printer1_URL = “http://printer1-ip:5000”
printer2_URL = “http://printer2-ip:5001”

printer1_KEY = “printer1-api-key”
printer2_KEY = “printer2-api-key”
```
### Configure the Weather API:
```
WEATHER_API_KEY = “your-openweathermap-key”
WEATHER_LAT = "your-latitude"
WEATHER_LON = your-longitute"
```

### Configure camera URLs in `templates/index.html`:
```
<img src="http://printer-ip:8080/?action=stream">
```

### Run the application:
`python WebInterface.py`

### Dashboard URL:
`http://localhost:8100`

## API Endpoints

### Print Control

`POST /api/control//`

### Parameters:
- printer: printer1 or printer2
- action: pause, resume, cancel

Response:
```{ “ok”: true }```

### Axis Movement (Jog)
```
`POST /api/control//jog`
```
Request body:
```
{
“command”: “jog”,
“axes”: {
“x”: 10,
“y”: -5,
“z”: 2
}
}
```
### Homing

`POST /api/control//home`

Request body:
```
{
“command”: “home”,
“axes”: [“x”, “y”, “z”]
}
```
---

## Real-Time Updates

### The dashboard uses Socket.IO to push updates every two seconds, including:
- Printer and job status
- Temperature readings
- System performance metrics
- Cached weather data (refreshed every 10 minutes)

---

## Browser Compatibility
- Chrome / Chromium (latest)
- Firefox (latest)
- Safari (latest)
- Edge (latest)
- Mobile browsers (iOS Safari, Chrome for Android)

---

## Dependencies
```
flask==2.3.0
flask-socketio==5.3.0
python-socketio==5.9.0
python-engineio==4.7.0
requests==2.31.0
psutil==5.9.5
eventlet==0.33.3
```
---

## Troubleshooting

### Camera Feed Not Loading
- Verify camera URLs are correct
- Test camera streams directly in a browser
- Check firewall and network access
- Inspect browser console for errors

### Printer Offline or Not Updating
- Verify OctoPrint URLs and API keys
- Ensure OctoPrint is running and reachable
- Confirm API key permissions
- Check terminal output and browser console

### Weather Data Issues
- Verify API key and geographic coordinates
- Confirm internet connectivity
- Check OpenWeatherMap rate limits
- Review application logs

### Axis Control Not Responding
- Ensure printer is idle
- Verify firmware supports jog commands
- Confirm API control permissions

---

## Customization

### Styling

- Edit `static/style.css` to adjust layout, colors, fonts, and responsive breakpoints.

### Adding Additional Printers
- Add new printer URLs and API keys in WebInterface.py
- Fetch printer data in the update loop
- Emit new printer data via Socket.IO
- Duplicate the printer section in index.html

### Update Frequency

- Modify the update interval in `WebInterface.py`:

`socketio.sleep(2)`

---

## Performance
- Update interval: 2 seconds (configurable)
- Weather cache: 10 minutes
- Typical memory usage: 50–100 MB
- Optimized for mobile and low-bandwidth connections

---

## License

- MIT License

---

## Future Enhancements
- Multi-printer queue management
- Print history and analytics
- Filament usage tracking
- Notification system (email/SMS)
- Bed leveling assistance
- Remote file upload
- Light/dark theme toggle

---

## Additional Resources

- OctoPrint documentation: `https://octoprint.org`
