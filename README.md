# loopIn Activity Platform + Echo

This repository contains the loopIn event site (static HTML/CSS/JavaScript and a FastAPI/SQLAlchemy API) with a modular, floating Echo voice assistant. Echo can answer general questions through a server-side FreeLLMAPI connection and search/navigate the site's actual non-draft `Activity` records.

## Local setup (Windows PowerShell)

From the repository root, create/use a Python environment on a drive with free space:

```powershell
$env:TEMP = 'F:\Temp'
$env:TMP = 'F:\Temp'
New-Item -ItemType Directory -Force -Path 'F:\Temp' | Out-Null
py -3.12 -m venv F:\Temp\team-larper-venv
F:\Temp\team-larper-venv\Scripts\python.exe -m pip install -r requirements.txt
```

Configure FreeLLMAPI in the current PowerShell session. This prompts without echoing the key and does not write it to the repository or user environment registry:

```powershell
$env:FREELLMAPI_BASE_URL = 'http://127.0.0.1:31415/v1'
$env:FREELLMAPI_MODEL = 'auto'
$secureKey = Read-Host 'FreeLLMAPI API key' -AsSecureString
$keyPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
try { $env:FREELLMAPI_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($keyPtr) }
finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($keyPtr) }
```

Run the API and website from the same origin:

```powershell
F:\Temp\team-larper-venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Open [http://127.0.0.1:8000/website/](http://127.0.0.1:8000/website/). The page uses `/api/...` on that same server; it no longer depends on a hard-coded LAN IP. Echo's small orb is at the bottom right. Tap it and allow browser microphone access, or type in the compact panel. Event browsing still requires the site's existing STUDENT or VISITOR access flow.

**Database:** the app creates empty tables if `campus.db` is absent. Do not run `seed.py` against a database containing data; it deletes current rows before reseeding. No production event data was included in this integration. Use an approved copy of the team's actual database for a realistic event demo.

## Tests

```powershell
F:\Temp\team-larper-venv\Scripts\python.exe -m pip install -r requirements-dev.txt
F:\Temp\team-larper-venv\Scripts\python.exe -m unittest discover -s tests -v
```

The tests use disposable SQLite fixtures and a local fake OpenAI-compatible HTTP server. They do not call the real FreeLLMAPI, modify a production database, or verify physical microphone/speaker hardware.

## Security and mobile demo

The API key is read only by the backend from `FREELLMAPI_API_KEY`; browser JavaScript never receives it. The default AI base is loopback and non-loopback HTTP is rejected (remote AI hosts must use HTTPS). The assistant has bounded structured actions, an in-memory 15-minute session TTL, a basic per-client rate limit, and safe error responses. Speech recognition and speech synthesis run in the visitor's browser; microphone recognition availability and permission prompts depend on browser and secure-context support.

The recommended local same-origin server binds to `127.0.0.1`, so it is not exposed to the network. For phone testing, connect one Android phone by USB, approve USB debugging, and use `scripts/open-echo-on-phone.ps1`; Android Chrome then opens the forwarded `http://127.0.0.1:8000/website/` origin. This requires USB debugging but not USB file transfer, and creates no public or LAN listener. The current Wi-Fi is classified as Public, so do not use the LAN launcher until you confirm the network is trusted and change its profile to Private. No public tunnel or deployment is enabled.

See [docs/ECHO_INTEGRATION.md](docs/ECHO_INTEGRATION.md) for the action contract and limitations, and [docs/MOBILE_ACCESS.md](docs/MOBILE_ACCESS.md) for phone setup.
