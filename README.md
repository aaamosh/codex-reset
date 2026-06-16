# codex-reset

> Spend your Codex **banked rate-limit reset** from the command line.

OpenAI [rolled out savable rate-limit resets for Codex](https://community.openai.com/t/flexible-rate-limit-resets-for-codex/1383470) on **2026-06-12**. Every eligible ChatGPT plan (Go / Plus / Pro / Business) was granted one free reset, plus more via the referral program. The "spend it now" button lives only in the desktop app and the VS Code / Cursor / Windsurf extension.

The Rust CLI (`codex`) [doesn't expose it yet](https://github.com/openai/codex/pull/5302) (only `account/rateLimits/read` was added), and the extension's reset prompt [doesn't reliably appear on Linux either](https://community.openai.com/t/flexible-rate-limit-resets-for-codex/1383470/4). If you're on a server, in WSL, or just live in a terminal, you couldn't redeem the credit you were given.

This is a tiny Python script (no dependencies) that talks to the same undocumented endpoint the extension does, using the access token `codex login` already wrote to `~/.codex/auth.json`.

```
$ codex-reset
banked credits: 1 available
  ● RateLimitResetCredit_…  status=available  granted=2026-06-12T01:33:14Z  expires=2026-07-12T01:33:14Z
      «One free rate limit reset»

current usage:
  primary  : 1% used, window=5.0h, resets in 5.0h
  secondary: 100% used, window=7.0d, resets in 3.2d

run `codex-reset consume` to redeem one credit now.

$ codex-reset consume
about to redeem:
  credit_id : RateLimitResetCredit_…
  reset_type: codex_rate_limits
  granted_at: 2026-06-12T01:33:14Z
  expires_at: 2026-07-12T01:33:14Z
proceed? [y/N] y

consumed. windows_reset=1, code=reset, redeemed_at=2026-06-13T13:12:31Z

new usage:
  primary  : 1% used, window=5.0h, resets in 5.0h
  secondary: 0% used, window=7.0d, resets in 7.0d
```

## Install

```sh
curl -fsSL https://raw.githubusercontent.com/aaamosh/codex-reset/main/codex_reset.py \
  -o ~/.local/bin/codex-reset && chmod +x ~/.local/bin/codex-reset
```

…or just clone the repo and run `python3 codex_reset.py`. There are no third-party dependencies — Python 3.9+ stdlib is enough.

## Usage

```
codex-reset                  # show available credits + current usage
codex-reset consume          # redeem one credit (asks for confirmation)
codex-reset consume --yes    # redeem without confirmation
codex-reset consume --dry-run
codex-reset --auth PATH      # use a different auth.json (e.g. CLIProxyAPI auths)
codex-reset status --json    # machine-readable output
```

The script reads `access_token` and `account_id` from `auth.json`. By default it looks at `$CODEX_HOME/auth.json`, falling back to `~/.codex/auth.json`. You can point `--auth` at any other file with the same shape — useful for proxy setups like [CLIProxyAPI](https://github.com/luispater/CLIProxyAPI) where many accounts live in one place.

## How it works

Three reset endpoints under `https://chatgpt.com/backend-api`:

| Endpoint                                            | Method | Purpose                                           |
| --------------------------------------------------- | ------ | ------------------------------------------------- |
| `/wham/rate-limit-reset-credits`                    | GET    | List your banked credits and current statuses     |
| `/wham/rate-limit-reset-credits/consume`            | POST   | Redeem one credit (body: `credit_id`, `redeem_request_id`) |
| `/wham/usage`                                       | GET    | Current rate-limit windows (used for before/after)|

Every request carries two headers:

```
Authorization: Bearer <access_token>
ChatGPT-Account-Id: <account_id>
```

Both endpoints were extracted from the official `openai.chatgpt` VS Code extension's webview bundle (`webview/assets/codex-api-*.js`). The script doesn't ship any auth — you bring your own via the file `codex login` already created.

## Referral invites

Codex reset credits and Codex referral invites are connected, but they are not
the same API surface.

The useful read-only backend signal available with normal Codex bearer auth is
already in `GET /wham/usage`:

- `rate_limit_reset_credits.available_count`: how many banked reset credits are
  currently available to spend.
- `referral_beacon`: referral-related state when OpenAI exposes it for the
  account. On accounts without a visible active referral campaign this can be
  `null`.

The current `openai.chatgpt` VS Code extension also contains an invite
eligibility query:

```text
GET /backend-api/referrals/invite/eligibility?referral_key=codex_referral_persistent_invite
```

In live testing this endpoint returned `403` when called with only the
`Authorization: Bearer <access_token>` + `ChatGPT-Account-Id` headers that work
for `/wham/usage`. It returned `200` when the same bearer-auth request also
included an authenticated ChatGPT browser `Cookie` header from the same account.
So eligibility appears to require the browser/web session cookie path in
addition to the Codex token.

A successful eligibility response can look like:

```json
{
  "grant_action": "rate_limit_reset_credit",
  "grant_amount": 1,
  "ineligible_reason": null,
  "ineligible_reason_code": null,
  "remaining_referrals": null,
  "should_show": true
}
```

The mutating invite endpoint is:

```text
POST /backend-api/wham/referrals/invite
```

with a JSON body like:

```json
{
  "referral_key": "codex_referral_persistent_invite",
  "emails": ["friend@example.com"]
}
```

Do not use the invite endpoint as a "status check": it can send real email
invites. For safe diagnostics, prefer `/wham/usage` first and treat the
eligibility endpoint as an optional web-session probe.

### Successful response example

```json
{
  "code": "reset",
  "credit": {
    "id": "RateLimitResetCredit_...",
    "reset_type": "codex_rate_limits",
    "status": "redeemed",
    "redeemed_at": "2026-06-13T13:12:31Z",
    ...
  },
  "windows_reset": 1
}
```

## Caveats

- **Undocumented and unsupported.** OpenAI could rename, gate, or remove these endpoints any day. If it stops working, that's the most likely reason — open an issue and we'll re-grep.
- **This does not bypass anything.** It only spends a credit OpenAI explicitly granted to your account. If you have `available_count: 0`, there's nothing to redeem.
- **API-key Codex users don't have this.** Savable resets are tied to ChatGPT subscriptions; pure API-key usage is billed per token with no 5-hour windows.
- **The credit is consumed even on a partial run.** If the POST returns 200, the credit is gone — same behavior as clicking the button in the app.

## License

[MIT](LICENSE) — do whatever you want, no warranty.

## Acknowledgements

- The OpenAI Codex team for the feature itself.
- The [openai/codex](https://github.com/openai/codex) repo for documenting `/wham/usage` and the rest of the auth flow.
- [Soju06/codex-lb](https://github.com/Soju06/codex-lb) and [steipete/CodexBar](https://github.com/steipete/CodexBar) for prior `/wham/*` reverse-engineering notes.
- [Anthropic](https://www.anthropic.com)'s **Claude** (Opus 4.7) wrote this in one session — reverse-engineered the endpoint out of the VS Code extension's webview bundle, built the CLI, and drafted this README — on a day the author's own Codex account was locked out behind a redeem button that only lived in a UI he couldn't reach. A friendly nod across vendors.
