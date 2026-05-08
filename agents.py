import os
import uuid
import time
from dotenv import load_dotenv
from google.adk.agents import LlmAgent
from google.adk import tools
from state import USERS, PARKING_SPOTS, BOOKINGS, AGENT_LOGS, add_log
from payments import create_solana_pay_url

load_dotenv()

# Инструменты для агентов

@tools.FunctionTool
def find_nearby_parking(lat: float, lng: float, duration_minutes: int) -> list:
    """Найти ближайшие доступные парковки на основе координат и длительности."""
    available = []
    for spot_id, spot in PARKING_SPOTS.items():
        if spot['status'] == 'active':
            # Имитация расчета расстояния
            distance_km = abs(spot['lat'] - lat) * 111 + abs(spot['lng'] - lng) * 111
            distance_text = f"{distance_km:.1f} км"
            available.append({
                "id": spot_id,
                "title": spot['title'],
                "price": spot['base_price_per_hour'] * (duration_minutes / 60),
                "distance": distance_text,
                "rules": spot['rules']
            })
    return available

@tools.FunctionTool
def request_price_offer(spot_id: str, duration_minutes: int) -> dict:
    """Запросить финальное ценовое предложение для конкретной парковки."""
    spot = PARKING_SPOTS.get(spot_id)
    if not spot:
        return {"error": "Парковка не найдена"}
    
    base_price = spot['base_price_per_hour'] * (duration_minutes / 60)
    # Имитация переговоров: скидка 10% при бронировании более 2 часов
    final_price = base_price * 0.9 if duration_minutes > 120 else base_price
    reasoning = "Применена скидка 10% за длительное бронирование." if duration_minutes > 120 else "Применен стандартный тариф."
    
    return {
        "spot_id": spot_id,
        "base_price": base_price,
        "final_price": final_price,
        "reasoning": reasoning
    }

@tools.FunctionTool
def create_booking(driver_id: int, spot_id: str, price_usdc: float, duration_minutes: int) -> dict:
    """Создать бронирование парковки."""
    booking_id = f"booking_{uuid.uuid4().hex[:8]}"
    reference = f"ref_{uuid.uuid4().hex[:12]}"
    
    spot = PARKING_SPOTS.get(spot_id)
    if not spot:
        return {"error": "Парковка не найдена"}

    booking = {
        "id": booking_id,
        "driver_id": driver_id,
        "spot_id": spot_id,
        "duration_minutes": duration_minutes,
        "price_usdc": price_usdc,
        "status": "pending_payment",
        "payment_reference": reference,
        "solana_pay_url": create_solana_pay_url(spot['wallet_address'], price_usdc, reference, booking_id),
        "created_at": time.time()
    }
    
    BOOKINGS[booking_id] = booking
    add_log("driver_agent", booking_id, "booking_created", f"Создано бронирование {spot_id} по цене {price_usdc} USDC")
    
    return booking

@tools.FunctionTool
def confirm_mock_payment(booking_id: str) -> dict:
    """Подтвердить оплату бронирования (имитация)."""
    booking = BOOKINGS.get(booking_id)
    if not booking:
        return {"error": "Бронирование не найдено"}
    
    booking['status'] = 'paid'
    spot = PARKING_SPOTS.get(booking['spot_id'])
    spot['status'] = 'reserved'
    
    add_log("driver_agent", booking_id, "payment_confirmed", "Пользователь вручную подтвердил имитацию оплаты.")
    
    return {"status": "success", "message": "Оплата подтверждена."}

@tools.FunctionTool
def get_access_instructions(booking_id: str) -> dict:
    """Получить инструкции по доступу для оплаченного бронирования."""
    booking = BOOKINGS.get(booking_id)
    if not booking or booking['status'] != 'paid':
        return {"error": "Бронирование не оплачено или не найдено"}
    
    spot = PARKING_SPOTS.get(booking['spot_id'])
    booking['status'] = 'access_released'
    
    add_log("parking_spot_agent", booking_id, "access_released", "Инструкции по доступу предоставлены водителю.")
    
    return {
        "instructions": spot['access_instructions'],
        "google_maps_link": spot['google_maps_link'],
        "rules": spot['rules']
    }

@tools.FunctionTool
def register_parking_spot(owner_id: int, title: str, city: str, lat: float, lng: float, 
                          wallet_address: str, base_price: float, access_instructions: str) -> dict:
    """Зарегистрировать новое парковочное место."""
    spot_id = f"spot_{uuid.uuid4().hex[:8]}"
    spot = {
        "id": spot_id,
        "owner_id": owner_id,
        "title": title,
        "city": city,
        "lat": lat,
        "lng": lng,
        "wallet_address": wallet_address,
        "base_price_per_hour": base_price,
        "access_instructions": access_instructions,
        "status": "inactive",
        "verification_status": "pending",
        "rules": "Стандартные правила парковки."
    }
    PARKING_SPOTS[spot_id] = spot
    return spot

@tools.FunctionTool
def verify_and_activate_spot(spot_id: str) -> dict:
    """Верифицировать и активировать парковочное место (имитация)."""
    spot = PARKING_SPOTS.get(spot_id)
    if not spot:
        return {"error": "Парковка не найдена"}
    
    spot['verification_status'] = 'verified'
    spot['status'] = 'active'
    
    add_log("owner_verification_agent", None, "spot_activated", f"Активирована парковка {spot_id}")
    
    return {"status": "success", "message": "Парковка активирована."}

# Инициализация агента

def get_park_master_agent():
    instructions = """
    Ты — ParkMaster, ИИ-агент, помогающий водителям находить парковку, а владельцам — монетизировать их места.
    
    Для водителей:
    1. Если присылают локацию, используй find_nearby_parking.
    2. Помоги выбрать место и запроси предложение по цене через request_price_offer.
    3. Если водитель согласен, создай бронирование через create_booking.
    4. После оплаты используй confirm_mock_payment, а затем get_access_instructions.
    
    Для владельцев:
    1. Помоги зарегистрировать место через register_parking_spot.
    2. После регистрации используй verify_and_activate_spot для имитации процесса верификации.
    
    Всегда объясняй свои действия и будь вежлив. Используй предоставленные инструменты.
    """
    
    agent = LlmAgent(
        name="ParkMaster",
        model="gemini-2.5-flash",
        instruction=instructions,
        tools=[
            find_nearby_parking, 
            request_price_offer, 
            create_booking, 
            confirm_mock_payment, 
            get_access_instructions,
            register_parking_spot,
            verify_and_activate_spot
        ]
    )
    return agent
