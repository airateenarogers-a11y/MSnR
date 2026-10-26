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
    Write-Host 'PASS: PowerShell syntax, checksum enforcement, HTTPS enforcement and existing-folder protection'
} finally {
    Remove-Item -LiteralPath $temporary -Recurse -Force
}
