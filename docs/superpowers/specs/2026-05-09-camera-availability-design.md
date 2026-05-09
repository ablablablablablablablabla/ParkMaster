# Camera-Based Availability for Lot Sajam

**Date:** 2026-05-09  
**Scope:** Wire live camera feed from CV server into bot's parking search, so Lot Sajam is silently hidden when camera detects an occupied slot.

---

## Problem

`spot_sajam_1` ("Lot Sajam", Belgrade) is always shown as available in bot results. During demo, a camera (via `web_server.py` + `index.html`) shows the real slot state. Bot must reflect that state: hide Lot Sajam when camera sees a car, show it when slot is empty.

---

## Architecture

Two separate processes on the same machine:

- **Telegram bot** (`main.py` → `bot_handlers.py` → `agents.py`)
- **Flask CV server** (`web_server.py`, port 5000) — receives base64 frames from browser, runs Keras model, returns label

The browser (`index.html`) pushes frames to Flask every 1 second. Flask always has the latest prediction. Bot queries Flask on demand.

---

## Data Flow

```
[Browser camera] --frame every 1s--> Flask POST /predict
                                           |
                                     updates LAST_PREDICTION global
                                           |
[Telegram Driver] --"find parking"--> bot agent
                                           |
                               find_nearby_parking() called
                                           |
                               GET http://localhost:5000/status
                                           |
                  is_occupied=true? → drop spot_sajam_1 from results
                  is_occupied=false? → include spot_sajam_1
                  Flask unreachable? → include spot_sajam_1 (safe fallback)
```

---

## Changes

### `web_server.py`

1. Add module-level `LAST_PREDICTION` dict:
   ```python
   LAST_PREDICTION = {
       "label": None,
       "is_occupied": False,
       "is_no_parking": False,
       "confidence": 0.0
   }
   ```

2. In `/predict` handler, after calling `predict_car()`, update `LAST_PREDICTION` in-place.

3. Add new endpoint:
   ```python
   @app.route("/status")
   def status():
       return jsonify(LAST_PREDICTION)
   ```

### `agents.py`

1. Add constants near top:
   ```python
   CAMERA_SERVER_URL = os.getenv("CAMERA_SERVER_URL", "http://localhost:5000")
   CAMERA_SPOT_ID = "spot_sajam_1"
   ```

2. In `find_nearby_parking`, after building `available` list, append camera filter:
   ```python
   try:
       with httpx.Client(timeout=2.0) as client:
           r = client.get(f"{CAMERA_SERVER_URL}/status")
           if r.status_code == 200 and r.json().get("is_occupied"):
               available = [s for s in available if s["id"] != CAMERA_SPOT_ID]
   except Exception:
       pass  # Flask down → include spot normally
   ```

---

## Model Labels (reference)

| Index | Label       | Meaning                          |
|-------|-------------|----------------------------------|
| 0     | Occupated   | Car present — spot busy          |
| 1     | Empty       | No car — spot available          |
| 2     | No parking  | Frame is not a parking spot area |

Only `Occupated` triggers the filter. `No parking` and `Empty` both leave Lot Sajam visible.

---

## Error Handling

| Scenario | Behavior |
|---|---|
| Flask not started | `except Exception: pass` → spot included |
| No prediction yet (`label=None`) | `is_occupied=False` → spot included |
| Camera shows "No parking" | `is_occupied=False` → spot included |
| Flask returns non-200 | Filter skipped → spot included |
| Payment reserves spot | Unaffected — `status='reserved'` set separately |

---

## What Does NOT Change

- Agent instructions (`get_park_master_agent`)
- `find_nearby_parking` filtering logic (only an append)
- Booking / payment flow
- `PARKING_SPOTS` state management
- Any other parking spots

---

## Environment Config

| Variable | Default | Purpose |
|---|---|---|
| `CAMERA_SERVER_URL` | `http://localhost:5000` | Flask CV server URL |

---

## Demo Setup

```
Terminal 1: python web_server.py        # starts Flask on :5000
Terminal 2: python main.py              # starts Telegram bot

Browser: open http://localhost:5000
         → click "Start Monitoring"
         → point camera at parking image

Telegram: driver asks for parking near Belgrade/Sajam
          → camera-occupied image: Lot Sajam absent from results
          → camera-empty image: Lot Sajam present in results
```
