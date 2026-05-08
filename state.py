import json
import time
import os

STATE_FILE = os.path.join(os.path.dirname(__file__), ".state.json")

# In-memory storage
USERS = {}        # telegram_id -> user_data
PARKING_SPOTS = {}  # spot_id -> spot_data
BOOKINGS = {}     # booking_id -> booking_data
AGENT_LOGS = []


def save_state():
    """Persist mutable state to disk so registered spots survive restarts."""
    try:
        data = {
            "users": {str(k): v for k, v in USERS.items()},
            "parking_spots": PARKING_SPOTS,
            "bookings": BOOKINGS,
            "agent_logs": AGENT_LOGS[-100:],
        }
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2, default=str)
        os.replace(tmp, STATE_FILE)
    except Exception as e:
        print(f"[state] save failed: {e}")


def load_state():
    if not os.path.exists(STATE_FILE):
        return
    try:
        with open(STATE_FILE) as f:
            data = json.load(f)
        USERS.update({int(k): v for k, v in data.get("users", {}).items()})
        PARKING_SPOTS.update(data.get("parking_spots", {}))
        BOOKINGS.update(data.get("bookings", {}))
        AGENT_LOGS.extend(data.get("agent_logs", []))
    except Exception as e:
        print(f"[state] load failed: {e}")


def add_log(agent, booking_id, action, reasoning):
    log_entry = {
        "id": f"log_{len(AGENT_LOGS) + 1}",
        "agent": agent,
        "booking_id": booking_id,
        "action": action,
        "reasoning": reasoning,
        "created_at": time.time()
    }
    AGENT_LOGS.append(log_entry)
    print(f"AGENT LOG [{agent}]: {action} - {reasoning}")
    save_state()
