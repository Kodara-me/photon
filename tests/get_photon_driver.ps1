# Test driver for scripts/get-photon.ps1, run by tests/test_get_photon_ps1.py.
#
# Dot-sources the installer, replaces the functions that download, ask, read the machine or
# start an elevated process, then runs the main flow and prints "CODE=<exit code>". Nothing
# here downloads, raises a UAC prompt or installs the service. The scenario comes from the
# environment (FAKE_*).
param(
    [string]$Script,
    [string]$Root,
    [string]$Version,
    [switch]$Yes,
    [switch]$DryRun,
    [switch]$Help
)

$wanted = @{ Version = $Version; Yes = $Yes; DryRun = $DryRun; Help = $Help }
. $Script

# The pinned PawnIO values are replaced by those of the fake installer in $Root\pawnio (the real
# ones pin the real installer, which no test downloads).
$fakeInstaller = Join-Path $Root 'pawnio\PawnIO_setup.exe'
if ($env:FAKE_PAWNIO_HASH -eq 'wrong') {
    $PawnIOSha256 = 'e' * 64
} elseif (Test-Path -LiteralPath $fakeInstaller) {
    $PawnIOSha256 = Get-FileSha256 $fakeInstaller
}
$PawnIOSignerSubject = 'CN=Fake PawnIO Signer'
$PawnIOSignerThumbprint = '0123456789ABCDEF0123456789ABCDEF01234567'

$log = Join-Path $Root 'log'
function Write-Log { param([string]$Message) Add-Content -LiteralPath $log -Value $Message }

function Test-WindowsPlatform { return ($env:FAKE_WINDOWS -ne '0') }
function Get-OSArchitecture { if ($env:FAKE_ARCH) { return $env:FAKE_ARCH } else { return 'X64' } }
function Test-64BitProcess { return ($env:FAKE_32BIT -ne '1') }
function Test-Elevated { return ($env:FAKE_ELEVATED -eq '1') }
function Get-ProgramFilesFolder { return (Join-Path $Root 'pf') }
function Test-Interactive { return ($env:FAKE_INTERACTIVE -eq '1') }

function Read-Answer {
    param([string]$Question)
    Write-Log "ask: $Question"
    return ($env:FAKE_ANSWER -eq 'y')
}

function Get-InstallerSignature {
    param([string]$Path)
    Write-Log "signature: $([IO.Path]::GetFileName($Path))"
    return [pscustomobject]@{
        Status     = $(if ($env:FAKE_SIG_STATUS) { $env:FAKE_SIG_STATUS } else { 'Valid' })
        Subject    = $(if ($env:FAKE_SIG_SUBJECT) { $env:FAKE_SIG_SUBJECT } else { $PawnIOSignerSubject })
        Thumbprint = $(if ($env:FAKE_SIG_THUMBPRINT) { $env:FAKE_SIG_THUMBPRINT } else { $PawnIOSignerThumbprint })
    }
}

function Invoke-Download {
    param([string]$Url, [string]$Path)
    Write-Log "download: $Url"
    if ($Url -eq $PawnIOUrl) {
        Copy-Item -LiteralPath $fakeInstaller -Destination $Path
        return
    }
    $prefix = 'https://releases.test/'
    if (-not $Url.StartsWith($prefix)) { throw "unexpected URL $Url" }
    $source = Join-Path (Join-Path $Root 'release') $Url.Substring($prefix.Length)
    if (-not (Test-Path -LiteralPath $source)) { throw "404 $source" }
    Copy-Item -LiteralPath $source -Destination $Path
}

# What another process could do to the verified file while the elevation prompt is open (R23).
function Start-ElevatedProcess {
    param([string]$Path, [string[]]$Arguments)
    Write-Log "elevated: $Path $($Arguments -join ' ')"
    $probe = @()
    try {
        $stream = [System.IO.File]::Open($Path, 'Open', 'Write', 'ReadWrite')
        $stream.Dispose()
        $probe += 'write=allowed'
    } catch { $probe += 'write=blocked' }
    try {
        Move-Item -LiteralPath $Path -Destination ($Path + '.moved') -ErrorAction Stop
        $probe += 'rename=allowed'
    } catch { $probe += 'rename=blocked' }
    try {
        Remove-Item -LiteralPath $Path -Force -ErrorAction Stop
        $probe += 'delete=allowed'
    } catch { $probe += 'delete=blocked' }
    try {
        $stream = [System.IO.File]::Open($Path, 'Open', 'Read', 'Read')
        $stream.Dispose()
        $probe += 'read=allowed'
    } catch { $probe += 'read=blocked' }
    Write-Log ('probe: ' + ($probe -join ' '))
    $outcome = if ($Path.EndsWith('PawnIO_setup.exe')) { $env:FAKE_PAWNIO_ELEVATION } else { $env:FAKE_ELEVATION }
    if ($outcome -eq 'cancel') { return $null }
    if ($outcome) { return [int]$outcome }
    return 0
}

$code = Invoke-PhotonInstall -Version $wanted.Version -Yes:$wanted.Yes -DryRun:$wanted.DryRun -Help:$wanted.Help
"CODE=$code"
