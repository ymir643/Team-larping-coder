# Admin authentication

The Admin tile only opens the sign-in form. It does not authorize a visitor. The backend validates the username and a salted PBKDF2-SHA256 password verifier, then issues a random eight-hour `HttpOnly`, `SameSite=Strict`, `Secure` session cookie. The cookie is not returned in JSON. Logout revokes the server-side session. Admin-only endpoints reject missing or expired sessions, regardless of frontend role state.

There are no default admin accounts. Existing demo passwords have been removed and are no longer accepted by this source. No administrator can sign in until a new credential is configured.

## Set or rotate credentials on the Windows host

From PowerShell, run:

```powershell
Set-Location 'F:\Downloads\Team-larper-coder'
& '.\scripts\set-admin-credentials.ps1'
```

The script asks for a new username and asks for the password twice using hidden prompts. Use a unique password of at least 14 characters. The script writes only the username and PBKDF2 verifier to `%LOCALAPPDATA%\EchoWeb\admin.env`; the plaintext password is not saved. The file ACL is restricted to the current Windows account and Local System. The backend reads this file at startup. Restart the backend after setting or rotating credentials.

The application can instead read `ECHO_ADMIN_USERNAME` and `ECHO_ADMIN_PASSWORD_HASH` from its process environment, or a different verifier-file path from `ECHO_ADMIN_CREDENTIALS_FILE`. Do not set `ECHO_ADMIN_PASSWORD` and do not put secrets in HTML, JavaScript, command-line arguments, source control, or logs. The verifier format is `pbkdf2_sha256$rounds$salt_hex$digest_hex`.

## Local HTTP testing

The session cookie is Secure by default and should remain Secure behind the Cloudflare HTTPS tunnel. For isolated localhost-only tests over plain HTTP, set `ECHO_ADMIN_COOKIE_SECURE=0` only in that test process, then restore/unset it before any public service start. Never disable Secure for the public tunnel.

## Public-service rollout

These source changes do not update a currently running process or a deployed copy by themselves. Do not expose the tunnel to visitors until the updated backend has been started and checked. Verify that unauthenticated requests to `/api/programs`, `/api/activities?status=Draft`, `/api/activities/1?view=host`, and every admin write endpoint return `401`; verify that a valid new login sets an HttpOnly, Secure, SameSite cookie. No code was deployed by this change.
