import asyncio
from telegram import Bot

async def fix_bot():
    token = "REDACTED_TELEGRAM_TOKEN"
    bot = Bot(token)
    try:
        me = await bot.get_me()
        print(f"Bot identified: @{me.username}")
        
        # 1. Delete Webhook
        print("Deleting any existing webhook...")
        await bot.delete_webhook(drop_pending_updates=True)
        
        # 2. Logout (This is useful to terminate other sessions if the library supports it, 
        # but in python-telegram-bot it's mainly for clearing the cache. 
        # For Conflict, we mostly need to stop the other process.)
        print("Webhook deleted and updates dropped.")
        
        print("Waiting 5 seconds to let the session clear on Telegram side...")
        await asyncio.sleep(5)
        print("Done. Now starting the bot on Batam.")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(fix_bot())
