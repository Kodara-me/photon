# Installs the latest Photon release as a Windows service:
#
#   irm https://github.com/jstmichel/photon/releases/latest/download/get-photon.ps1 | iex
#
# To pass options, use the scriptblock form:
#
#   & ([scriptblock]::Create((irm https://github.com/jstmichel/photon/releases/latest/download/get-photon.ps1))) -DryRun
#
# Usage: get-photon.ps1 [-Version <tag>] [-Yes] [-DryRun] [-Help]
#
#   -Version <tag>  install this release (for example v0.2.0) instead of the latest
#   -Yes            answer yes to the question that installs the service (not the PawnIO one)
#   -DryRun         download and check, then print the elevated command without running it
#   -Help           print this usage
#
# Run it from a standard (not elevated) PowerShell: each step that needs administrator rights
# is started through its own User Account Control prompt.
#
# Exit codes: 0 installed, already installed, dry run that passed or -Help; 1 failure or
# refusal. Run from a file, the code is the process exit code; run through `iex` or the
# scriptblock form, it is $LASTEXITCODE once the script has returned, and the session stays
# open.
#
# Works in Windows PowerShell 5.1 and PowerShell 7.

param(
    [string]$Version,
    [switch]$Yes,
    [switch]$DryRun,
    [switch]$Help
)

# --- Pinned PawnIO installer (R14). Bumping PawnIO is a change to this script, released with
# --- Photon: take the version and the URL from the release page
# --- https://github.com/namazso/PawnIO.Setup/releases (linked from https://pawnio.eu), download
# --- the installer only to read its SHA-256 (`certutil -hashfile PawnIO_setup.exe SHA256`) and
# --- its signature (`Get-AuthenticodeSignature`: Status Valid, SignerCertificate.Subject and
# --- .Thumbprint), never to run it, and update the five values together.
$PawnIOVersion = '2.2.0'
$PawnIOUrl = 'https://github.com/namazso/PawnIO.Setup/releases/download/2.2.0/PawnIO_setup.exe'
$PawnIOSha256 = '1f519a22e47187f70a1379a48ca604981c4fcf694f4e65b734aaa74a9fba3032'
$PawnIOSignerSubject = 'E=admin@namazso.eu, CN=namazso.eu, O=namazso, L=Debrecen, C=HU'
$PawnIOSignerThumbprint = 'F380DCC9F706E2756A5047B832FFE719E1BC35F5'

# --- Small steps: the tests replace these functions, so nothing below needs the network,
# --- an elevation prompt or a real process.

function Write-Say {
    param([string]$Message)
    Write-Host $Message
}

function Write-Fail {
    param([string]$Message)
    Write-Host "error: $Message" -ForegroundColor Red
}

function Show-Usage {
    Write-Host @'
Usage: get-photon.ps1 [-Version <tag>] [-Yes] [-DryRun] [-Help]

  -Version <tag>  install this release (for example v0.2.0) instead of the latest
  -Yes            answer yes to the question that installs the service (never the PawnIO one)
  -DryRun         download and check, then print the elevated command without running it
  -Help           print this usage

Run it from a standard (not elevated) PowerShell; each step that needs administrator rights
is started through its own User Account Control prompt. When User Account Control is turned
off, follow "By hand" in the README instead.

When PawnIO (the driver the RAM needs) is missing, it asks on the console whether to install it
from its official installer, pinned in this script and verified (SHA-256 and signature) before
it runs; -Yes does not answer that question, and without a console the offer is skipped.

Exit codes: 0 installed, already installed, dry run that passed or -Help; 1 failure or refusal.
'@
}

function Get-ReleasesUrl {
    if ($env:PHOTON_RELEASES_URL) { return $env:PHOTON_RELEASES_URL.TrimEnd('/') }
    return 'https://github.com/jstmichel/photon/releases'
}

# Not-Windows and not-x64 machines, and a 32-bit PowerShell on Windows x64, are refused.
# Returns the reason, or $null when the machine is fine.
function Test-WindowsPlatform {
    return ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT)
}

function Get-OSArchitecture {
    try {
        return [string][System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture
    } catch {
        return $(if ([Environment]::Is64BitOperatingSystem) { 'X64' } else { 'X86' })
    }
}

function Test-64BitProcess {
    return [Environment]::Is64BitProcess
}

function Get-PlatformProblem {
    if (-not (Test-WindowsPlatform)) {
        return 'this installer is for Windows; on Linux use get-photon.sh'
    }
    $architecture = Get-OSArchitecture
    if ($architecture -ne 'X64') {
        return "Photon's Windows executable is built for x64, not $architecture"
    }
    if (-not (Test-64BitProcess)) {
        return 'this is a 32-bit PowerShell; run the 64-bit Windows PowerShell (not "Windows PowerShell (x86)")'
    }
    return $null
}

function Test-Elevated {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# The 64-bit Program Files folder as the shell resolves it, never from the environment.
function Get-ProgramFilesFolder {
    return [Environment]::GetFolderPath('ProgramFiles')
}

function Test-Interactive {
    return ([Environment]::UserInteractive -and -not [Console]::IsInputRedirected)
}

# Returns $true for yes.
function Read-Answer {
    param([string]$Question)
    $answer = Read-Host "$Question [y/N]"
    return ($answer -match '^\s*(y|yes|o|oui)\s*$')
}

function Invoke-Download {
    param([string]$Url, [string]$Path)
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    } catch { }
    $client = New-Object System.Net.WebClient
    try {
        $client.DownloadFile($Url, $Path)
    } finally {
        $client.Dispose()
    }
}

# Opens a downloaded file so that other processes can still read and run it but none can
# write, rename or delete it. The caller keeps the handle open until the elevated process
# has started (R23), and checks the file only after this call.
function Open-HeldFile {
    param([string]$Path)
    return [System.IO.File]::Open($Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::Read)
}

# Hashes with .NET on a FileShare.Read stream rather than Get-FileHash: it works with the handle
# held open for R23 and does not depend on module autoloading.
function Get-FileSha256 {
    param([string]$Path)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $stream = [System.IO.File]::Open($Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::Read)
    try {
        return ([BitConverter]::ToString($sha.ComputeHash($stream)) -replace '-', '').ToLowerInvariant()
    } finally {
        $stream.Dispose()
        $sha.Dispose()
    }
}

# Runs an executable on the console and returns its exit code.
function Invoke-PhotonExe {
    param([string]$Path, [string[]]$Arguments)
    $ErrorActionPreference = 'Continue'
    & $Path @Arguments | Out-Host
    return $LASTEXITCODE
}

# Reads "photon <version>" from `photon.exe --version`; $null when there is none.
function Get-InstalledVersion {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    $ErrorActionPreference = 'Continue'
    try {
        $output = & $Path --version 2>$null
        if ($LASTEXITCODE -eq 0 -and ("$output").Trim() -match '^photon (\S+)$') { return $Matches[1] }
    } catch { }
    return $null
}

# PawnIO is installed when PawnIOLib.dll sits in the PawnIO folder of the 64-bit Program Files
# folder, the one folder `photon.exe service check` searches (R11).
function Test-PawnIOInstalled {
    param([string]$ProgramFiles)
    return (Test-Path -LiteralPath (Join-Path $ProgramFiles 'PawnIO\PawnIOLib.dll') -PathType Leaf)
}

# Status, signer certificate subject and thumbprint of a file's Authenticode signature.
function Get-InstallerSignature {
    param([string]$Path)
    $signature = Get-AuthenticodeSignature -LiteralPath $Path
    $certificate = $signature.SignerCertificate
    return [pscustomobject]@{
        Status     = [string]$signature.Status
        Subject    = $(if ($certificate) { $certificate.Subject } else { '' })
        Thumbprint = $(if ($certificate) { $certificate.Thumbprint } else { '' })
    }
}

# Starts a process through a UAC prompt, waits for it and returns its exit code; $null when
# the prompt was cancelled or the process could not start.
function Start-ElevatedProcess {
    param([string]$Path, [string[]]$Arguments)
    try {
        # Start-Process rejects an empty -ArgumentList: PawnIO's installer takes no argument.
        if ($Arguments -and $Arguments.Count -gt 0) {
            $process = Start-Process -FilePath $Path -ArgumentList $Arguments -Verb RunAs -Wait -PassThru
        } else {
            $process = Start-Process -FilePath $Path -Verb RunAs -Wait -PassThru
        }
        return $process.ExitCode
    } catch {
        return $null
    }
}

# The PawnIO step (R11-R18). Returns $true to go on, $false to stop the run with code 1 (a failed
# verification of the installer, R14). A declined, skipped, cancelled or failed install goes on.
function Invoke-PawnIOStep {
    param([string]$ProgramFiles, [string]$Work, [switch]$DryRun)
    if (Test-PawnIOInstalled $ProgramFiles) { return $true }

    if ($DryRun) {
        Write-Say "PawnIO is not installed. Would offer to install PawnIO $PawnIOVersion from $PawnIOUrl (a kernel driver needed only for the RAM)."
        return $true
    }
    if (-not (Test-Interactive)) {
        Write-Say 'PawnIO is not installed and there is no console to ask on: skipping it, the RAM stays disabled. Install it yourself from https://pawnio.eu.'
        return $true
    }
    $question = "PawnIO is not installed. Install PawnIO $PawnIOVersion (download: $PawnIOUrl)? It is a signed kernel driver, needed only for the RAM."
    # -Yes does not answer this question.
    if (-not (Read-Answer $question)) {
        Write-Say 'PawnIO was not installed: the RAM stays disabled. Photon works with every other device.'
        return $true
    }

    $installer = Join-Path $Work 'PawnIO_setup.exe'
    Write-Say "Downloading PawnIO $PawnIOVersion..."
    try {
        Invoke-Download $PawnIOUrl $installer
    } catch {
        Write-Say "Cannot download ${PawnIOUrl}: the RAM stays disabled. Install PawnIO yourself from https://pawnio.eu."
        return $true
    }

    # Held from before the checks until the elevated process has started (R23).
    $held = Open-HeldFile $installer
    $failure = $null
    $code = $null
    try {
        if ((Get-FileSha256 $installer) -ne $PawnIOSha256) {
            $failure = "the downloaded PawnIO installer does not match the pinned SHA-256"
        } else {
            $signature = Get-InstallerSignature $installer
            if ($signature.Status -ne 'Valid') {
                $failure = "the downloaded PawnIO installer has no valid Authenticode signature (status $($signature.Status))"
            } elseif ($signature.Subject -cne $PawnIOSignerSubject) {
                $failure = "the PawnIO installer is signed by '$($signature.Subject)', not by the pinned signer subject"
            } elseif ($signature.Thumbprint -ne $PawnIOSignerThumbprint) {
                $failure = "the PawnIO installer's signer certificate thumbprint $($signature.Thumbprint) is not the pinned one"
            }
        }
        if (-not $failure) {
            Write-Say 'PawnIO installer verified (SHA-256 and signature). Its own interface opens after a User Account Control prompt...'
            $code = Start-ElevatedProcess $installer @()
        }
    } finally {
        $held.Dispose()
    }
    if ($failure) {
        Remove-Item -LiteralPath $installer -Force -ErrorAction SilentlyContinue
        Write-Fail "${failure}; it was not run and nothing was installed"
        return $false
    }
    if ($null -eq $code) {
        Write-Say 'The PawnIO installation was cancelled: the RAM stays disabled.'
    } elseif ($code -ne 0) {
        Write-Say "The PawnIO installer exited with code ${code}: the RAM stays disabled."
    } else {
        Write-Say 'PawnIO installer finished.'
    }
    return $true
}

# --- Main flow: returns 0 or 1 and never calls `exit`.

function Invoke-PhotonInstall {
    param(
        [string]$Version,
        [switch]$Yes,
        [switch]$DryRun,
        [switch]$Help
    )
    $ErrorActionPreference = 'Stop'
    $work = $null
    $held = @()
    try {
        if ($Help) {
            Show-Usage
            return 0
        }
        $problem = Get-PlatformProblem
        if ($problem) {
            Write-Fail $problem
            return 1
        }
        if (Test-Elevated) {
            Write-Fail ('this PowerShell is elevated; run the installer from a standard prompt, it asks for administrator rights ' +
                'only for the steps that need them. If User Account Control is turned off, follow "By hand" in the README.')
            return 1
        }

        $programFiles = Get-ProgramFilesFolder
        $installedExe = Join-Path $programFiles 'Photon\photon.exe'

        $workParent = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { [IO.Path]::GetTempPath() }
        $work = Join-Path $workParent ('photon-install.' + [guid]::NewGuid().ToString('N').Substring(0, 8))
        New-Item -ItemType Directory -Path $work -Force | Out-Null

        $releases = Get-ReleasesUrl
        $base = if ($Version) { "$releases/download/$Version" } else { "$releases/latest/download" }
        $label = if ($Version) { $Version } else { 'the latest release' }

        Write-Say "Looking for $label..."
        $sums = Join-Path $work 'SHA256SUMS'
        try {
            Invoke-Download "$base/SHA256SUMS" $sums
        } catch {
            Write-Fail "cannot download $base/SHA256SUMS"
            return 1
        }
        $lines = @(Get-Content -LiteralPath $sums)
        $releaseVersion = $null
        $exeHash = $null
        foreach ($line in $lines) {
            if (-not $releaseVersion -and $line -match '^[0-9a-fA-F]{64}  photon-(.+)\.tar\.gz\s*$') { $releaseVersion = $Matches[1] }
            if (-not $exeHash -and $line -match '^([0-9a-fA-F]{64})  photon\.exe\s*$') { $exeHash = $Matches[1].ToLowerInvariant() }
        }
        if (-not $releaseVersion) {
            Write-Fail "the release's SHA256SUMS names no version"
            return 1
        }
        if (-not $exeHash) {
            Write-Fail "the release lists no photon.exe"
            return 1
        }

        $installed = Get-InstalledVersion $installedExe
        if ($installed -and $installed -eq $releaseVersion) {
            Write-Say "Photon $releaseVersion is already installed."
            $checkCode = Invoke-PhotonExe $installedExe @('service', 'check')
            if ($checkCode -ne 0) {
                Write-Fail 'the dependencies above are missing; nothing was changed'
                return 1
            }
            if (-not (Invoke-PawnIOStep -ProgramFiles $programFiles -Work $work -DryRun:$DryRun)) { return 1 }
            return 0
        }

        Write-Say "Downloading Photon $releaseVersion..."
        $exe = Join-Path $work 'photon.exe'
        try {
            Invoke-Download "$base/photon.exe" $exe
        } catch {
            Write-Fail "cannot download $base/photon.exe"
            return 1
        }
        # Held from before the check until the elevated process has started (R23).
        $held += Open-HeldFile $exe
        if ((Get-FileSha256 $exe) -ne $exeHash) {
            Write-Fail "photon.exe does not match the release's SHA256SUMS; nothing was installed"
            return 1
        }
        Write-Say 'Checksum verified.'

        $checkCode = Invoke-PhotonExe $exe @('service', 'check')
        if ($checkCode -ne 0) {
            Write-Fail 'the dependencies above are missing; nothing was installed'
            return 1
        }

        if (-not (Invoke-PawnIOStep -ProgramFiles $programFiles -Work $work -DryRun:$DryRun)) { return 1 }

        if ($installed) {
            $question = "Upgrade Photon ${installed} to ${releaseVersion}?"
        } else {
            $question = "Install Photon $releaseVersion as a Windows service?"
        }

        if ($DryRun) {
            Write-Say "  would run (elevated): $exe service install"
            Write-Say 'Dry run: nothing was installed.'
            return 0
        }

        if (-not $Yes) {
            if (-not (Test-Interactive)) {
                Write-Fail "$question Run again with -Yes to answer yes."
                return 1
            }
            if (-not (Read-Answer $question)) {
                Write-Fail 'the Photon service was not installed'
                return 1
            }
        }

        Write-Say "Installing Photon $releaseVersion (a User Account Control prompt follows)..."
        $installCode = Start-ElevatedProcess $exe @('service', 'install')
        $status = "$installedExe service status"
        $log = Join-Path ([Environment]::GetFolderPath('CommonApplicationData')) 'Photon\photon.log'
        if ($null -eq $installCode) {
            Write-Fail "the elevation was cancelled or refused; the Photon service was not installed. See '$status' and $log"
            return 1
        }
        Write-Say "service install exited with code $installCode."
        if ($installCode -ne 0) {
            Write-Fail "the Photon service was not installed. See '$status' and $log"
            return 1
        }

        Write-Say ''
        Write-Say "Photon $releaseVersion is installed and running. Stop Solaar and OpenRGB if they run."
        Write-Say 'Color: %ProgramData%\Photon\config.toml, then photon.exe service restart (elevated).'
        Write-Say "Status: $status"
        return 0
    } catch {
        Write-Fail $_.Exception.Message
        return 1
    } finally {
        foreach ($handle in $held) {
            try { $handle.Dispose() } catch { }
        }
        if ($work -and (Test-Path -LiteralPath $work)) {
            Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

# --- Ending (R10, R22). Dot-sourced from a file, the script only defines its functions.
# --- A scriptblock literal has a File only when the text was parsed from a file, which
# --- tells a file apart from `iex` and `[scriptblock]::Create`, whatever the caller is.

$ranFromFile = [bool]({}).File
if ($ranFromFile -and $MyInvocation.InvocationName -eq '.') { return }

$exitCode = Invoke-PhotonInstall -Version $Version -Yes:$Yes -DryRun:$DryRun -Help:$Help
if ($ranFromFile) {
    exit $exitCode
}
# Under `iex` and the scriptblock form `exit` would close the caller's session.
$global:LASTEXITCODE = $exitCode
