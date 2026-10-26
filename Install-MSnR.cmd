@echo off
setlocal
set "MSNR_SETUP_SELF=%~f0"
powershell.exe -NoLogo -NoProfile -Command "try { $raw = [IO.File]::ReadAllText($env:MSNR_SETUP_SELF); $marker = '# MSNR_POWERSHELL_PAYLOAD'; $code = $raw.Substring($raw.LastIndexOf($marker) + $marker.Length); & ([ScriptBlock]::Create($code)); exit 0 } catch { Write-Host ('MSnR setup stopped: ' + $_.Exception.Message) -ForegroundColor Red; exit 1 }"
set "MSNR_SETUP_EXIT=%ERRORLEVEL%"
if not "%MSNR_SETUP_TEST%"=="1" if not "%MSNR_SETUP_EXIT%"=="0" pause
exit /b %MSNR_SETUP_EXIT%
# MSNR_POWERSHELL_PAYLOAD
param([switch]$LibraryOnly)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$SourceCommit = '2b0874403677fa44ce75949270fa5f80fbbaacc7'
$SourceSha256 = '41a8abe46bc1c72ffd010c1ce61b115c016a9a9fed722eb75620fa3b1051e63a'
$SourceUrl = "https://codeload.github.com/airateenarogers-a11y/MSnR/zip/$SourceCommit"

function Invoke-Native([string]$Executable, [string[]]$Arguments) {
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed with exit code $LASTEXITCODE. Review the output above." }
}

function Assert-ArchiveHash([string]$Path, [string]$Expected) {
    if ((Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Expected.ToLowerInvariant()) {
        throw 'Project checksum mismatch. The downloaded archive will not be installed.'
    }
}

function Get-Download([string]$Url, [string]$Destination) {
    if (-not $Url.StartsWith('https://')) { throw 'Downloads require HTTPS.' }
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        try {
            Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Destination -TimeoutSec 180
            return
        } catch {
            if ($attempt -eq 3) { throw }
            Start-Sleep -Seconds (2 * $attempt)
        }
    }
}

function Assert-VendorSignature([string]$Path, [string]$Publisher) {
    $signature = Get-AuthenticodeSignature -LiteralPath $Path
    if ($signature.Status -ne 'Valid' -or $null -eq $signature.SignerCertificate -or
        $signature.SignerCertificate.Subject -notmatch $Publisher) {
        throw 'The downloaded installer does not have the expected valid publisher signature.'
    }
}

function Set-PrivateDirectory([string]$Path) {
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User
    $acl = New-Object Security.AccessControl.DirectorySecurity
    $acl.SetOwner($sid)
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($identity in @($sid, [Security.Principal.SecurityIdentifier]'S-1-5-18', [Security.Principal.SecurityIdentifier]'S-1-5-32-544')) {
        $rule = New-Object Security.AccessControl.FileSystemAccessRule($identity, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
        $acl.AddAccessRule($rule)
    }
    Set-Acl -LiteralPath $Path -AclObject $acl
}

function Find-Python {
    $candidates = @()
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        try {
            $path = & $launcher.Source -3.12 -c 'import sys; print(sys.executable)' 2>$null
            if ($LASTEXITCODE -eq 0 -and $path) { $candidates += [string]$path }
        } catch { }
    }
    $candidates += (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe')
    $command = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($command -and $command.Source -notmatch '\\WindowsApps\\') { $candidates += $command.Source }
    foreach ($path in $candidates) {
        if (Test-Path -LiteralPath $path -PathType Leaf) {
            try {
                $ok = & $path -c 'import sys; print(sys.version_info[:2] == (3, 12) and sys.maxsize > 2**32)' 2>$null
                if ($LASTEXITCODE -eq 0 -and $ok -eq 'True') { return $path }
            } catch { }
        }
    }
    return $null
}

function Install-Python([string]$Downloads) {
    $python = Find-Python
    if ($python) { return $python }
    Write-Host 'Installing Python 3.12 for the current Windows user...'
    # 3.12.10 is the Python.org Windows installer baseline; reuse an existing 3.12 installation when available.
    $installer = Join-Path $Downloads 'python-3.12.10-amd64.exe'
    Get-Download 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' $installer
    Assert-VendorSignature $installer 'Python Software Foundation'
    $process = Start-Process -FilePath $installer -ArgumentList @('/quiet', 'InstallAllUsers=0', 'PrependPath=0', 'Include_launcher=0', 'Include_pip=1', 'Include_tcltk=1', 'Include_test=0') -Wait -PassThru
    if ($process.ExitCode -notin @(0, 3010)) { throw "Python setup failed with exit code $($process.ExitCode)." }
    $python = Find-Python
    if (-not $python) { throw 'Python 3.12 x64 was not found after setup. Restart Windows if setup requested it, then rerun this file.' }
    return $python
}

function Find-Chrome {
    foreach ($base in @($env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:LOCALAPPDATA)) {
        if ($base) {
            $path = Join-Path $base 'Google\Chrome\Application\chrome.exe'
            if (Test-Path -LiteralPath $path -PathType Leaf) { return $path }
        }
    }
    return $null
}

function Find-MT5 {
    foreach ($base in @($env:ProgramFiles, ${env:ProgramFiles(x86)})) {
        if ($base) {
            $files = @(Get-ChildItem -Path (Join-Path $base '*\terminal64.exe') -File -ErrorAction SilentlyContinue)
            if ($files.Count -gt 0) { return $files[0].FullName }
        }
    }
    return $null
}

function Install-ChartBrowser([string]$Downloads) {
    if (Find-Chrome) { return }
    try {
        Write-Host 'Installing Google Chrome. Windows may request installation permission...'
        $installer = Join-Path $Downloads 'ChromeStandaloneSetup64.exe'
        Get-Download 'https://dl.google.com/chrome/install/ChromeStandaloneSetup64.exe' $installer
        Assert-VendorSignature $installer 'Google (LLC|Inc\.?)'
        $process = Start-Process -FilePath $installer -ArgumentList @('/silent', '/install') -Wait -PassThru
        if ($process.ExitCode -notin @(0, 3010) -or -not (Find-Chrome)) { throw 'Chrome installation was not completed.' }
    } catch {
        Write-Warning 'Chrome is unavailable. The dashboard and deterministic signal charts can still start. Install Chrome later for TradingView inspection.'
    }
}

function Install-Terminal([string]$Downloads) {
    $terminal = Find-MT5
    if ($terminal) { return $terminal }
    try {
        Write-Host 'Opening the official MT5 installer. Complete its prompts, then sign in to your broker DEMO account.'
        $installer = Join-Path $Downloads 'mt5setup.exe'
        Get-Download 'https://download.mql5.com/cdn/web/metaquotes.ltd/mt5/mt5setup.exe' $installer
        Assert-VendorSignature $installer 'MetaQuotes (Ltd\.?|Software Corp\.?)'
        $process = Start-Process -FilePath $installer -Wait -PassThru
        if ($process.ExitCode -notin @(0, 3010)) { throw 'MT5 installation was cancelled or failed.' }
        return (Find-MT5)
    } catch {
        Write-Warning 'MT5 is not installed yet. The paper dashboard will start; use your broker installer and Choose MT5 terminal when ready.'
        return $null
    }
}

function Install-Project([string]$Root, [string]$Downloads) {
    $app = Join-Path $Root 'app'
    $marker = Join-Path $app '.msnr-source.json'
    if (Test-Path -LiteralPath $app) {
        if (-not (Test-Path -LiteralPath $marker)) { throw "An unrecognized app folder exists at $app. It will not be overwritten." }
        $installed = Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json
        if ($installed.commit -ne $SourceCommit -or $installed.sha256 -ne $SourceSha256) {
            throw 'This installation belongs to another source release. Back up its journal and follow the upgrade guide; it will not be overwritten.'
        }
        return $app
    }
    $archive = Join-Path $Downloads "source-$SourceCommit.zip"
    if (Test-Path -LiteralPath $archive) {
        try { Assert-ArchiveHash $archive $SourceSha256 }
        catch { Remove-Item -LiteralPath $archive -Force }
    }
    if ($env:MSNR_SOURCE_ARCHIVE) {
        Copy-Item -LiteralPath $env:MSNR_SOURCE_ARCHIVE -Destination $archive -Force
    } elseif (-not (Test-Path -LiteralPath $archive)) {
        Write-Host 'Downloading the pinned MSnR project release...'
        try { Get-Download $SourceUrl $archive } catch {
            if ($env:MSNR_SETUP_TEST -eq '1') { throw }
            Write-Host "Download failed. For a private repository, sign in to GitHub in your browser and download: $SourceUrl"
            $local = (Read-Host 'Paste the full path to that downloaded ZIP').Trim('"')
            Copy-Item -LiteralPath $local -Destination $archive -Force
        }
    }
    Assert-ArchiveHash $archive $SourceSha256
    $stage = Join-Path $Root ('.extract-' + [guid]::NewGuid().ToString('N'))
    try {
        Expand-Archive -LiteralPath $archive -DestinationPath $stage
        $source = Join-Path $stage "MSnR-$SourceCommit"
        foreach ($required in @('pyproject.toml', 'requirements-windows.lock', 'src/msnr/desktop.py', 'config/default.json')) {
            if (-not (Test-Path -LiteralPath (Join-Path $source $required) -PathType Leaf)) { throw 'The project archive is incomplete.' }
        }
        @{ commit = $SourceCommit; sha256 = $SourceSha256 } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $source '.msnr-source.json') -Encoding UTF8
        Move-Item -LiteralPath $source -Destination $app
    } finally {
        if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
    }
    return $app
}

function Main {
    if ($env:OS -ne 'Windows_NT' -or -not [Environment]::Is64BitOperatingSystem) { throw 'Use this launcher on 64-bit Windows 10/11 or a Windows VPS.' }
    if ($PSVersionTable.PSVersion -lt [version]'5.1') { throw 'Windows PowerShell 5.1 or newer is required.' }
    if ($env:MSNR_INSTALL_ROOT -and $env:MSNR_SETUP_TEST -ne '1') { throw 'MSNR_INSTALL_ROOT is reserved for the isolated installer self-test. Normal installation uses LOCALAPPDATA\MSnR.' }
    $root = if ($env:MSNR_INSTALL_ROOT) { [IO.Path]::GetFullPath($env:MSNR_INSTALL_ROOT) } else { Join-Path $env:LOCALAPPDATA 'MSnR' }
    New-Item -ItemType Directory -Path $root -Force | Out-Null
    Set-PrivateDirectory $root
    $installerLock = $null
    try {
        try { $installerLock = [IO.File]::Open((Join-Path $root 'setup.lock'), 'OpenOrCreate', 'ReadWrite', 'None') }
        catch { throw 'Another MSnR setup/control window is already open. Use that window.' }
        $downloads = Join-Path $root 'downloads'
        New-Item -ItemType Directory -Path $downloads -Force | Out-Null
        $python = Install-Python $downloads
        $app = Install-Project $root $downloads
        Set-Location -LiteralPath $app
        $venv = Join-Path $app '.venv\Scripts\python.exe'
        if (-not (Test-Path -LiteralPath $venv)) { Invoke-Native $python @('-m', 'venv', '.venv') }
        $stamp = Join-Path $app '.desktop-dependencies-ready'
        if (-not (Test-Path -LiteralPath $stamp)) {
            Write-Host 'Installing hash-verified Python and MT5 dependencies. This can take several minutes...'
            $env:PIP_CACHE_DIR = Join-Path $root 'downloads\pip-cache'
            Invoke-Native $venv @('-m', 'pip', 'install', '--require-hashes', '-r', 'requirements-windows.lock')
            Invoke-Native $venv @('-m', 'pip', 'install', '--no-deps', '--no-build-isolation', '-e', '.')
            Invoke-Native $venv @('-m', 'pip', 'check')
            [IO.File]::WriteAllText($stamp, $SourceCommit)
        }
        Invoke-Native $venv @('-c', 'import msnr.desktop, MetaTrader5, tkinter')
        if ($env:MSNR_SETUP_TEST -ne '1') {
            Install-ChartBrowser $downloads
            $terminal = Install-Terminal $downloads
            if ($terminal) { $env:MSNR_DESKTOP_MT5_PATH = $terminal }
            $chrome = Find-Chrome
            if ($chrome) { $env:MSNR_CHROME_EXECUTABLE = $chrome }
            if ($env:MSNR_SETUP_SELF) {
                $copy = Join-Path $root 'Start-MSnR.cmd'
                if ([IO.Path]::GetFullPath($env:MSNR_SETUP_SELF) -ne $copy) { Copy-Item -LiteralPath $env:MSNR_SETUP_SELF -Destination $copy -Force }
                $desktop = [Environment]::GetFolderPath('Desktop')
                $link = Join-Path $desktop 'MSnR Trading Ledger.lnk'
                if (-not (Test-Path -LiteralPath $link)) {
                    $shell = New-Object -ComObject WScript.Shell
                    $shortcut = $shell.CreateShortcut($link)
                    $shortcut.TargetPath = $copy
                    $shortcut.WorkingDirectory = $app
                    $shortcut.Description = 'Start the local MSnR paper trading control center'
                    $shortcut.Save()
                }
            }
            Write-Host 'Starting PAPER mode. Keep the control window open. Use Copy sign-in key to sign in to the dashboard.'
            Invoke-Native $venv @('-m', 'msnr.desktop', '--root', $app)
        } else {
            Invoke-Native $venv @('-m', 'msnr.desktop', '--root', $app, '--self-test')
        }
    } finally {
        if ($installerLock) { $installerLock.Dispose() }
    }
}

if (-not $LibraryOnly) {
    try { Main } catch {
        if ($env:MSNR_SETUP_TEST -eq '1') {
            $detail = ('MSnR bootstrap: ' + $_.Exception.Message + ' | ' + $_.ScriptStackTrace).Replace('%', '%25').Replace("`r", '%0D').Replace("`n", '%0A')
            Write-Host "::error::$detail"
        }
        throw
    }
}
