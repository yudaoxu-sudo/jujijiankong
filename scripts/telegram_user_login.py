#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sniper_engine.env import load_local_env


DEFAULT_SESSION = ROOT / ".secrets" / "telegram_user.session"


async def status(client) -> None:
    authorized = await client.is_user_authorized()
    print(f"authorized={authorized}")
    if authorized:
        me = await client.get_me()
        print(f"user_id={getattr(me, 'id', '')}")
        print(f"username={getattr(me, 'username', '')}")
        print(f"first_name={getattr(me, 'first_name', '')}")


async def qr_login(client, session_path: Path) -> None:
    if await client.is_user_authorized():
        await status(client)
        return

    qr = await client.qr_login()
    print("Open Telegram on your phone: Settings -> Devices -> Link Desktop Device")
    print("Scan this QR URL with Telegram. Do not send login codes in chat.")
    print(qr.url)

    try:
        import qrcode  # type: ignore

        out = ROOT / "output" / "telegram_user_signals" / "qr_login.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        img = qrcode.make(qr.url)
        img.save(out)
        print(f"qr_png={out}")
    except Exception as exc:
        print(f"qr_png=not_created reason={exc}")
        print("Install optional QR support with: python3 -m pip install --user qrcode[pil]")

    print(f"session_path={session_path}")
    await qr.wait(timeout=180)
    await status(client)


async def interactive_login(client, session_path: Path) -> None:
    if await client.is_user_authorized():
        await status(client)
        return
    print("This will prompt for phone/code in this terminal. Do not paste codes into chat.")
    await client.start()
    print(f"session_path={session_path}")
    await status(client)


async def main_async(args: argparse.Namespace) -> int:
    load_local_env()
    api_id = os.environ.get("TELEGRAM_API_ID", "")
    api_hash = os.environ.get("TELEGRAM_API_HASH", "")
    if not api_id or not api_hash:
        raise SystemExit("missing TELEGRAM_API_ID or TELEGRAM_API_HASH")

    try:
        from telethon import TelegramClient
    except Exception as exc:
        raise SystemExit(f"missing telethon: {exc}") from exc

    session_path = Path(os.environ.get("TELEGRAM_USER_SESSION", str(DEFAULT_SESSION)))
    session_path.parent.mkdir(parents=True, exist_ok=True)
    client = TelegramClient(str(session_path), int(api_id), api_hash)
    await client.connect()
    try:
        if args.check:
            await status(client)
        elif args.qr:
            await qr_login(client, session_path)
        else:
            await interactive_login(client, session_path)
    finally:
        await client.disconnect()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or check Telegram user session for configured channels.")
    parser.add_argument("--qr", action="store_true", help="Use Telegram QR login")
    parser.add_argument("--check", action="store_true", help="Check whether the session is authorized")
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
