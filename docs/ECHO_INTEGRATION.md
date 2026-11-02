# Echo website integration

## Existing site parts retained

- The main site remains `index.html`, `style.css`, and `script.js`.
- The backend remains FastAPI + SQLAlchemy in `main.py` with the existing SQLite `Activity` model and `/api/activities` routes.
- Echo is isolated in `echo-assistant.js` and `echo_assistant.py`; it uses the site's actual `Activity` table for search and event resolution.
- `/website/` serves the existing HTML and `/assets/*` serves the existing frontend files from the API origin. `/` remains the existing JSON API status route.

## Request and response contract

`POST /api/echo/command` accepts JSON:

```json
{"session_id":"opaque-browser-session-id","transcript":"Find Explorer events"}
```

The session ID is generated with browser cryptographic randomness and stored in the current tab's `sessionStorage`. The server keeps independent conversational turns and result IDs for 15 minutes (in process memory). No cookies or credentials are used for visitor sessions.

Successful responses use a compact envelope:

```json
{"session_id":"opaque-browser-session-id","speech_text":"I found 2 matching events.","action":{"action":"search_events","query":"Explorer","results":[{"activity_id":12,"title":"Explorer Night","category":"Astronomy","venue":"Science Hall","start_time":"2026-11-15T18:00:00","end_time":"2026-11-15T20:00:00","participation_type":"Individual","status":"Published","participant_instructions":"Bring a notebook."}],"has_more":false}}
```

Allowed server responses are `answer`, `clarify`, `unsupported`, `search_events`, `open_event`, `show_event_details`, `navigate`, `scroll`, and the local `stop_speaking` control. Navigation route names are limited to `home`, `campus`, `map`, `events`, `contacts`, `announcements`, and `progress`. Event IDs and titles are resolved only from the database. The frontend executes only these known action types; it never evaluates model output as code, SQL, a URL, or a command.

The existing generic Echo contract in the EchoPhone repository models canonical `/events/{slug}` paths. This site's actual UI is a gated single-page app and its actual event records use integer activity IDs, so that route schema cannot be imported unchanged. This integration reuses its narrow-intent, isolated-session, trusted-database-resolution approach and adapts the response to this site's real IDs and routes.

## Intent behavior

- General questions become bounded text `answer` responses.
- Event requests become parameterized SQLAlchemy queries over non-Draft activities; “upcoming” also restricts to future Published/Ongoing activities.
- Search results are stored per session. “Open the second one” resolves index 2 against that session's actual result IDs. “Show details” resolves the previously selected record.
- `show_more_events` returns the next page from the session's stored result set.
- Supported navigation: home, campus landing, map, events, contacts, announcements, and activity progress. Map opens a fixed official Google Maps search link selected in the frontend; model output cannot choose arbitrary URLs. Phone contacts discovery, calendar integration, registration, and arbitrary app/device actions are not provided by Echo and are not claimed.
- “Be quiet”, “stop talking”, “stop speaking”, and “shut up” are intercepted locally in the browser; mute/unmute is also local. No AI call is required to stop browser speech.

## AI configuration

Server-only environment variables:

- `FREELLMAPI_BASE_URL` (default `http://127.0.0.1:31415/v1`)
- `FREELLMAPI_MODEL` (default `auto`)
- `FREELLMAPI_API_KEY` (required)

The backend sends an authenticated non-streaming OpenAI-compatible `/chat/completions` request with `model`, `messages`, `stream:false`, and a Bearer key. It uses a 40-second timeout and does not log key values or raw provider errors. Plain-text conversational completions become `answer` responses; action-shaped requests still require validated structured JSON, and malformed action output cannot execute. A non-loopback HTTP AI endpoint is rejected; configure HTTPS for any remote host.

## Voice and browser support

Speech recognition uses `SpeechRecognition` or `webkitSpeechRecognition` when available and shows interim/final text. It needs a supported browser and secure context (HTTPS or localhost); otherwise use typed input. Speech output uses browser `speechSynthesis` and visitor-device voices. It is not Kokoro, not Windows TTS, and not a promise that all device/browser combinations support a voice. Microphone/audio hardware was not tested by the automated suite.

## Local development / demo readiness

Use the README's single-origin Uvicorn command on `127.0.0.1`, with the approved real database and server-side API key configured in the PowerShell session. The clone contains no production database, and the existing `seed.py` deletes rows before seeding; do not run it against valuable data. Empty tables correctly produce no event results.

No HTTPS tunnel, public host, firewall change, remote AI route, or deployment was configured. A visitor browser cannot use its own localhost to reach the developer's laptop. Before any public demo, isolate a secured HTTPS gateway and review the existing unauthenticated administrative API routes and demo host login implementation; current backend-wide exposure is not ready for public access.
