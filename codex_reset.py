#!/usr/bin/env python3
"""
codex-reset — redeem your Codex "banked rate-limit reset" from the CLI.

OpenAI rolled out savable rate-limit resets for Codex on 2026-06-12. Every
eligible ChatGPT plan (Go, Plus, Pro, Business) was granted one free reset,
plus more through the referral program. The "spend it now" button lives in
the desktop app and the VS Code / Cursor / Windsurf extension; the Rust CLI
doesn't expose it yet, and the extension's prompt doesn't always appear on
Linux either (see the OpenAI community thread linked in the README).

This script talks to the same undocumented endpoint the extension uses,
authenticating with the token `codex login` already stored in ~/.codex/auth.json.
It doesn't bypass any limit — it just lets you spend a credit OpenAI granted
you.

Endpoints (base: https://chatgpt.com/backend-api):
  GET  /wham/rate-limit-reset-credits           — list your credits
  POST /wham/rate-limit-reset-credits/consume   — redeem one
  GET  /wham/usage                              — current rate-limit windows
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

DEFAULT_BASE = "https://chatgpt.com/backend-api"
USER_AGENT = "codex-reset/0.1 (+https://github.com/aaamosh/codex-reset)"


# ─── auth ──────────────────────────────────────────────────────────────────

def default_auth_path() -> Path:
    home = os.environ.get("CODEX_HOME")
    base = Path(home) if home else Path.home() / ".codex"
    return base / "auth.json"


def load_auth(path: Path) -> tuple[str, str]:
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        die(f"auth file not found: {path}\nrun `codex login` first, or pass --auth")
    except json.JSONDecodeError as e:
        die(f"auth file is not valid JSON: {path}: {e}")
    token = data.get("access_token") or (data.get("tokens") or {}).get("access_token")
    account_id = data.get("account_id") or (data.get("tokens") or {}).get("account_id")
    if not token or not account_id:
        die(f"auth file is missing access_token / account_id: {path}")
    return token, account_id


# ─── http ──────────────────────────────────────────────────────────────────

def request(
    method: str,
    url: str,
    *,
    token: str,
    account_id: str,
    body: dict | None = None,
    timeout: float = 30.0,
) -> tuple[int, dict | str]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, method=method, data=data)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("ChatGPT-Account-Id", account_id)
    req.add_header("User-Agent", USER_AGENT)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode()
            return r.status, parse_json(raw)
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        return e.code, parse_json(raw)
    except urllib.error.URLError as e:
        die(f"network error talking to {url}: {e.reason}")


def parse_json(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


# ─── api wrappers ──────────────────────────────────────────────────────────

def list_credits(base: str, token: str, account_id: str) -> dict:
    status, body = request("GET", f"{base}/wham/rate-limit-reset-credits",
                           token=token, account_id=account_id)
    if status != 200:
        die_api("listing credits", status, body)
    return body  # {credits:[...], available_count:N}


def get_usage(base: str, token: str, account_id: str) -> dict:
    status, body = request("GET", f"{base}/wham/usage",
                           token=token, account_id=account_id)
    if status != 200:
        die_api("fetching usage", status, body)
    return body


def consume_credit(base: str, token: str, account_id: str,
                   credit_id: str, redeem_request_id: str) -> dict:
    status, body = request(
        "POST", f"{base}/wham/rate-limit-reset-credits/consume",
        token=token, account_id=account_id,
        body={"credit_id": credit_id, "redeem_request_id": redeem_request_id},
    )
    if status != 200:
        die_api("consuming credit", status, body)
    return body


# ─── output helpers ────────────────────────────────────────────────────────

def fmt_window(w: dict | None) -> str:
    if not w:
        return "n/a"
    used = w.get("used_percent")
    window_s = w.get("limit_window_seconds")
    reset_s = w.get("reset_after_seconds")
    parts = [f"{used}% used" if used is not None else "?%"]
    if window_s:
        parts.append(f"window={human_secs(window_s)}")
    if reset_s is not None:
        parts.append(f"resets in {human_secs(reset_s)}")
    return ", ".join(parts)


def human_secs(s: int) -> str:
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    if s < 86400:
        return f"{s / 3600:.1f}h"
    return f"{s / 86400:.1f}d"


def print_credits(payload: dict) -> None:
    credits = payload.get("credits") or []
    count = payload.get("available_count", 0)
    print(f"banked credits: {count} available")
    for c in credits:
        flag = "●" if c.get("status") == "available" else "○"
        print(f"  {flag} {c.get('id')}  status={c.get('status')}  "
              f"granted={c.get('granted_at')}  expires={c.get('expires_at')}")
        if c.get("title"):
            print(f"      «{c.get('title')}»")


def print_usage(payload: dict) -> None:
    rl = payload.get("rate_limit") or {}
    print(f"  primary  : {fmt_window(rl.get('primary_window'))}")
    print(f"  secondary: {fmt_window(rl.get('secondary_window'))}")
    extra = payload.get("additional_rate_limits") or []
    for entry in extra:
        name = entry.get("name") or entry.get("id") or "additional"
        rl2 = entry.get("rate_limit") or {}
        print(f"  {name}: primary={fmt_window(rl2.get('primary_window'))}  "
              f"secondary={fmt_window(rl2.get('secondary_window'))}")


# ─── errors ────────────────────────────────────────────────────────────────

def die(msg: str, code: int = 1) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def die_api(action: str, status: int, body: Any) -> None:
    pretty = body if isinstance(body, str) else json.dumps(body, indent=2)
    die(f"{action} failed (HTTP {status})\n{pretty}", code=2)


# ─── commands ──────────────────────────────────────────────────────────────

def cmd_status(args, base: str, token: str, account_id: str) -> int:
    credits = list_credits(base, token, account_id)
    if args.json:
        usage = get_usage(base, token, account_id)
        print(json.dumps({"credits": credits, "usage": usage}, indent=2))
        return 0
    print_credits(credits)
    print("\ncurrent usage:")
    print_usage(get_usage(base, token, account_id))
    if credits.get("available_count", 0) > 0:
        print("\nrun `codex-reset consume` to redeem one credit now.")
    return 0


def cmd_consume(args, base: str, token: str, account_id: str) -> int:
    credits = list_credits(base, token, account_id)
    available = [c for c in (credits.get("credits") or [])
                 if c.get("status") == "available"]
    if not available:
        print("no available credits to redeem.")
        return 0

    target = None
    if args.credit_id:
        target = next((c for c in available if c["id"] == args.credit_id), None)
        if target is None:
            die(f"credit_id not found among available credits: {args.credit_id}")
    else:
        target = available[0]

    print("about to redeem:")
    print(f"  credit_id : {target['id']}")
    print(f"  reset_type: {target.get('reset_type')}")
    print(f"  granted_at: {target.get('granted_at')}")
    print(f"  expires_at: {target.get('expires_at')}")

    if not args.yes:
        try:
            ans = input("proceed? [y/N] ").strip().lower()
        except EOFError:
            ans = ""
        if ans not in ("y", "yes"):
            print("aborted.")
            return 1

    if args.dry_run:
        print("\n--dry-run: skipping POST.")
        return 0

    rid = str(uuid.uuid4())
    result = consume_credit(base, token, account_id, target["id"], rid)
    print(f"\nconsumed. windows_reset={result.get('windows_reset')}, "
          f"code={result.get('code')}, "
          f"redeemed_at={(result.get('credit') or {}).get('redeemed_at')}")
    print("\nnew usage:")
    print_usage(get_usage(base, token, account_id))
    return 0


# ─── main ──────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="codex-reset",
        description="Redeem your Codex banked rate-limit reset.",
    )
    p.add_argument("--auth", type=Path, default=None,
                   help="path to auth.json (default: $CODEX_HOME/auth.json or "
                        "~/.codex/auth.json)")
    p.add_argument("--base", default=DEFAULT_BASE,
                   help=f"backend base URL (default: {DEFAULT_BASE})")
    sub = p.add_subparsers(dest="command")

    s = sub.add_parser("status", help="show available credits and current usage "
                                       "(default)")
    s.add_argument("--json", action="store_true",
                   help="machine-readable JSON output")

    c = sub.add_parser("consume", help="redeem one banked credit")
    c.add_argument("--credit-id", help="specific credit_id to redeem "
                                       "(default: first available)")
    c.add_argument("-y", "--yes", action="store_true",
                   help="skip confirmation prompt")
    c.add_argument("--dry-run", action="store_true",
                   help="show what would be redeemed without calling consume")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    auth_path = args.auth or default_auth_path()
    token, account_id = load_auth(auth_path)

    if args.command in (None, "status"):
        if args.command is None:
            args.json = False  # status default
        return cmd_status(args, args.base, token, account_id)
    if args.command == "consume":
        return cmd_consume(args, args.base, token, account_id)
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
