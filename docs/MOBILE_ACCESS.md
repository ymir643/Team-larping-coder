# Open Echo Web on an Android phone

## Preferred: temporary USB forwarding

This keeps Echo Web bound to `127.0.0.1` on the laptop and requires no Wi-Fi
firewall rule, no public tunnel, and no certificate installation. ADB forwards
the phone's loopback port to the laptop's loopback port.

1. Start Echo Web on the laptop at `127.0.0.1:8000`.
2. Connect one Android phone by USB, enable **USB debugging**, unlock the phone,
   and approve the USB debugging prompt. USB file transfer is not required.
3. In PowerShell from the repository, run:

   ```powershell
   .\scripts\open-echo-on-phone.ps1
   ```

4. In Android Chrome, open:

   ```text
   http://127.0.0.1:8000/website/
   ```

   On the phone, `127.0.0.1` is treated as its own loopback endpoint; the ADB
   reverse mapping carries that request to the laptop. Loopback origins are
   generally considered secure contexts by browsers, allowing microphone APIs
   that require a secure context. Browser speech recognition availability and
   microphone permission still depend on Android Chrome and the phone settings.
5. Remove the temporary mapping when finished:

   ```powershell
   .\scripts\open-echo-on-phone.ps1 -Remove
   ```

The helper refuses to choose between multiple connected phones, checks that the
site is listening first, and handles missing or unauthorized ADB devices without
changing phone data or installing an app.

## Same-Wi-Fi HTTP option

The inspected laptop Wi-Fi address was `192.168.0.227`, but Windows currently
classifies that network as **Public**. Do not use that address yet. Once the
owner confirms the Wi-Fi is trusted, switch its Windows network profile to
**Private**, add a narrowly scoped firewall rule from an Administrator
PowerShell, stop the loopback server, and start the guarded LAN mode:

```powershell
New-NetFirewallRule -DisplayName "Echo Website LAN Demo" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8000 -Profile Private -RemoteAddress LocalSubnet
& "F:\Temp\team-larper-venv\Scripts\python.exe" "F:\Temp\run_echo_web_live_test.py" --lan
```

The guarded launcher refuses to bind unless Windows reports a Private network
and enables the public-demo API allowlist. It prints the actual LAN URL. Plain
HTTP on a LAN IP does not provide a secure browser origin for microphone access;
use the USB loopback method above for private voice testing. No firewall rule or
LAN listener is created automatically.

No public HTTPS tunnel is configured. Do not start one without explicit approval.
