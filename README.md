# Vision PAL 🐾👓

Vision Pro + JetBot = パルの目になる

## Architecture

```
Vision Pro (Swift/RealityKit)          JetBot (Python)
┌─────────────────────┐          ┌──────────────────┐
│  HeadTracking       │          │  mqtt_robot.py    │
│  → yaw/pitch        │──MQTT──→│  → Motor Control  │
│                     │          │                   │
│  MJPEGView          │←─HTTP──│  mjpeg_server.py  │
│  → Camera Feed      │          │  → CSI Camera     │
└─────────────────────┘          └──────────────────┘
         │                                │
         └──── Mosquitto (Jetson) ────────┘
                192.168.3.5:1883
```

## Components

### Vision Pro App (Swift + RealityKit)
- Head tracking → MQTT move commands
- MJPEG camera feed display in AR space
- Look forward = JetBot forward, look left/right = turn

### JetBot (Python 3.6)
- `mqtt_robot.py` - MQTT subscriber → Adafruit MotorHAT control
- `mjpeg_server.py` - CSI camera → HTTP MJPEG stream on port 8554

### Infrastructure
- Mosquitto MQTT broker on Jetson host (192.168.3.5:1883)
- All communication over local WiFi network

## Setup

1. Start Mosquitto on Jetson: `sudo systemctl start mosquitto`
2. Start JetBot scripts: `python3 mqtt_robot.py` & `python3 mjpeg_server.py`
3. Open VisionPAL app on Vision Pro
4. Look around to control JetBot!

## MQTT Topics

| Topic | Direction | Payload |
|-------|-----------|---------|
| `vision_pal/move` | Vision Pro → JetBot | `{"direction": "forward\|left\|right\|stop", "speed": 0.0-1.0}` |
| `vision_pal/status` | JetBot → Vision Pro | `{"status": "ready", "timestamp": ...}` |
