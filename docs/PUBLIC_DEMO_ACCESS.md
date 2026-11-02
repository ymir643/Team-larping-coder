# Echo Web public demo preparation

## What the opt-in mode protects

Set `ECHO_PUBLIC_DEMO_MODE=1` before starting the FastAPI process that will sit
behind a public HTTPS tunnel. The default is off. In public mode, the app uses
an allowlist: the website and its five static assets, Echo's command endpoint,
and read-only non-draft event list/details. Host login, host detail views,
registration, student personal data, writes, documentation, and other routes
return 404. Draft activities are filtered even if a caller requests them.

Echo requests remain same-origin. The FreeLLMAPI key stays in the backend
process, never in HTML or JavaScript. Sessions are random browser-local IDs,
isolated in the process, and expire after 15 minutes. Public mode limits each
session to 5 Echo requests per minute and the app's observed client address to
30 per minute. Behind a local tunnel these client limits may aggregate visitors.
Requests remain bounded to 8 KB and 1,000 transcript characters.

The homepage uses a small generated topography SVG; the provided campus image
is converted to `assets/campus-bh.webp` for mobile loading. This background is
visual only and carries a visible note that the site is not an official BITS
Pilani website.

This is a demo guard, not a production authentication system. Only run one
worker unless session/rate state is moved to a shared service. Review any event
data before showing it publicly. The existing page contains contact details and
the repository has pre-existing host credentials; public mode blocks the host
API, but a full deployment security review is still required.

## Local check

Keep the origin bound to loopback and use an in-memory database for testing.
Run the saved-key runner with the optional flag to test the public allowlist
without starting any tunnel:

```powershell
F:\Temp\team-larper-venv\Scripts\python.exe F:\Temp\run_echo_web_live_test.py --public-demo
```

The current local development server is intentionally bound to
`127.0.0.1:8000`. On the inspected Windows network, Wi-Fi was categorized as
Public and the current PowerShell session was not elevated. No LAN listener,
firewall rule, or HTTPS certificate was created. Do not use a LAN address until
the trusted Wi-Fi is set to Private and a narrowly scoped inbound rule is
reviewed; plain HTTP on a LAN address does not enable browser microphone access.

With the mode enabled, verify `/website/` and `/api/echo/command` work and that
`/api/host/login`, `/api/students/...`, `/api/activities/1/register`,
`/api/activities/1?view=host`, `/docs`, and write routes return 404. Stop the
server with Ctrl+C after the check.

## Public HTTPS, only after owner approval

Do not start a tunnel until the event data is approved and the public-mode
checks have passed. Stop the current server with Ctrl+C, then start the same
DPAPI-backed runner with `--public-demo` so the credential is loaded in memory
and the allowlist is active:

```powershell
F:\Temp\team-larper-venv\Scripts\python.exe F:\Temp\run_echo_web_live_test.py --public-demo
```

For a one-off hackathon demo, Cloudflare Quick Tunnels can
publish a temporary HTTPS URL to a local service. Install `cloudflared` only
after approval, then:

1. Start the app with `ECHO_PUBLIC_DEMO_MODE=1`, the approved database/config,
   the saved server-side FreeLLMAPI credential, and `--host 127.0.0.1`.
2. In a second PowerShell window, run:

   ```powershell
   cloudflared tunnel --url http://127.0.0.1:8000
   ```

3. Copy the generated `https://…trycloudflare.com/website/` address and test
   it on a phone. The HTTPS URL provides a secure browser context for microphone
   access; actual browser speech-recognition support and permission still vary.
4. Stop the tunnel with Ctrl+C when the demo ends. Do not install it as a
   persistent Windows service for this temporary demonstration.

After the approved HTTPS page opens in desktop Chrome, create its QR code from
**More → Cast, save and share → Create QR code → Download**. Scan the downloaded
code with the phone camera and confirm it opens the same HTTPS `/website/` URL.
See [Chrome's QR sharing instructions](https://support.google.com/chrome/answer/10051760?co=GENIE.Platform%3DDesktop&hl=en-GB).

The tunnel makes the website public. It must never point at FreeLLMAPI port
31415, and the backend must continue to bind only to loopback. Do not publish
or print tunnel tokens. Do not expose the app until the security gates above
have been verified and the owner has approved public access.
