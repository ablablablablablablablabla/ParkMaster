import os
import uuid
import time
import httpx
from dotenv import load_dotenv
from google.adk.agents import LlmAgent
from google.adk import tools
from google.adk.models.lite_llm import LiteLlm
from state import USERS, PARKING_SPOTS, BOOKINGS, AGENT_LOGS, add_log, save_state
from payments import create_solana_pay_url, new_reference_pubkey, verify_payment, USDC_DEVNET_MINT

load_dotenv()

FLAT_PRICE_USDC = 1.0  # demo: flat 1 USDC per booking regardless of duration


@tools.FunctionTool
async def geocode_address(address: str) -> dict:
    """Resolve a free-form address or place name to lat/lng via OpenStreetMap Nominatim.

    Use this when the driver describes their location in words (e.g.
    "I'm near Sajam at Novi Sad") instead of sharing GPS coordinates.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": address, "format": "json", "limit": 1},
                headers={"User-Agent": "ParkMasterBot/1.0 (hackathon)"},
            )
            r.raise_for_status()
            results = r.json()
            if not results:
                return {"error": f"No location found for: {address}"}
            top = results[0]
            return {
                "lat": float(top["lat"]),
                "lng": float(top["lon"]),
                "display_name": top.get("display_name", address),
            }
    except Exception as e:
        return {"error": f"Geocoding failed: {e}"}


@tools.FunctionTool
def find_nearby_parking(lat: float, lng: float, duration_minutes: int) -> list:
    """Find available parking spots near given coordinates."""
    available = []
    for spot_id, spot in PARKING_SPOTS.items():
        if spot['status'] == 'active':
            distance_km = abs(spot['lat'] - lat) * 111 + abs(spot['lng'] - lng) * 111
            distance_text = f"{distance_km:.1f} km"
            available.append({
                "id": spot_id,
                "title": spot['title'],
                "price": FLAT_PRICE_USDC,
                "distance": distance_text,
                "rules": spot['rules']
            })
    return available


@tools.FunctionTool
def request_price_offer(spot_id: str, duration_minutes: int) -> dict:
    """Get the final price offer for a specific parking spot."""
    spot = PARKING_SPOTS.get(spot_id)
    if not spot:
        return {"error": "Parking spot not found"}

    return {
        "spot_id": spot_id,
        "base_price": FLAT_PRICE_USDC,
        "final_price": FLAT_PRICE_USDC,
        "reasoning": f"Demo mode: flat price of {FLAT_PRICE_USDC} USDC per booking."
    }


@tools.FunctionTool
def create_booking(driver_id: int, spot_id: str, price_usdc: float, duration_minutes: int) -> dict:
    """Create a parking booking. Price is fixed at 1 USDC."""
    price_usdc = FLAT_PRICE_USDC
    booking_id = f"booking_{uuid.uuid4().hex[:8]}"
    reference = new_reference_pubkey()

    spot = PARKING_SPOTS.get(spot_id)
    if not spot:
        return {"error": "Parking spot not found"}

    booking = {
        "id": booking_id,
        "driver_id": driver_id,
        "spot_id": spot_id,
        "duration_minutes": duration_minutes,
        "price_usdc": price_usdc,
        "status": "pending_payment",
        "payment_reference": reference,
        "recipient_wallet": spot['wallet_address'],
        "mint": USDC_DEVNET_MINT,
        "solana_pay_url": create_solana_pay_url(spot['wallet_address'], price_usdc, reference, booking_id),
        "payment_signature": None,
        "created_at": time.time()
    }

    BOOKINGS[booking_id] = booking
    add_log("driver_agent", booking_id, "booking_created", f"Booking {spot_id} created at {price_usdc} USDC")
    save_state()

    return booking


@tools.FunctionTool
async def verify_payment_onchain(booking_id: str) -> dict:
    """Verify booking payment on Solana devnet.

    Searches for an on-chain USDC tx referencing this booking. Returns
    status=success only if the tx is found and the amount matches.
    """
    booking = BOOKINGS.get(booking_id)
    if not booking:
        return {"error": "Booking not found"}

    if booking['status'] in ('paid', 'access_released'):
        return {
            "status": "success",
            "message": "Payment already confirmed.",
            "signature": booking.get('payment_signature'),
        }

    sig = await verify_payment(
        reference=booking['payment_reference'],
        expected_recipient=booking['recipient_wallet'],
        expected_amount=booking['price_usdc'],
        mint=booking['mint'],
        created_after=booking.get('created_at', 0.0),
    )

    if not sig:
        return {
            "status": "pending",
            "message": "Transaction not found on-chain yet. Try again in 10-30 seconds after paying.",
        }

    booking['status'] = 'paid'
    booking['payment_signature'] = sig
    spot = PARKING_SPOTS.get(booking['spot_id'])
    if spot:
        spot['status'] = 'reserved'

    add_log("driver_agent", booking_id, "payment_confirmed", f"On-chain payment verified: {sig}")

    return {
        "status": "success",
        "message": "Payment confirmed on-chain.",
        "signature": sig,
        "explorer_url": f"https://explorer.solana.com/tx/{sig}?cluster=devnet",
    }


@tools.FunctionTool
def get_access_instructions(booking_id: str) -> dict:
    """Get access instructions for a paid booking."""
    booking = BOOKINGS.get(booking_id)
    if not booking or booking['status'] != 'paid':
        return {"error": "Booking is not paid or not found"}

    spot = PARKING_SPOTS.get(booking['spot_id'])
    booking['status'] = 'access_released'

    add_log("parking_spot_agent", booking_id, "access_released", "Access instructions delivered to driver.")

    return {
        "instructions": spot['access_instructions'],
        "google_maps_link": spot['google_maps_link'],
        "rules": spot['rules']
    }


DEMO_RECIPIENT = os.getenv("DEMO_RECIPIENT_PUBKEY", "11111111111111111111111111111111")


@tools.FunctionTool
def register_parking_spot(owner_id: int, title: str, city: str, lat: float, lng: float,
                          base_price: float, access_instructions: str) -> dict:
    """Register a new parking spot. Recipient wallet is fixed to the demo wallet.

    Rejects duplicates: a spot at the same coordinates (~11m precision) or with
    the same title in the same city is treated as already registered.
    """
    title_norm = title.strip().lower()
    city_norm = city.strip().lower()
    for existing in PARKING_SPOTS.values():
        same_coords = (
            round(existing.get('lat', 0), 4) == round(lat, 4)
            and round(existing.get('lng', 0), 4) == round(lng, 4)
        )
        same_title = (
            existing.get('title', '').strip().lower() == title_norm
            and existing.get('city', '').strip().lower() == city_norm
        )
        if same_coords or same_title:
            return {
                "error": "duplicate",
                "message": f"This parking spot is already registered (id: {existing['id']}, title: {existing['title']}). Owners cannot register the same spot twice.",
                "existing_spot_id": existing['id'],
            }

    spot_id = f"spot_{uuid.uuid4().hex[:8]}"
    spot = {
        "id": spot_id,
        "owner_id": owner_id,
        "title": title,
        "city": city,
        "lat": lat,
        "lng": lng,
        "wallet_address": DEMO_RECIPIENT,
        "base_price_per_hour": base_price,
        "access_instructions": access_instructions,
        "status": "inactive",
        "verification_status": "pending",
        "rules": "Standard parking rules."
    }
    PARKING_SPOTS[spot_id] = spot
    save_state()
    return spot


@tools.FunctionTool
def verify_and_activate_spot(spot_id: str) -> dict:
    """Verify and activate a parking spot (mock)."""
    spot = PARKING_SPOTS.get(spot_id)
    if not spot:
        return {"error": "Parking spot not found"}

    spot['verification_status'] = 'verified'
    spot['status'] = 'active'

    add_log("owner_verification_agent", None, "spot_activated", f"Spot {spot_id} activated")
    save_state()

    return {"status": "success", "message": "Parking spot activated."}


def get_park_master_agent():
    instructions = """
    You are ParkMaster, an AI agent helping drivers find parking and owners
    monetize their spots. ALWAYS reply in English.

    Each user message starts with [ROLE=driver] or [ROLE=owner] and a
    [DRIVER_ID=...] or [OWNER_ID=...] tag. STRICTLY follow that role.
    Never run driver flow for an owner, or vice versa. ALWAYS pass the
    given DRIVER_ID as the driver_id arg to create_booking and the
    OWNER_ID as the owner_id arg to register_parking_spot. Never invent
    an id.

    For drivers:
    1. If they send GPS coordinates, call find_nearby_parking directly.
       If they describe their location in words (address, neighborhood,
       landmark), FIRST call geocode_address to get lat/lng, THEN call
       find_nearby_parking with those coords. Default duration: 120 min
       unless the driver specifies otherwise. Do NOT ask for coordinates
       if they gave a textual location — geocode it.
    2. Help them pick a spot, then call request_price_offer.
    3. If the driver agrees, create the booking via create_booking.
    4. When the driver says they paid, call verify_payment_onchain.
       NEVER call get_access_instructions until verify_payment_onchain
       returns status=success. If status=pending, ask them to wait
       ~30 seconds and try again.
    5. Only after payment is confirmed, call get_access_instructions.

    For owners:
    1. Owner sends a free-form line like "Title, Address, City, Price USDC".
       Parse it. ALWAYS call geocode_address on the address+city to get
       real lat/lng before registering. If geocoding fails, ask the owner
       to clarify the address.
    2. Call register_parking_spot with the geocoded lat/lng.
    3. If register_parking_spot returns error="duplicate", tell the owner
       politely that this spot is already registered (mention existing
       spot id) and stop — do NOT call verify_and_activate_spot.
    4. Otherwise, ALWAYS call verify_and_activate_spot right after
       registration so the spot is searchable immediately.
    5. Confirm registration in plain English with the spot id, address,
       and price. Do NOT search for parking — owners register, they don't
       book.

    Always explain your actions and stay concise. Use the provided tools.
    """

    model_id = os.getenv("LLM_MODEL", "openrouter/google/gemini-2.5-flash")
    agent = LlmAgent(
        name="ParkMaster",
        model=LiteLlm(model=model_id),
        instruction=instructions,
        tools=[
            geocode_address,
            find_nearby_parking,
            request_price_offer,
            create_booking,
            verify_payment_onchain,
            get_access_instructions,
            register_parking_spot,
            verify_and_activate_spot
        ]
    )
    return agent
