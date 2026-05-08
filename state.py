import time

# In-memory storage
USERS = {}  # telegram_id -> user_data
PARKING_SPOTS = {}  # spot_id -> spot_data
BOOKINGS = {}  # booking_id -> booking_data
AGENT_LOGS = []

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
