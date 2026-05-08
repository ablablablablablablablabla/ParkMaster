import os
import io
import asyncio
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, filters, CallbackQueryHandler
from state import USERS, PARKING_SPOTS, BOOKINGS, AGENT_LOGS, add_log
from mock_data import INITIAL_PARKING_SPOTS
from agents import get_park_master_agent
from qr import generate_qr_code
from google.adk.runners import InMemoryRunner
import time
from google.genai import types
import html
from telegram.constants import ParseMode

# States
MAIN_MENU, DRIVER_ACTION, OWNER_ACTION = range(3)

agent = get_park_master_agent()
RUNNERS = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in USERS:
        USERS[user_id] = {"id": user_id, "name": update.effective_user.first_name}
    
    # Load mock data if not loaded
    if not PARKING_SPOTS:
        for spot in INITIAL_PARKING_SPOTS:
            PARKING_SPOTS[spot['id']] = spot
            
    reply_keyboard = [["🚗 Я водитель", "🏠 Я владелец"]]
    await update.message.reply_text(
        "Привет! Я ParkMaster — твой ИИ-помощник для поиска и сдачи в аренду парковок.\n\nКто ты сегодня?",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    return MAIN_MENU

async def role_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id
    
    if "водитель" in text:
        USERS[user_id]["role"] = "driver"
        await update.message.reply_text(
            "Отлично! Отправь мне свою геолокацию (кнопка ниже) или напиши адрес, и я найду ближайшие места для тебя.",
            reply_markup=ReplyKeyboardMarkup([[KeyboardButton("📍 Отправить локацию", request_location=True)], ["Отмена"]], resize_keyboard=True)
        )
        return DRIVER_ACTION
    elif "владелец" in text:
        USERS[user_id]["role"] = "owner"
        await update.message.reply_text(
            "Здорово! Давай зарегистрируем твою парковку. Просто напиши мне название, адрес и базовую цену в час.",
            reply_markup=ReplyKeyboardMarkup([["Отмена"]], resize_keyboard=True)
        )
        return OWNER_ACTION
    return MAIN_MENU


async def handle_agent_call(user_id, message_text):
    session_id = str(user_id)
    full_response = ""

    # --- Изолированная среда для каждого юзера ---
    if session_id not in RUNNERS:
        user_runner = InMemoryRunner(agent=agent)
        user_runner.auto_create_session = True
        RUNNERS[session_id] = user_runner

    current_runner = RUNNERS[session_id]
    # ---------------------------------------------

    try:
        content = types.Content(
            role='user',
            parts=[types.Part(text=message_text)]
        )

        async for event in current_runner.run_async(
                user_id=session_id,
                session_id=session_id,
                new_message=content
        ):
            # ADK Event processing
            if hasattr(event, 'text') and event.text:
                full_response += event.text
            elif hasattr(event, 'content') and event.content:
                content_event = event.content
                if isinstance(content_event, str):
                    full_response += content_event
                elif hasattr(content_event, 'parts'):
                    for part in content_event.parts:
                        # ИСПРАВЛЕНИЕ: строго проверяем, что part.text является строкой / не None
                        if hasattr(part, 'text') and part.text:
                            full_response += part.text
    except Exception as e:
        print(f"Error calling agent: {e}")
        full_response = "Извини, у меня возникли трудности с обработкой запроса. Попробуй еще раз."

    return full_response

async def driver_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if update.message.text == "Отмена":
        return await start(update, context)

    prompt = ""
    if update.message.location:
        loc = update.message.location
        prompt = f"Моя локация: lat={loc.latitude}, lng={loc.longitude}. Найди мне парковку на 2 часа. Расскажи про варианты и порекомендуй лучший."
    else:
        prompt = update.message.text

    status_msg = await update.message.reply_text("🔎 Опрашиваю агентов парковок...")
    
    response = await handle_agent_call(user_id, prompt)
    
    # Пытаемся добавить кнопки для парковок, упомянутых в ответе
    keyboard = []
    for spot_id, spot in PARKING_SPOTS.items():
        if spot['status'] == 'active' and (spot['title'].lower() in response.lower() or spot_id in response):
             keyboard.append([InlineKeyboardButton(f"Забронировать {spot['title']}", callback_data=f"book_{spot_id}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None

    await status_msg.delete()
    await update.message.reply_text(response or "Агент не ответил. Попробуй еще раз.", reply_markup=reply_markup)
    return DRIVER_ACTION

async def owner_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if update.message.text == "Отмена":
        return await start(update, context)
    
    status_msg = await update.message.reply_text("📝 Обрабатываю данные парковки...")
    response = await handle_agent_call(user_id, update.message.text)
    
    await status_msg.delete()
    await update.message.reply_text(response)
    return OWNER_ACTION


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = query.data

    # ПЕРВАЯ ПРОВЕРКА — используем if
    if data.startswith("book_"):
        spot_id = data.split("_", 1)[1]

        # 1. ПЕРЕДАЕМ РЕАЛЬНЫЙ ID ЮЗЕРА АГЕНТУ
        prompt = (
            f"Я хочу забронировать парковку {spot_id} на 2 часа. "
            f"Мой driver_id: {user_id}. "  # <--- КЛЮЧЕВОЕ ИЗМЕНЕНИЕ
            f"Вызови инструмент create_booking, обязательно передав мой driver_id. "
            f"ВНИМАНИЕ: СТРОГО ЗАПРЕЩЕНО использовать confirm_mock_payment. ОСТАНОВИСЬ ПОСЛЕ БРОНИРОВАНИЯ."
        )

        await query.message.reply_text("⏳ Формирую бронирование...")
        response = await handle_agent_call(user_id, prompt)

        # 2. ТЕПЕРЬ БОТ НАЙДЕТ БРОНЬ, ПОТОМУ ЧТО ID СОВПАДАЮТ
        booking = None
        for b in sorted(BOOKINGS.values(), key=lambda x: x['created_at'], reverse=True):
            if b['driver_id'] == user_id and b['status'] == 'pending_payment':
                booking = b
                break

        # 3. ВЫВОДИМ ФОТО И ССЫЛКИ
        if booking:
            safe_response = html.escape(response)
            try:
                with open('QR.jpg', 'rb') as photo:
                    await query.message.reply_photo(
                        photo=photo,
                        caption=(
                            f"✅ <b>Бронирование создано!</b>\n\n"
                            f"{safe_response}\n\n"
                            f"💰 Сумма: <code>{booking['price_usdc']}</code> USDC\n\n"
                            f"🔗 <b><a href='{booking['solana_pay_url']}'>Оплатить через Solana Pay</a></b>"
                        ),
                        parse_mode=ParseMode.HTML,
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("✅ Оплата подтверждена (Mock)",
                                                 callback_data=f"confirm_{booking['id']}")
                        ]])
                    )
            except FileNotFoundError:
                await query.message.reply_text(
                    f"✅ <b>Бронирование создано!</b>\n\n{safe_response}\n\n"
                    f"🔗 <b><a href='{booking['solana_pay_url']}'>Оплатить через Solana Pay</a></b>\n\n"
                    f"⚠️ Файл QR.jpg не найден.",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("✅ Оплата подтверждена (Mock)", callback_data=f"confirm_{booking['id']}")
                    ]])
                )
        else:
            await query.message.reply_text(response)
    # ВТОРАЯ ПРОВЕРКА — здесь уже elif
    elif data.startswith("confirm_"):
        booking_id = data.split("_", 1)[1]
        prompt = f"Я оплатил бронирование {booking_id}. Подтверди оплату и выдай мне полные инструкции по доступу."
        await query.message.reply_text("🔄 Проверяю транзакцию в сети Solana...")
        response = await handle_agent_call(user_id, prompt)
        await query.message.reply_text(response)
async def demo_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    USERS.clear()
    PARKING_SPOTS.clear()
    BOOKINGS.clear()
    AGENT_LOGS.clear()
    for spot in INITIAL_PARKING_SPOTS:
        PARKING_SPOTS[spot['id']] = spot
    await update.message.reply_text("Состояние демо-режима сброшено. Парковки из датасета восстановлены.")

async def demo_seed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for spot in INITIAL_PARKING_SPOTS:
        if spot['id'] not in PARKING_SPOTS:
            PARKING_SPOTS[spot['id']] = spot
    await update.message.reply_text("Демонстрационные данные загружены.")

async def demo_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not AGENT_LOGS:
        await update.message.reply_text("Логов пока нет. Попробуйте что-нибудь забронировать!")
        return
    text = "📜 Логи решений ИИ-агентов:\n\n"
    for log in AGENT_LOGS[-8:]:
        t = time.strftime('%H:%M:%S', time.localtime(log['created_at']))
        text += f"🕒 {t} | [{log['agent']}]\n🔹 Действие: {log['action']}\n💡 Причина: {log['reasoning']}\n\n"
    await update.message.reply_text(text)
