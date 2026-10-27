param([string]$Source = (Join-Path $PSScriptRoot 'windows-bootstrap.ps1'))
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
[System.Management.Automation.Language.Parser]::ParseFile($Source, [ref]$tokens, [ref]$errors) | Out-Null
if ($errors.Count) { throw ($errors | Out-String) }
. $Source -LibraryOnly
$temporary = Join-Path ([IO.Path]::GetTempPath()) ('msnr-bootstrap-test-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $temporary | Out-Null
try {
    if ($env:OS -eq 'Windows_NT') {
        Set-PrivateDirectory $temporary
        if (-not (Get-Acl -LiteralPath $temporary).AreAccessRulesProtected) { throw 'Private directory ACL did not apply.' }
    }
    $archive = Join-Path $temporary 'archive.zip'
    [IO.File]::WriteAllText($archive, 'known content')
    $hash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash
    Assert-ArchiveHash $archive $hash
    $rejected = $false
    try { Assert-ArchiveHash $archive ('0' * 64) } catch { $rejected = $true }
    if (-not $rejected) { throw 'Corrupt archive was accepted.' }
    $rejected = $false
    try { Get-Download 'http://invalid.example/file' $archive } catch { $rejected = $true }
    if (-not $rejected) { throw 'An unencrypted download was accepted.' }
    $app = Join-Path $temporary 'app'
    New-Item -ItemType Directory -Path $app | Out-Null
    [IO.File]::WriteAllText((Join-Path $app 'journal-to-preserve'), 'do not overwrite')
    $rejected = $false
    try { Install-Project $temporary $temporary } catch { $rejected = $true }
    if (-not $rejected -or -not (Test-Path (Join-Path $app 'journal-to-preserve'))) { throw 'Existing installation was not preserved.' }
    # Exercise the actual staged update with synthetic local files, without running installers.
    if ($env:OS -ne 'Windows_NT') { function Assert-InstallationStopped([string]$App) { } }
    $SourceCommit = 'f' * 40
    $releaseDirectory = Join-Path $temporary ("MSnR-$SourceCommit")
    foreach ($name in @('pyproject.toml', 'requirements-windows.lock', 'src/msnr/desktop.py', 'config/default.json')) {
        $file = Join-Path $releaseDirectory $name
        New-Item -ItemType Directory -Path (Split-Path $file -Parent) -Force | Out-Null
        [IO.File]::WriteAllText($file, 'synthetic test file')
    }
    $candidate = Join-Path $temporary 'candidate.zip'
    Compress-Archive -Path $releaseDirectory -DestinationPath $candidate
    $SourceSha256 = (Get-FileHash $candidate -Algorithm SHA256).Hash.ToLowerInvariant()
    @{ commit = ('a' * 40); sha256 = ('b' * 64) } | ConvertTo-Json | Set-Content (Join-Path $app '.msnr-source.json')
    New-Item -ItemType Directory -Path (Join-Path $app 'var') | Out-Null
    [IO.File]::WriteAllText((Join-Path $app 'var/state.txt'), 'retain exact runtime state')
    $downloads = Join-Path $temporary 'downloads'
    New-Item -ItemType Directory -Path $downloads | Out-Null
    $priorArchive = $env:MSNR_SOURCE_ARCHIVE
    try {
        $env:MSNR_SOURCE_ARCHIVE = $candidate
        $updated = Install-Project $temporary $downloads
        if ([IO.File]::ReadAllText((Join-Path $updated 'var/state.txt')) -ne 'retain exact runtime state') { throw 'Runtime state was lost during update.' }
        if (-not (Test-Path (Join-Path $script:UpgradeBackup 'journal-to-preserve'))) { throw 'Original installation backup missing.' }
    } finally { $env:MSNR_SOURCE_ARCHIVE = $priorArchive }
    Write-Host 'PASS: PowerShell syntax, checksum, HTTPS, existing-folder protection and state-preserving update'
} finally {
    Remove-Item -LiteralPath $temporary -Recurse -Force
}
