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
  GET  /referrals/invite/eligibility            — optional invite eligibility probe
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

DEFAULT_BASE = "https://chatgpt.com/backend-api"
DEFAULT_REFERRAL_KEY = "codex_referral_persistent_invite"
USER_AGENT = "codex-reset/0.1 (+https://github.com/aaamosh/codex-reset)"
SAFE_BEACON_KEYS = (
    "type",
    "referral_key",
    "grant_type",
    "grant_amount",
    "referral_action",
    "referral_redemption_action",
)
SAFE_ELIGIBILITY_KEYS = (
    "should_show",
    "grant_action",
    "grant_amount",
    "remaining_referrals",
    "ineligible_reason",
    "ineligible_reason_code",
)


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
    extra_headers: dict[str, str] | None = None,
    timeout: float = 30.0,
) -> tuple[int, dict | str]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, method=method, data=data)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("ChatGPT-Account-Id", account_id)
    req.add_header("User-Agent", USER_AGENT)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    for key, value in (extra_headers or {}).items():
        req.add_header(key, value)
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


def get_invite_eligibility(
    base: str,
    token: str,
    account_id: str,
    referral_key: str,
    cookie_header: str,
    cookie_user_agent: str | None = None,
) -> tuple[int, dict | str]:
    query = urllib.parse.urlencode({"referral_key": referral_key})
    headers = {"Cookie": cookie_header}
    if cookie_user_agent:
        headers["User-Agent"] = cookie_user_agent
    return request(
        "GET", f"{base}/referrals/invite/eligibility?{query}",
        token=token, account_id=account_id,
        extra_headers=headers,
    )


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


def safe_subset(payload: dict | None, keys: tuple[str, ...]) -> dict:
    if not isinstance(payload, dict):
        return {}
    return {key: payload.get(key) for key in keys if key in payload}


def invite_status_payload(
    usage: dict,
    *,
    eligibility_status: int | None = None,
    eligibility_body: dict | str | None = None,
) -> dict:
    reset_credits = usage.get("rate_limit_reset_credits") or {}
    referral_beacon = usage.get("referral_beacon")
    payload = {
        "usage": {
            "plan_type": usage.get("plan_type"),
            "rate_limit_reset_credits": {
                "available_count": reset_credits.get("available_count"),
            },
            "referral_beacon": (
                None if referral_beacon is None
                else safe_subset(referral_beacon, SAFE_BEACON_KEYS)
            ),
        },
        "eligibility": {
            "checked": eligibility_status is not None,
        },
    }
    if eligibility_status is not None:
        payload["eligibility"]["http_status"] = eligibility_status
        payload["eligibility"]["body"] = (
            safe_subset(eligibility_body, SAFE_ELIGIBILITY_KEYS)
            if isinstance(eligibility_body, dict)
            else summarize_non_json_body(eligibility_body)
        )
    return payload


def summarize_non_json_body(body: Any, limit: int = 240) -> dict:
    text = "" if body is None else str(body)
    preview = " ".join(text[:limit].split())
    return {
        "non_json": True,
        "length": len(text),
        "preview": preview,
    }


def print_invite_status(payload: dict) -> None:
    usage = payload["usage"]
    print("referral diagnostics:")
    print(f"  plan_type: {usage.get('plan_type') or 'unknown'}")
    count = (usage.get("rate_limit_reset_credits") or {}).get("available_count")
    print(f"  banked reset credits: {fmt_unknown(count)} available")

    beacon = usage.get("referral_beacon")
    if beacon is None:
        print("  referral_beacon: none")
    elif beacon:
        print("  referral_beacon:")
        for key in SAFE_BEACON_KEYS:
            if key in beacon:
                print(f"    {key}: {fmt_unknown(beacon.get(key))}")
    else:
        print("  referral_beacon: present, but no known fields exposed")

    eligibility = payload["eligibility"]
    if not eligibility.get("checked"):
        print("\neligibility: not checked")
        print("  pass --cookie-file or --cookie-header to run the optional "
              "browser-session GET probe")
        return

    status = eligibility.get("http_status")
    body = eligibility.get("body")
    print(f"\neligibility: HTTP {status}")
    if isinstance(body, dict) and body.get("non_json"):
        print(f"  body: non-JSON response, {body.get('length', 0)} bytes")
        preview = body.get("preview")
        if preview:
            print(f"  preview: {preview}")
    elif isinstance(body, dict):
        for key in SAFE_ELIGIBILITY_KEYS:
            if key in body:
                value = body.get(key)
                if key == "remaining_referrals" and value is None:
                    value = "unknown"
                else:
                    value = fmt_unknown(value)
                print(f"  {key}: {value}")


def fmt_unknown(value: Any) -> str:
    return "unknown" if value is None else str(value)


# ─── errors ────────────────────────────────────────────────────────────────

def die(msg: str, code: int = 1) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def die_api(action: str, status: int, body: Any) -> None:
    if isinstance(body, str):
        summary = summarize_non_json_body(body)
        pretty = (
            f"non-JSON response, {summary['length']} bytes\n"
            f"preview: {summary['preview']}"
        )
    else:
        pretty = json.dumps(body, indent=2)
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


def cmd_invite_status(args, base: str, token: str, account_id: str) -> int:
    usage = get_usage(base, token, account_id)
    cookie_header = read_cookie_header(args)
    eligibility_status = None
    eligibility_body = None
    if cookie_header:
        eligibility_status, eligibility_body = get_invite_eligibility(
            base, token, account_id, args.referral_key, cookie_header,
            args.cookie_user_agent)

    payload = invite_status_payload(
        usage,
        eligibility_status=eligibility_status,
        eligibility_body=eligibility_body,
    )
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print_invite_status(payload)
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


def read_cookie_header(args) -> str | None:
    if args.cookie_header and args.cookie_file:
        die("pass only one of --cookie-header / --cookie-file")
    if args.cookie_header:
        return args.cookie_header.strip() or None
    if args.cookie_file:
        if str(args.cookie_file) == "-":
            return sys.stdin.read().strip() or None
        try:
            return args.cookie_file.read_text().strip() or None
        except FileNotFoundError:
            die(f"cookie file not found: {args.cookie_file}")
    return None


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

    i = sub.add_parser("invite-status",
                       help="show read-only referral/invite diagnostics")
    i.add_argument("--json", action="store_true",
                   help="machine-readable JSON output")
    i.add_argument("--referral-key", default=DEFAULT_REFERRAL_KEY,
                   help=f"referral key (default: {DEFAULT_REFERRAL_KEY})")
    i.add_argument("--cookie-header",
                   help="browser Cookie header for optional eligibility GET "
                        "(sensitive; prefer --cookie-file -)")
    i.add_argument("--cookie-file", type=Path,
                   help="file containing a browser Cookie header, or '-' for "
                        "stdin")
    i.add_argument("--cookie-user-agent",
                   help="User-Agent to send with --cookie-header/--cookie-file "
                        "when cookies are tied to a browser session")

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
    if args.command == "invite-status":
        return cmd_invite_status(args, args.base, token, account_id)
    if args.command == "consume":
        return cmd_consume(args, args.base, token, account_id)
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
