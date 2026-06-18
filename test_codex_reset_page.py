#!/usr/bin/env python3

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
HTML = (ROOT / "codex-reset.html").read_text(encoding="utf-8")


class CodexResetPageTests(unittest.TestCase):
    def test_page_is_standalone_and_branded(self):
        self.assertIn("<!doctype html>", HTML)
        self.assertIn("<title>Codex Reset</title>", HTML)
        self.assertIn("<h1>Codex Reset</h1>", HTML)
        self.assertIn("Reset credit command builder", HTML)
        self.assertIn("Official handoff", HTML)
        self.assertFalse(re.search(r"[^\x00-\x7F]", HTML))

    def test_page_declares_no_network_or_storage_surface(self):
        self.assertIn("connect-src 'none'", HTML)
        self.assertNotRegex(HTML, r"<script\s+[^>]*src=")
        self.assertNotRegex(HTML, r"<link\s+[^>]*href=")
        self.assertNotRegex(HTML, r"<form\b")
        self.assertNotIn("fetch(", HTML)
        self.assertNotIn("XMLHttpRequest", HTML)
        self.assertNotIn("WebSocket", HTML)
        self.assertNotIn("EventSource", HTML)
        self.assertNotIn("sendBeacon", HTML)
        self.assertNotIn("localStorage", HTML)
        self.assertNotIn("sessionStorage", HTML)
        self.assertIn("does not call OpenAI endpoints", HTML)
        self.assertIn("does not read `auth.json`", HTML)

    def test_page_points_to_codex_reset_repo(self):
        self.assertIn(
            "https://github.com/aaamosh/codex-reset/raw/main/codex-reset.html",
            HTML,
        )
        self.assertIn(
            "https://github.com/aaamosh/codex-reset/blob/main/codex-reset.html",
            HTML,
        )
        self.assertNotIn("codex-invite-helper/raw", HTML)
        self.assertNotIn("codex-hud/raw", HTML)

    def test_page_generates_expected_command_surfaces(self):
        for expected in [
            "codex-reset status",
            "invite-status",
            "--cookie-file",
            "consume",
            "--dry-run",
            "--yes",
            "curl -fsSL https://raw.githubusercontent.com/aaamosh/codex-reset/main/codex_reset.py",
        ]:
            self.assertIn(expected, HTML)


if __name__ == "__main__":
    unittest.main()
