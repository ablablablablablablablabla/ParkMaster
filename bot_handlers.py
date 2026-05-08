import os
import io
import asyncio
import time
import html
import logging
import traceback

log = logging.getLogger(__name__)

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, filters, CallbackQueryHandler
from google.adk.runners import InMemoryRunner
from google.genai import types

from state import USERS, PARKING_SPOTS, BOOKINGS, AGENT_LOGS, add_log, save_state, load_state
from mock_data import INITIAL_PARKING_SPOTS
from agents import get_park_master_agent
from qr import generate_qr_code
from payments import verify_payment, USDC_DEVNET_MINT

WATCH_TASKS = {}  # booking_id -> asyncio.Task
WATCH_INTERVAL_SEC = 5
WATCH_TIMEOUT_SEC = 600

# Conversation states
MAIN_MENU, DRIVER_ACTION, OWNER_ACTION = range(3)

agent = get_park_master_agent()
RUNNERS = {}

load_state()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in USERS:
        USERS[user_id] = {"id": user_id, "name": update.effective_user.first_name}

    if not PARKING_SPOTS:
        for spot in INITIAL_PARKING_SPOTS:
            PARKING_SPOTS[spot['id']] = spot

    reply_keyboard = [["🚗 I'm a driver", "🏠 I'm an owner"]]
    await update.message.reply_text(
        "Hi! I'm ParkMaster — your AI assistant for finding and renting out parking spots.\n\nWhich are you today?",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    return MAIN_MENU


async def role_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower()
    user_id = update.effective_user.id

    if "driver" in text:
        USERS[user_id]["role"] = "driver"
        await update.message.reply_text(
            "Great! Send me your location (button below) or type an address, "
            "and I'll find the closest spots for you.",
            reply_markup=ReplyKeyboardMarkup(
                [[KeyboardButton("📍 Send location", request_location=True)], ["Cancel"]],
                resize_keyboard=True
            )
        )
        return DRIVER_ACTION
    elif "owner" in text:
        USERS[user_id]["role"] = "owner"
        await update.message.reply_text(
            "Awesome! Let's register your parking spot. Send me the title, "
            "address, and base hourly price.",
            reply_markup=ReplyKeyboardMarkup([["Cancel"]], resize_keyboard=True)
        )
        return OWNER_ACTION
    return MAIN_MENU


async def handle_agent_call(user_id, message_text):
    session_id = str(user_id)
    full_response = ""

    if session_id not in RUNNERS:
        user_runner = InMemoryRunner(agent=agent)
        user_runner.auto_create_session = True
        RUNNERS[session_id] = user_runner

    current_runner = RUNNERS[session_id]

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
            if hasattr(event, 'text') and event.text:
                full_response += event.text
            elif hasattr(event, 'content') and event.content:
                content_event = event.content
                if isinstance(content_event, str):
                    full_response += content_event
                elif hasattr(content_event, 'parts'):
                    for part in content_event.parts:
                        if hasattr(part, 'text') and part.text:
                            full_response += part.text
    except Exception as e:
        log.exception("Error calling agent")
        full_response = f"Sorry, I had trouble processing that: {e}"

    return full_response


async def driver_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if update.message.text and update.message.text.lower() == "cancel":
        return await start(update, context)

    if update.message.location:
        loc = update.message.location
        prompt = (
            f"[ROLE=driver] [DRIVER_ID={user_id}] My location: lat={loc.latitude}, lng={loc.longitude}. "
            "Find me parking for 2 hours. List options and recommend the best one."
        )
    else:
        prompt = f"[ROLE=driver] [DRIVER_ID={user_id}] {update.message.text}"

    status_msg = await update.message.reply_text("🔎 Polling parking agents...")

    response = await handle_agent_call(user_id, prompt)

    keyboard = []
    for spot_id, spot in PARKING_SPOTS.items():
        if spot['status'] == 'active' and (spot['title'].lower() in response.lower() or spot_id in response):
            keyboard.append([InlineKeyboardButton(f"Book {spot['title']}", callback_data=f"book_{spot_id}")])

    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None

    await status_msg.delete()
    await update.message.reply_text(response or "Agent didn't reply. Try again.", reply_markup=reply_markup)

    # If the agent created a booking via tool call, render QR codes now.
    booking = _latest_pending_booking(user_id)
    if booking and not booking.get("_qr_sent"):
        await _send_payment_qrs(update.message.chat_id, user_id, booking, response, context)
        booking["_qr_sent"] = True
        save_state()

    return DRIVER_ACTION


def _latest_pending_booking(user_id):
    for b in sorted(BOOKINGS.values(), key=lambda x: x['created_at'], reverse=True):
        if b['driver_id'] == user_id and b['status'] == 'pending_payment':
            return b
    return None


async def _send_payment_qrs(chat_id, user_id, booking, agent_text, context):
    safe_text = html.escape(agent_text or "")
    amount = booking['price_usdc']
    recipient = booking['recipient_wallet']
    pay_url = booking['solana_pay_url']

    pay_qr = generate_qr_code(pay_url)
    await context.bot.send_photo(
        chat_id=chat_id,
        photo=pay_qr,
        caption=(
            f"✅ <b>Booking created!</b>\n\n"
            f"{safe_text}\n\n"
            f"💰 <b>{amount:.2f} USDC</b> (devnet)\n"
            f"🪙 Mint: <code>{USDC_DEVNET_MINT}</code>\n\n"
            f"📲 <b>Scan this QR with Phantom / Solflare</b> or tap the link:\n"
            f"<a href='{html.escape(pay_url)}'>Pay via Solana Pay</a>"
        ),
        parse_mode='HTML',
    )

    addr_qr = generate_qr_code(recipient)
    await context.bot.send_photo(
        chat_id=chat_id,
        photo=addr_qr,
        caption=(
            f"📥 <b>Recipient address</b> (for manual USDC devnet transfer):\n"
            f"<code>{recipient}</code>\n\n"
            f"⚠️ If you scan this QR, set the amount and token (USDC) manually."
        ),
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Check payment", callback_data=f"check_{booking['id']}")],
            [InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{booking['id']}")],
        ])
    )

    await context.bot.send_message(
        chat_id=chat_id,
        text="🤖 I'm watching the chain. As soon as the payment lands, I'll send the access instructions automatically."
    )

    if booking['id'] not in WATCH_TASKS:
        task = asyncio.create_task(
            _watch_payment(booking['id'], user_id, chat_id, context)
        )
        WATCH_TASKS[booking['id']] = task


async def owner_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if update.message.text and update.message.text.lower() == "cancel":
        return await start(update, context)

    status_msg = await update.message.reply_text("📝 Processing parking spot data...")
    response = await handle_agent_call(
        user_id,
        f"[ROLE=owner] [OWNER_ID={user_id}] {update.message.text}"
    )

    await status_msg.delete()
    await update.message.reply_text(response)
    return OWNER_ACTION


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = query.data

    if data.startswith("book_"):
        spot_id = data.split("_", 1)[1]
        prompt = f"[ROLE=driver] [DRIVER_ID={user_id}] I want to book parking spot {spot_id} for 2 hours. Create the booking and send a confirmation."
        await query.message.reply_text("⏳ Creating booking...")
        response = await handle_agent_call(user_id, prompt)

        booking = _latest_pending_booking(user_id)
        if not booking:
            await query.message.reply_text(response)
            return

        if not booking.get("_qr_sent"):
            await _send_payment_qrs(query.message.chat_id, user_id, booking, response, context)
            booking["_qr_sent"] = True
            save_state()

    elif data.startswith("check_"):
        booking_id = data.split("_", 1)[1]
        await query.message.reply_text("🔄 Checking the transaction on Solana devnet...")
        await _check_and_release(booking_id, user_id, query.message.chat_id, context)

    elif data.startswith("cancel_"):
        booking_id = data.split("_", 1)[1]
        booking = BOOKINGS.get(booking_id)
        if booking and booking['status'] == 'pending_payment':
            booking['status'] = 'cancelled'
        task = WATCH_TASKS.pop(booking_id, None)
        if task and not task.done():
            task.cancel()
        await query.message.reply_text("❌ Booking cancelled.")


async def _watch_payment(booking_id, user_id, chat_id, context):
    """Poll devnet RPC until payment is found, timed out, or cancelled."""
    started = time.time()
    try:
        while time.time() - started < WATCH_TIMEOUT_SEC:
            await asyncio.sleep(WATCH_INTERVAL_SEC)
            booking = BOOKINGS.get(booking_id)
            if not booking or booking['status'] != 'pending_payment':
                return  # cancelled or already paid
            sig = await verify_payment(
                reference=booking['payment_reference'],
                expected_recipient=booking['recipient_wallet'],
                expected_amount=booking['price_usdc'],
                mint=booking['mint'],
                created_after=booking.get('created_at', 0.0),
            )
            if sig:
                booking['status'] = 'paid'
                booking['payment_signature'] = sig
                spot = PARKING_SPOTS.get(booking['spot_id'])
                if spot:
                    spot['status'] = 'reserved'
                add_log("payment_watcher", booking_id, "payment_confirmed", f"sig={sig}")
                save_state()
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=(
                        f"✅ <b>Payment received!</b>\n"
                        f"🔗 <a href='https://explorer.solana.com/tx/{sig}?cluster=devnet'>View tx in Solana Explorer</a>\n"
                        f"<code>{sig}</code>"
                    ),
                    parse_mode='HTML',
                )
                response = await handle_agent_call(
                    user_id,
                    f"[ROLE=driver] [DRIVER_ID={user_id}] Payment for {booking_id} is confirmed. Give me the access instructions."
                )
                await context.bot.send_message(chat_id=chat_id, text=response)
                return
        booking = BOOKINGS.get(booking_id)
        if booking and booking['status'] == 'pending_payment':
            booking['status'] = 'expired'
            await context.bot.send_message(
                chat_id=chat_id,
                text="⌛ Payment window expired. If you already paid, tap «Check payment»."
            )
    except asyncio.CancelledError:
        pass
    finally:
        WATCH_TASKS.pop(booking_id, None)


async def _check_and_release(booking_id, user_id, chat_id, context):
    booking = BOOKINGS.get(booking_id)
    if not booking:
        await context.bot.send_message(chat_id=chat_id, text="Booking not found.")
        return
    if booking['status'] in ('paid', 'access_released'):
        sig = booking.get('payment_signature')
        link = (
            f"\n🔗 https://explorer.solana.com/tx/{sig}?cluster=devnet\nTx: {sig}"
            if sig else ""
        )
        await context.bot.send_message(chat_id=chat_id, text=f"✅ Payment already confirmed.{link}")
        response = await handle_agent_call(
            user_id,
            f"[ROLE=driver] [DRIVER_ID={user_id}] Give me the access instructions for {booking_id}."
        )
        await context.bot.send_message(chat_id=chat_id, text=response)
        return
    response = await handle_agent_call(
        user_id,
        f"[ROLE=driver] [DRIVER_ID={user_id}] Check payment for {booking_id} via verify_payment_onchain. If status=success, give me the instructions."
    )
    await context.bot.send_message(chat_id=chat_id, text=response)


async def demo_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    USERS.clear()
    PARKING_SPOTS.clear()
    BOOKINGS.clear()
    AGENT_LOGS.clear()
    for spot in INITIAL_PARKING_SPOTS:
        PARKING_SPOTS[spot['id']] = spot
    save_state()
    await update.message.reply_text("Demo state reset. Parking spots restored from dataset.")


async def demo_seed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for spot in INITIAL_PARKING_SPOTS:
        if spot['id'] not in PARKING_SPOTS:
            PARKING_SPOTS[spot['id']] = spot
    await update.message.reply_text("Demo data loaded.")


async def demo_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not AGENT_LOGS:
        await update.message.reply_text("No logs yet. Try booking something!")
        return
    text = "📜 AI agent decision log:\n\n"
    for log in AGENT_LOGS[-8:]:
        t = time.strftime('%H:%M:%S', time.localtime(log['created_at']))
        text += f"🕒 {t} | [{log['agent']}]\n🔹 Action: {log['action']}\n💡 Reason: {log['reasoning']}\n\n"
    await update.message.reply_text(text)
