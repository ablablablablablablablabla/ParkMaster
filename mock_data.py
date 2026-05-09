import os

# Demo recipient wallet on devnet — overridable via env. All spots share it
# for the hackathon. Replace per-spot wallets in production.
DEMO_RECIPIENT = os.getenv(
    "DEMO_RECIPIENT_PUBKEY", "11111111111111111111111111111111"
)

INITIAL_PARKING_SPOTS = [
    {
        "id": "spot_spens_1",
        "title": "SPENS Courtyard Spot",
        "city": "Novi Sad",
        "lat": 45.2468,
        "lng": 19.8511,
        "google_maps_link": "https://maps.google.com/?q=SPENS+Novi+Sad",
        "base_price_per_hour": 2.0,
        "minimum_duration_minutes": 60,
        "availability": "18:00-23:00",
        "status": "active",
        "wallet_address": DEMO_RECIPIENT,
        "access_instructions": "Gate code 1234. Enter through the gray gate near the bakery. Park in the second spot on the left.",
        "rules": "Do not block the garage door.",
        "verification_status": "verified"
    },
    {
        "id": "spot_sajam_1",
        "title": "Lot Sajam",
        "city": "Belgrade",
        "lat": 44.7940,
        "lng": 20.4302,
        "google_maps_link": "https://maps.google.com/?q=Sajam+Belgrade",
        "base_price_per_hour": 2.0,
        "minimum_duration_minutes": 60,
        "availability": "00:00-23:59",
        "status": "active",
        "wallet_address": DEMO_RECIPIENT,
        "access_instructions": "Enter from Bulevar vojvode Mišića. Spot is marked P3, ground level.",
        "rules": "No overnight parking. Stay within marked lines.",
        "verification_status": "verified"
    },
    {
        "id": "spot_promenada_1",
        "title": "Promenada Private Spot",
        "city": "Novi Sad",
        "lat": 45.2449,
        "lng": 19.8425,
        "google_maps_link": "https://maps.google.com/?q=Promenada+Novi+Sad",
        "base_price_per_hour": 2.5,
        "minimum_duration_minutes": 60,
        "availability": "17:00-22:00",
        "status": "active",
        "wallet_address": DEMO_RECIPIENT,
        "access_instructions": "Use entrance from the small side street. Parking spot number is 14.",
        "rules": "Leave before the booking end time.",
        "verification_status": "verified"
    }
]
