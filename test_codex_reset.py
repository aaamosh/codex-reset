#!/usr/bin/env python3

from __future__ import annotations

import contextlib
import io
import json
import types
import unittest
from unittest import mock

import codex_reset


def args(**overrides):
    base = {
        "json": True,
        "referral_key": codex_reset.DEFAULT_REFERRAL_KEY,
        "cookie_header": None,
        "cookie_file": None,
        "cookie_user_agent": None,
    }
    base.update(overrides)
    return types.SimpleNamespace(**base)


class InviteStatusTests(unittest.TestCase):
    def test_invite_status_without_cookie_skips_eligibility(self):
        usage = {
            "plan_type": "prolite",
            "rate_limit_reset_credits": {"available_count": 0},
            "referral_beacon": None,
        }
        out = io.StringIO()
        with mock.patch.object(codex_reset, "get_usage", return_value=usage):
            with mock.patch.object(codex_reset, "get_invite_eligibility") as elig:
                with contextlib.redirect_stdout(out):
                    code = codex_reset.cmd_invite_status(
                        args(), "https://chatgpt.com/backend-api",
                        "token", "account")
        self.assertEqual(code, 0)
        elig.assert_not_called()
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["usage"]["plan_type"], "prolite")
        self.assertEqual(
            payload["usage"]["rate_limit_reset_credits"]["available_count"], 0)
        self.assertFalse(payload["eligibility"]["checked"])

    def test_invite_status_with_cookie_reports_eligibility_null_as_unknown(self):
        usage = {
            "plan_type": "prolite",
            "rate_limit_reset_credits": {"available_count": 0},
            "referral_beacon": None,
        }
        eligibility = {
            "grant_action": "rate_limit_reset_credit",
            "grant_amount": 1,
            "remaining_referrals": None,
            "should_show": True,
        }
        out = io.StringIO()
        with mock.patch.object(codex_reset, "get_usage", return_value=usage):
            with mock.patch.object(
                codex_reset, "get_invite_eligibility",
                return_value=(200, eligibility),
            ) as elig:
                with contextlib.redirect_stdout(out):
                    code = codex_reset.cmd_invite_status(
                        args(json=False, cookie_header="__Secure-next=abc"),
                        "https://chatgpt.com/backend-api", "token", "account")
        self.assertEqual(code, 0)
        elig.assert_called_once_with(
            "https://chatgpt.com/backend-api", "token", "account",
            codex_reset.DEFAULT_REFERRAL_KEY, "__Secure-next=abc", None)
        text = out.getvalue()
        self.assertIn("eligibility: HTTP 200", text)
        self.assertIn("remaining_referrals: unknown", text)
        self.assertNotIn("remaining_referrals: 0", text)

    def test_get_invite_eligibility_is_get_with_cookie_header(self):
        with mock.patch.object(
            codex_reset, "request", return_value=(200, {})
        ) as request:
            status, body = codex_reset.get_invite_eligibility(
                "https://chatgpt.com/backend-api",
                "token",
                "account",
                "codex referral/key",
                "__Secure-next=abc",
                "Mozilla/5.0",
            )
        self.assertEqual((status, body), (200, {}))
        request.assert_called_once()
        method, url = request.call_args.args
        self.assertEqual(method, "GET")
        self.assertIn("/referrals/invite/eligibility?", url)
        self.assertIn("referral_key=codex+referral%2Fkey", url)
        self.assertEqual(
            request.call_args.kwargs["extra_headers"],
            {"Cookie": "__Secure-next=abc", "User-Agent": "Mozilla/5.0"},
        )

    def test_invite_status_summarizes_non_json_eligibility_body(self):
        payload = codex_reset.invite_status_payload(
            {"rate_limit_reset_credits": {}},
            eligibility_status=403,
            eligibility_body="<html>" + ("challenge " * 100) + "</html>",
        )
        body = payload["eligibility"]["body"]
        self.assertTrue(body["non_json"])
        self.assertGreater(body["length"], 240)
        self.assertLessEqual(len(body["preview"]), 240)
        self.assertNotIn("challenge " * 50, json.dumps(payload))

    def test_die_api_summarizes_non_json_error(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as raised:
                codex_reset.die_api(
                    "fetching usage", 403,
                    "<html>" + ("challenge " * 100) + "</html>",
                )
        self.assertEqual(raised.exception.code, 2)
        text = err.getvalue()
        self.assertIn("non-JSON response", text)
        self.assertIn("preview:", text)
        self.assertNotIn("challenge " * 50, text)

    def test_print_invite_status_shows_non_json_eligibility_summary(self):
        payload = codex_reset.invite_status_payload(
            {"rate_limit_reset_credits": {}},
            eligibility_status=403,
            eligibility_body="<html>challenge</html>",
        )
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            codex_reset.print_invite_status(payload)
        text = out.getvalue()
        self.assertIn("eligibility: HTTP 403", text)
        self.assertIn("body: non-JSON response", text)
        self.assertIn("preview: <html>challenge</html>", text)


if __name__ == "__main__":
    unittest.main()
