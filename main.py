import os
import asyncio
import logging
from dotenv import load_dotenv
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ConversationHandler
import bot_handlers
os.environ["OTEL_SDK_DISABLED"] = "true"
# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

load_dotenv()

async def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token or token == "YOUR_TELEGRAM_BOT_TOKEN":
        print("Error: TELEGRAM_BOT_TOKEN not found in .env. Please set it.")
        return

    application = ApplicationBuilder().token(token).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', bot_handlers.start)],
        states={
            bot_handlers.MAIN_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot_handlers.role_selected)],
            bot_handlers.DRIVER_ACTION: [
                MessageHandler(filters.LOCATION, bot_handlers.driver_action),
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot_handlers.driver_action)
            ],
            bot_handlers.OWNER_ACTION: [
                MessageHandler(filters.LOCATION, bot_handlers.owner_action),
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot_handlers.owner_action)
            ],
        },
        fallbacks=[CommandHandler('start', bot_handlers.start), CommandHandler('demo_reset', bot_handlers.demo_reset)],
    )

    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(bot_handlers.callback_handler))
    application.add_handler(CommandHandler('demo_reset', bot_handlers.demo_reset))
    application.add_handler(CommandHandler('demo_seed', bot_handlers.demo_seed))
    application.add_handler(CommandHandler('demo_logs', bot_handlers.demo_logs))

    print("Bot is starting... Press Ctrl+C to stop.")
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    
    # Run until the process is stopped
    while True:
        await asyncio.sleep(1)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
