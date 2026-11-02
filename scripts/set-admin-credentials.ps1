[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

function ConvertFrom-HiddenInput([Security.SecureString] $Value) {
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Value)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}

$username = (Read-Host 'Choose a new admin username').Trim()
if ($username -notmatch '^[A-Za-z0-9._@-]{1,128}$') {
    throw 'Use 1–128 letters, numbers, periods, underscores, @ signs, or hyphens for the username.'
}

$passwordSecure = Read-Host 'Enter a NEW admin password (hidden; 14+ characters)' -AsSecureString
$confirmSecure = Read-Host 'Enter the new password again (hidden)' -AsSecureString
$password = ConvertFrom-HiddenInput $passwordSecure
$confirmation = ConvertFrom-HiddenInput $confirmSecure
if ($password.Length -lt 14) {
    $password = $null; $confirmation = $null
    $passwordSecure.Dispose(); $confirmSecure.Dispose()
    throw 'The new password must be at least 14 characters.'
}
if (-not [string]::Equals($password, $confirmation, [StringComparison]::Ordinal)) {
    $password = $null; $confirmation = $null
    $passwordSecure.Dispose(); $confirmSecure.Dispose()
    throw 'The passwords did not match. No credentials were saved.'
}

$directory = Join-Path $env:LOCALAPPDATA 'EchoWeb'
New-Item -ItemType Directory -Path $directory -Force | Out-Null
$credentialPath = Join-Path $directory 'admin.env'
$temporaryPath = Join-Path $directory ('admin.env.' + [guid]::NewGuid().ToString('N') + '.tmp')
$salt = New-Object byte[] 16
$rng = [Security.Cryptography.RandomNumberGenerator]::Create()
$rng.GetBytes($salt)
$kdf = [Security.Cryptography.Rfc2898DeriveBytes]::new(
    $password, $salt, 600000, [Security.Cryptography.HashAlgorithmName]::SHA256
)
try {
    $derived = $kdf.GetBytes(32)
    $saltHex = [BitConverter]::ToString($salt).Replace('-', '').ToLowerInvariant()
    $derivedHex = [BitConverter]::ToString($derived).Replace('-', '').ToLowerInvariant()
    $verifier = 'pbkdf2_sha256$600000${0}${1}' -f $saltHex, $derivedHex
    $contents = "ECHO_ADMIN_USERNAME=$username`nECHO_ADMIN_PASSWORD_HASH=$verifier`n"
    [IO.File]::WriteAllText($temporaryPath, $contents, [Text.UTF8Encoding]::new($false))

    # Restrict the verifier file to this Windows account and Local System.
    $currentSid = [Security.Principal.WindowsIdentity]::GetCurrent().User
    $systemSid = [Security.Principal.SecurityIdentifier]::new('S-1-5-18')
    $fileAcl = [Security.AccessControl.FileSecurity]::new()
    $fileAcl.SetAccessRuleProtection($true, $false)
    $fileAcl.SetOwner($currentSid)
    $fileAcl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
        $currentSid, [Security.AccessControl.FileSystemRights]::FullControl,
        [Security.AccessControl.AccessControlType]::Allow
    ))
    $fileAcl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
        $systemSid, [Security.AccessControl.FileSystemRights]::FullControl,
        [Security.AccessControl.AccessControlType]::Allow
    ))
    Set-Acl -LiteralPath $temporaryPath -AclObject $fileAcl
    Move-Item -LiteralPath $temporaryPath -Destination $credentialPath -Force
    Set-Acl -LiteralPath $credentialPath -AclObject $fileAcl
}
finally {
    $kdf.Dispose()
    $rng.Dispose()
    [Array]::Clear($salt, 0, $salt.Length)
    if ($derived) { [Array]::Clear($derived, 0, $derived.Length) }
    $password = $null
    $confirmation = $null
    $passwordSecure.Dispose()
    $confirmSecure.Dispose()
    if (Test-Path -LiteralPath $temporaryPath) { Remove-Item -LiteralPath $temporaryPath -Force }
}

Write-Host 'Admin password verifier saved. The password itself was not stored.'
Write-Host "Credential file: $credentialPath"
Write-Host 'Restart the loopIn backend before signing in.'
