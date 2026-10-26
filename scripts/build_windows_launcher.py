"""Build the one downloadable CMD file from the reviewed PowerShell source."""

import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
release = json.loads((root / "deployment/windows-release.json").read_text())
payload = (root / "deployment/windows-bootstrap.ps1").read_text()
payload = payload.replace("__SOURCE_COMMIT__", release["commit"]).replace(
    "__SOURCE_SHA256__", release["sha256"]
)
header = r"""@echo off
setlocal
set "MSNR_SETUP_SELF=%~f0"
rem Do not inherit PowerShell 7 module paths into Windows PowerShell 5.1.
set "PSModulePath="
powershell.exe -NoLogo -NoProfile -Command "try { $raw = [IO.File]::ReadAllText($env:MSNR_SETUP_SELF); $marker = '# MSNR_POWERSHELL_PAYLOAD'; $code = $raw.Substring($raw.LastIndexOf($marker) + $marker.Length); & ([ScriptBlock]::Create($code)); exit 0 } catch { Write-Host ('MSnR setup stopped: ' + $_.Exception.Message) -ForegroundColor Red; exit 1 }"
set "MSNR_SETUP_EXIT=%ERRORLEVEL%"
if not "%MSNR_SETUP_TEST%"=="1" if not "%MSNR_SETUP_EXIT%"=="0" pause
exit /b %MSNR_SETUP_EXIT%
# MSNR_POWERSHELL_PAYLOAD
"""
(root / "Install-MSnR.cmd").write_bytes(
    (header + payload).replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")
)
print("Built Install-MSnR.cmd for source " + release["commit"])
