"""Server-side account reset: last resort when password AND authenticator/backup codes are all lost.
Run on the server by its owner:

  python -m app.accounts.cli reset --email me@x.com

Sets a new password, turns 2FA off, logs out every device. The user can turn 2FA on again in Settings.
"""

import argparse
import asyncio
import getpass
import sys

from app.accounts.recovery import admin_reset
from app.db.session import get_sessionmaker


def ask_new_password() -> str:
    first = getpass.getpass("New password (hidden): ")
    if len(first) < 10:
        sys.exit("Password needs at least 10 characters.")
    if getpass.getpass("Same password again: ") != first:
        sys.exit("Passwords don't match.")
    return first


async def reset(email: str) -> None:
    password = ask_new_password()
    async with get_sessionmaker()() as s:
        if not await admin_reset(s, email, password):
            sys.exit(f"No account for {email}.")
    print(f"OK: {email} has a new password, 2-step sign-in is off, and all devices were logged out.")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="python -m app.accounts.cli", description="Leapvoy account tools (server only)")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("reset", help="new password + 2FA off + log out everywhere (lost everything)")
    r.add_argument("--email", required=True)
    a = p.parse_args(argv)
    asyncio.run(reset(a.email))


if __name__ == "__main__":
    main()
