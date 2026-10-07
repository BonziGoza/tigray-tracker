"""Create a Telegram StringSession for GitHub Actions.

Run locally after installing requirements. The printed session is a credential:
store it only as the TELEGRAM_SESSION GitHub repository secret.
"""
import os
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

api_id = int(input("Telegram API ID: ").strip())
api_hash = input("Telegram API hash: ").strip()

with TelegramClient(StringSession(), api_id, api_hash) as client:
    client.start()
    print("\nTELEGRAM_SESSION:")
    print(client.session.save())
