#!/usr/bin/env python3
# dashboard/admin_cli.py
# ═══════════════════════════════════════════════════════════════
# YieldIQ Admin CLI
# Usage:
#   python admin_cli.py --set-tier user@email.com pro
#   python admin_cli.py --add-user user@email.com password123 premium
#   python admin_cli.py --list-users
#   python admin_cli.py --deactivate user@email.com
#   python admin_cli.py --clean-sessions
#   python admin_cli.py --unlock-account user@email.com
# ═══════════════════════════════════════════════════════════════
import argparse
import sys
from pathlib import Path

# Allow running from any directory
sys.path.insert(0, str(Path(__file__).parent.parent))

from dashboard.auth import (
    init_auth_db,
    register_user,
    set_tier,
    list_users,
    deactivate_user,
    delete_expired_sessions,
    unlock_account,
)


def cmd_set_tier(args):
    result = set_tier(args.email, args.tier)
    if result["ok"]:
        print(f"✅  {args.email}  →  tier set to  '{args.tier}'")
    else:
        print(f"❌  {result['error']}")
        sys.exit(1)


def cmd_add_user(args):
    tier = args.tier if hasattr(args, "tier") and args.tier else "free"
    result = register_user(args.email, args.password, tier)
    if result["ok"]:
        print(f"✅  User created:  {args.email}  (tier: {tier},  id: {result['user_id']})")
    else:
        print(f"❌  {result['error']}")
        sys.exit(1)


def cmd_list_users(args):
    users = list_users()
    if not users:
        print("No users found.")
        return
    print(f"\n{'EMAIL':<35} {'TIER':<10} {'ACTIVE':<8} {'CREATED':<22} {'LAST LOGIN'}")
    print("─" * 100)
    for u in users:
        active    = "yes" if u["is_active"] else "NO"
        last_login = u["last_login"] or "never"
        print(f"{u['email']:<35} {u['tier']:<10} {active:<8} {u['created_at']:<22} {last_login}")
    print(f"\nTotal: {len(users)} user(s)")


def cmd_deactivate(args):
    result = deactivate_user(args.email)
    if result["ok"]:
        print(f"✅  {args.email}  deactivated")
    else:
        print(f"❌  {result['error']}")
        sys.exit(1)


def cmd_clean_sessions(args):
    n = delete_expired_sessions()
    print(f"✅  Deleted {n} expired session(s)")


def cmd_unlock_account(args):
    result = unlock_account(args.email)
    if result["ok"]:
        cleared = result["cleared"]
        if cleared:
            print(f"✅  {args.email}  unlocked  ({cleared} failed attempt record(s) cleared)")
        else:
            print(f"ℹ️   {args.email}  had no active lockout (0 attempt records found)")
    else:
        print(f"❌  {result.get('error', 'Unknown error')}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        prog="admin_cli",
        description="YieldIQ admin tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python admin_cli.py --set-tier user@email.com pro
  python admin_cli.py --add-user new@email.com secretpass123 premium
  python admin_cli.py --list-users
  python admin_cli.py --deactivate bad@email.com
  python admin_cli.py --clean-sessions
  python admin_cli.py --unlock-account locked@email.com
        """,
    )

    sub = parser.add_subparsers(dest="command")

    # --set-tier
    p_tier = parser.add_argument_group("set-tier")
    parser.add_argument("--set-tier", nargs=2, metavar=("EMAIL", "TIER"),
                        help="Set tier for a user:  --set-tier user@x.com pro")

    # --add-user
    parser.add_argument("--add-user", nargs="+", metavar=("EMAIL", "PASSWORD"),
                        help="Add user:  --add-user email pass [tier]")

    # --list-users
    parser.add_argument("--list-users", action="store_true",
                        help="List all users")

    # --deactivate
    parser.add_argument("--deactivate", metavar="EMAIL",
                        help="Deactivate a user account")

    # --clean-sessions
    parser.add_argument("--clean-sessions", action="store_true",
                        help="Delete expired session tokens")

    # --unlock-account
    parser.add_argument("--unlock-account", metavar="EMAIL",
                        help="Clear login lockout for an account:  --unlock-account user@x.com")

    args = parser.parse_args()

    # Ensure DB is ready
    init_auth_db()

    if args.set_tier:
        email, tier = args.set_tier
        class _A:
            pass
        a = _A(); a.email = email; a.tier = tier
        cmd_set_tier(a)

    elif args.add_user:
        parts = args.add_user
        if len(parts) < 2:
            print("❌  --add-user requires at least EMAIL and PASSWORD")
            sys.exit(1)
        class _A:
            pass
        a = _A()
        a.email    = parts[0]
        a.password = parts[1]
        a.tier     = parts[2] if len(parts) > 2 else "free"
        cmd_add_user(a)

    elif args.list_users:
        cmd_list_users(args)

    elif args.deactivate:
        class _A:
            pass
        a = _A(); a.email = args.deactivate
        cmd_deactivate(a)

    elif args.clean_sessions:
        cmd_clean_sessions(args)

    elif args.unlock_account:
        class _A:
            pass
        a = _A(); a.email = args.unlock_account
        cmd_unlock_account(a)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
