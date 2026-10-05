"""Telegram setup CLI (in-app screens replace this in Step 8).

  python -m app.telegram.cli keygen
  python -m app.telegram.cli login    --email me@x.com --phone +919876543210
  python -m app.telegram.cli channels --email me@x.com
  python -m app.telegram.cli enable   --email me@x.com -1001234567890 [...]
  python -m app.telegram.cli disable  --email me@x.com -1001234567890 [...]
  python -m app.telegram.cli backfill --email me@x.com --days 90
  python -m app.telegram.cli logout   --email me@x.com
"""

import argparse
import asyncio
import base64
import getpass
import os
import sys
from datetime import UTC, datetime, timedelta

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession

from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.telegram import reader, store


async def _user_session(email: str):
    async with get_sessionmaker()() as s:
        user_id = await store.get_or_create_user(s, email)
        session_str = await store.load_session(s, user_id)
    if session_str is None:
        raise SystemExit(f"No Telegram login for {email}. Run: login --email {email} --phone +91...")
    return user_id, session_str


async def login(email: str, phone: str) -> None:
    settings = get_settings()
    if not (settings.telegram_api_id and settings.telegram_api_hash):
        raise SystemExit("Set TELEGRAM_API_ID and TELEGRAM_API_HASH in .env first.")
    client = TelegramClient(StringSession(), settings.telegram_api_id, settings.telegram_api_hash)
    await client.connect()
    try:
        await client.send_code_request(phone)
        code = input("Code Telegram sent you: ").strip()
        try:
            await client.sign_in(phone, code)
        except SessionPasswordNeededError:
            await client.sign_in(password=getpass.getpass("Telegram 2-step password: "))
        me = await client.get_me()
        async with get_sessionmaker()() as s:
            user_id = await store.get_or_create_user(s, email)
            await store.save_session(s, user_id, phone, StringSession.save(client.session))
        print(f"OK: Logged in as {me.first_name}. Session saved (encrypted).")
    finally:
        await client.disconnect()


async def channels(email: str) -> None:
    user_id, session_str = await _user_session(email)
    client = await reader.connect(session_str)
    try:
        dialogs = [d for d in await client.get_dialogs() if d.is_channel or d.is_group]
    finally:
        await client.disconnect()
    async with get_sessionmaker()() as s:
        await store.upsert_channels(
            s, user_id, [(d.id, d.name or "", getattr(d.entity, "username", None)) for d in dialogs]
        )
        rows = await store.list_channels(s, user_id)
    print(f"{'ID':>16}  ON   TITLE")
    for c in rows:
        print(f"{c.tg_chat_id:>16}  {'ON ' if c.enabled else 'off'}   {c.title}")
    print("\nTurn on: enable --email ... <ID> [<ID> ...]")


async def set_enabled(email: str, chat_ids: list[int], enabled: bool) -> None:
    async with get_sessionmaker()() as s:
        user_id = await store.get_or_create_user(s, email)
        changed = await store.set_enabled(s, user_id, chat_ids, enabled)
    print(f"{'Enabled' if enabled else 'Disabled'} {changed} channel(s). Unknown IDs? Run `channels` first.")


async def backfill(email: str, days: int) -> None:
    user_id, session_str = await _user_session(email)
    client = await reader.connect(session_str)
    try:
        since = datetime.now(UTC) - timedelta(days=days)
        saved = await reader.catch_up(client, get_sessionmaker(), user_id, since=since, from_start=True)
    finally:
        await client.disconnect()
    print(f"OK: Backfill done: {saved} new post(s) from the last {days} days.")


async def logout(email: str) -> None:
    user_id, session_str = await _user_session(email)
    try:
        client = await reader.connect(session_str)
        await client.log_out()  # ends the session on Telegram's side too
    except reader.SessionRevoked:
        pass
    async with get_sessionmaker()() as s:
        await store.delete_session(s, user_id)
    print("OK: Telegram disconnected; session deleted from the server.")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="python -m app.telegram.cli", description="Leapvoy Telegram setup")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("keygen", help="print a new MASTER_KEY for .env")
    for name, help_ in [
        ("login", "log in to Telegram (phone → code → 2-step password)"),
        ("channels", "list joined channels/groups and which are on"),
        ("enable", "turn channels on"),
        ("disable", "turn channels off"),
        ("backfill", "save older posts from enabled channels"),
        ("logout", "disconnect Telegram and delete the saved session"),
    ]:
        sp = sub.add_parser(name, help=help_)
        sp.add_argument("--email", required=True)
        if name == "login":
            sp.add_argument("--phone", required=True, help="with country code, e.g. +919876543210")
        if name in ("enable", "disable"):
            sp.add_argument("chat_ids", nargs="+", type=int)
        if name == "backfill":
            sp.add_argument("--days", type=int, default=90)
    a = p.parse_args(argv)
    # channel names have emojis; Windows pipes default to cp1252 and would crash on print
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if a.cmd == "keygen":
        print("MASTER_KEY=" + base64.b64encode(os.urandom(32)).decode())
        return
    job = {
        "login": lambda: login(a.email, a.phone),
        "channels": lambda: channels(a.email),
        "enable": lambda: set_enabled(a.email, a.chat_ids, True),
        "disable": lambda: set_enabled(a.email, a.chat_ids, False),
        "backfill": lambda: backfill(a.email, a.days),
        "logout": lambda: logout(a.email),
    }[a.cmd]
    asyncio.run(job())


if __name__ == "__main__":
    main()
