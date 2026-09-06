"""Owner bootstrap and invite management (ROADMAP AA3, AA5).

Run this to claim the owner account and to mint beta-tester invites.

    python admin_setup.py claim shagnikpal@gmail.com
    python admin_setup.py invite --role beta
    python admin_setup.py invite --role beta --email friend@example.com
    python admin_setup.py list
    python admin_setup.py promote friend@example.com --role admin

The password is read from a hidden prompt and is never taken from the command
line — an argv password lands in shell history and in the process list, where
anyone on the machine can read it.
"""

from __future__ import annotations

import argparse
import getpass
import sys

from auth import (
    AuthError,
    AuthStore,
    Permission,
    Role,
    WeakPasswordError,
    invite_link,
)
from paths import data_path

STORE_PATH = str(data_path("auth.json"))


def _prompt_new_password() -> str:
    """Read a password twice from a hidden prompt, enforcing the policy."""
    for _ in range(3):
        first = getpass.getpass("Choose a password (min 12 chars): ")
        second = getpass.getpass("Confirm password: ")
        if first != second:
            print("  Those did not match. Try again.\n")
            continue
        try:
            from auth import check_password_policy

            check_password_policy(first)
        except WeakPasswordError as error:
            print(f"  {error}\n")
            continue
        return first
    raise SystemExit("Could not set a password after 3 attempts.")


def _signin(store: AuthStore, email: str) -> str:
    password = getpass.getpass(f"Password for {email}: ")
    return store.authenticate(email, password)


def cmd_claim(store: AuthStore, args: argparse.Namespace) -> int:
    """Create the owner account and set its password."""
    user = store.bootstrap_owner(args.email)
    if user.has_password and not args.reset:
        print(f"{user.email} already has a password. Use --reset to change it.")
        return 1
    print(f"Setting the owner password for {user.email}.")
    print("This is stored only as a salted scrypt hash — the plaintext is never saved.\n")
    store.set_password(user.email, _prompt_new_password())
    print(f"\n  Owner account ready: {user.email} (role: {user.role.value})")
    print("  You now hold every permission, including machine control.")
    return 0


def cmd_invite(store: AuthStore, args: argparse.Namespace) -> int:
    """Mint a single-use invite and print the shareable link."""
    token = _signin(store, args.as_user)
    invite = store.create_invite(token, Role(args.role), email=args.email or "")
    link = invite_link(args.base_url, invite.token)

    print(f"\n  Invite created — role: {invite.role.value}, single use, expires in 14 days.")
    if invite.email:
        print(f"  Locked to: {invite.email}")
    print(f"\n  Share this link:\n  {link}\n")
    if args.email:
        print("  Suggested message:\n")
        print(f"    Hi — you're invited to beta test Nyx Ichos.")
        print(f"    Set up your account here: {link}")
        print(f"    The link works once and expires in two weeks.\n")
    return 0


def cmd_list(store: AuthStore, args: argparse.Namespace) -> int:
    token = _signin(store, args.as_user)
    print("\n  Accounts:")
    for user in store.list_users(token):
        methods = ", ".join(user["auth_methods"]) or "no login method yet"
        print(f"    {user['role']:<6} {user['email']:<32} ({methods})")

    invites = store.list_invites(token)
    pending = [i for i in invites if i["valid"]]
    print(f"\n  Pending invites: {len(pending)}")
    for invite in pending:
        target = invite["email"] or "anyone with the link"
        print(f"    {invite['role']:<6} -> {target}")
    redeemed = [i for i in invites if i["redeemed_by"]]
    if redeemed:
        print(f"\n  Redeemed: {len(redeemed)}")
        for invite in redeemed:
            print(f"    {invite['role']:<6} -> {invite['redeemed_by']}")
    print()
    return 0


def cmd_promote(store: AuthStore, args: argparse.Namespace) -> int:
    token = _signin(store, args.as_user)
    user = store.grant_role(token, args.email, Role(args.role))
    print(f"\n  {user.email} is now {user.role.value}.\n")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="admin_setup",
        description="Claim the owner account and manage beta testers for Nyx Ichos.",
    )
    parser.add_argument("--store", default=STORE_PATH, help="Path to the account store.")
    sub = parser.add_subparsers(dest="command", required=True)

    claim = sub.add_parser("claim", help="Create the owner account and set its password.")
    claim.add_argument("email")
    claim.add_argument("--reset", action="store_true", help="Change an existing password.")
    claim.set_defaults(func=cmd_claim)

    invite = sub.add_parser("invite", help="Mint a single-use invite link.")
    invite.add_argument("--as-user", required=True, help="Your email (the inviter).")
    invite.add_argument("--role", default="beta", choices=["beta", "admin", "user"])
    invite.add_argument("--email", default="", help="Lock the invite to one address.")
    invite.add_argument("--base-url", default="http://localhost:5173")
    invite.set_defaults(func=cmd_invite)

    listing = sub.add_parser("list", help="List accounts and invites.")
    listing.add_argument("--as-user", required=True)
    listing.set_defaults(func=cmd_list)

    promote = sub.add_parser("promote", help="Change an account's role.")
    promote.add_argument("email")
    promote.add_argument("--as-user", required=True)
    promote.add_argument("--role", default="admin", choices=["admin", "beta", "user"])
    promote.set_defaults(func=cmd_promote)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = AuthStore(args.store)
    try:
        return args.func(store, args)
    except AuthError as error:
        print(f"\n  {error}\n", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
