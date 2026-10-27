"""Positive local-process identity checks; inaccessible processes are never declared dead."""

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import sys


def identity(pid: int) -> str | None:
    if not isinstance(pid, int) or pid <= 0:
        raise ValueError("Invalid process ID")
    if os.name == "nt":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        kernel.GetProcessTimes.restype = wintypes.BOOL
        handle = kernel.OpenProcess(0x1000 | 0x100000, False, pid)
        if not handle:
            error = ctypes.get_last_error()
            if error == 87:  # ERROR_INVALID_PARAMETER: no such process ID
                return None
            raise ctypes.WinError(error)
        try:
            status = kernel.WaitForSingleObject(handle, 0)
            if status == 0:  # terminated, including a process whose handle is still held elsewhere
                return None
            if status != 258:  # WAIT_TIMEOUT means it is still running
                raise ctypes.WinError(ctypes.get_last_error())
            times = [wintypes.FILETIME() for _ in range(4)]
            if not kernel.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
                raise ctypes.WinError(ctypes.get_last_error())
            created = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
            return f"windows:{created}"
        finally:
            kernel.CloseHandle(handle)
    if sys.platform.startswith("linux"):
        try:
            fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
            if fields[0] == "Z":
                return None
            boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
            return f"linux:{boot}:{fields[19]}"
        except FileNotFoundError:
            return None
    raise OSError("Process ownership cannot be verified on this platform")
