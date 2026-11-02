param(
    [switch]$Remove
)

$ErrorActionPreference = 'Stop'
$adb = 'F:\Android\Sdk\platform-tools\adb.exe'
$port = 8000

if (-not (Test-Path -LiteralPath $adb)) {
    Write-Host "ERROR: Android platform-tools were not found at $adb. Install/configure ADB before continuing." -ForegroundColor Yellow
    exit 2
}

if ($Remove) {
    & $adb reverse --remove "tcp:$port"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Write-Host 'Removed the temporary phone-to-laptop port mapping.'
    exit 0
}

if (-not (Test-NetConnection -ComputerName 127.0.0.1 -Port $port -InformationLevel Quiet)) {
    Write-Host "ERROR: Echo Web is not listening on 127.0.0.1:$port. Start the local website first." -ForegroundColor Yellow
    exit 2
}

$deviceLines = @(& $adb devices | Select-Object -Skip 1 | Where-Object { $_ -match '^\S+\s+device(?:\s|$)' })
if ($deviceLines.Count -eq 0) {
    $unauthorized = @(& $adb devices | Select-Object -Skip 1 | Where-Object { $_ -match '^\S+\s+unauthorized(?:\s|$)' })
    if ($unauthorized.Count -gt 0) {
        Write-Host 'ERROR: ADB sees an unauthorized phone. Unlock it and approve the USB debugging prompt, then run this script again.' -ForegroundColor Yellow
    } else {
        Write-Host 'ERROR: No authorized Android phone is connected. Connect by USB, enable USB debugging, approve its prompt, then run this script again. USB file transfer is not required.' -ForegroundColor Yellow
    }
    exit 3
}

if ($deviceLines.Count -ne 1) {
    Write-Host 'ERROR: More than one authorized Android device is connected. Disconnect the others and run this script again to avoid forwarding to the wrong phone.' -ForegroundColor Yellow
    exit 4
}

$serial = ($deviceLines[0] -split '\s+')[0]
& $adb -s $serial reverse "tcp:$port" "tcp:$port"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$forwarding = @(& $adb -s $serial reverse --list)
if (-not ($forwarding -match "tcp:$port\s+tcp:$port")) {
    Write-Host 'ERROR: ADB did not confirm the temporary reverse mapping.' -ForegroundColor Yellow
    exit 5
}

Write-Host 'Phone access is ready. Open this URL in Android Chrome:'
Write-Host "http://127.0.0.1:$port/website/"
Write-Host 'The website remains bound to laptop loopback. This mapping lasts only while the USB debugging session is active.'
