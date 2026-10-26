"""Local Windows control panel for authorized demo automation; live execution is refused."""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
import webbrowser

import httpx

from .config import load


def atomic_json(path: Path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def protect_secret(value: bytes, decrypt=False) -> bytes:
    """Windows DPAPI binds ciphertext to this user's Windows profile."""
    if os.name != "nt":
        raise RuntimeError("The desktop credential vault requires Windows")

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_char))]

    buffer = ctypes.create_string_buffer(value)
    source = Blob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    output = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    fn = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    fn.argtypes = [
        ctypes.POINTER(Blob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(Blob),
    ]
    fn.restype = wintypes.BOOL
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        kernel.LocalFree(ctypes.cast(output.data, ctypes.c_void_p))


class Vault:
    def __init__(self, path: Path, codec=protect_secret):
        self.path, self.codec = path, codec

    def read(self):
        if self.path.exists():
            value = json.loads(self.codec(self.path.read_bytes(), decrypt=True))
            if any(len(value.get(k, "")) < 32 for k in ("operator", "bridge")):
                raise ValueError("Credential vault is invalid; restore it instead of replacing it")
            return value
        value = {
            "operator": secrets.token_urlsafe(32),
            "bridge": secrets.token_urlsafe(32),
            "webhook": "",
            "terminal": os.getenv("MSNR_DESKTOP_MT5_PATH", ""),
        }
        self.save(value)
        return value

    def save(self, value):
        temporary = self.path.with_suffix(".tmp")
        temporary.write_bytes(self.codec(json.dumps(value).encode()))
        temporary.chmod(0o600)
        temporary.replace(self.path)


class InstanceLock:
    def __init__(self, path: Path):
        self.file = path.open("a+b")
        if self.file.tell() == 0:
            self.file.write(b"0")
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError("MSnR is already running. Use its existing control window.") from None

    def close(self):
        self.file.close()


class ProcessJob:
    """Windows automatically terminates only our child services if this launcher dies."""

    def __init__(self):
        self.handle = None
        if os.name != "nt":
            return

        class Basic(ctypes.Structure):
            _fields_ = [
                ("process_time", ctypes.c_longlong),
                ("job_time", ctypes.c_longlong),
                ("flags", wintypes.DWORD),
                ("min_ws", ctypes.c_size_t),
                ("max_ws", ctypes.c_size_t),
                ("processes", wintypes.DWORD),
                ("affinity", ctypes.c_size_t),
                ("priority", wintypes.DWORD),
                ("scheduling", wintypes.DWORD),
            ]

        class Extended(ctypes.Structure):
            _fields_ = [
                ("basic", Basic),
                ("io", ctypes.c_ulonglong * 6),
                ("process_memory", ctypes.c_size_t),
                ("job_memory", ctypes.c_size_t),
                ("peak_process", ctypes.c_size_t),
                ("peak_job", ctypes.c_size_t),
            ]

        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        self.kernel.SetInformationJobObject.restype = wintypes.BOOL
        self.kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.kernel.AssignProcessToJobObject.restype = wintypes.BOOL
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = self.kernel.CreateJobObjectW(None, None)
        limits = Extended()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.handle or not self.kernel.SetInformationJobObject(
            self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
        ):
            self.close()
            raise ctypes.WinError(ctypes.get_last_error())

    def assign(self, process):
        if self.handle and not self.kernel.AssignProcessToJobObject(self.handle, int(process._handle)):
            process.kill()
            process.wait()
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def free_port(preferred):
    for port in range(preferred, preferred + 30):
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                pass
    raise RuntimeError(f"No free loopback port near {preferred}")


class Supervisor:
    def __init__(self, root: Path, credentials: dict, mode="demo"):
        if mode not in ("demo", "paper"):
            raise ValueError("Desktop mode must be demo or paper; live is disabled")
        self.mode = mode
        self.root, self.credentials = root.resolve(), credentials
        self.state = self.root / "var/desktop"
        self.state.mkdir(parents=True, exist_ok=True)
        self.config = self.state / f"{mode}-config.json"
        self.database = self.state / f"{mode}.db"
        if not self.config.exists():
            settings = load(self.root / "config/default.json")
            settings = settings.model_copy(update={"mode": mode, "live_authorization_file": None})
            atomic_json(self.config, settings.model_dump())
        settings = load(self.config)
        if settings.mode != mode or settings.live_authorization_file is not None:
            raise ValueError("Desktop config must match the selected demo/paper mode with live disabled.")
        self.processes = {}
        self.streams = {}
        self.stop_files = {}
        self.job = ProcessJob()
        self.dashboard_port, self.bridge_port = free_port(8000), free_port(8765)
        self.feed_connected = False

    @property
    def url(self):
        return f"http://127.0.0.1:{self.dashboard_port}"

    def environment(self, feed=False):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("MSNR_", "MT5_"))}
        env.update(
            {
                "MSNR_CONFIG": str(self.config),
                "MSNR_DB": str(self.database),
                "MSNR_OPERATOR_TOKEN": self.credentials["operator"],
                "MSNR_BRIDGE_TOKEN": self.credentials["bridge"],
                "MPLCONFIGDIR": str(self.state / "cache/matplotlib"),
                "XDG_CACHE_HOME": str(self.state / "cache"),
                "PYTHONUNBUFFERED": "1",
            }
        )
        if feed:
            env["MSNR_BRIDGE_URL"] = f"http://127.0.0.1:{self.bridge_port}"
        if self.credentials.get("webhook"):
            env["MSNR_DISCORD_WEBHOOK"] = self.credentials["webhook"]
        if self.credentials.get("terminal"):
            env["MT5_TERMINAL_PATH"] = self.credentials["terminal"]
        return env

    def start_process(self, role, feed=False):
        settings = load(self.config)
        if settings.mode != self.mode or settings.live_authorization_file is not None:
            raise ValueError("Desktop execution must remain in the selected demo/paper mode")
        if role in self.processes and self.processes[role].poll() is None:
            return
        self.stop_process(role)
        args = [sys.executable, "-m", "msnr.cli", "serve" if role == "dashboard" else role]
        if role in ("dashboard", "bridge"):
            args += ["--port", str(self.dashboard_port if role == "dashboard" else self.bridge_port)]
        stream = (self.state / f"{role}.log").open("ab", buffering=0)
        env = self.environment(feed)
        if role == "worker":
            stop_file = self.state / ("stop-" + secrets.token_hex(12))
            self.stop_files[role] = stop_file
            env["MSNR_WORKER_STOP_FILE"] = str(stop_file)
        options = (
            {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
            if os.name == "nt"
            else {"start_new_session": True}
        )
        try:
            process = subprocess.Popen(
                args,
                cwd=self.root,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=stream,
                stderr=subprocess.STDOUT,
                **options,
            )
            self.job.assign(process)
        except BaseException:
            stream.close()
            raise
        self.processes[role], self.streams[role] = process, stream

    def stop_process(self, role):
        process = self.processes.pop(role, None)
        stop_file = self.stop_files.pop(role, None)
        if stop_file:
            stop_file.touch()
        if process and process.poll() is None:
            try:
                if os.name != "nt" or not stop_file:
                    process.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGTERM)
                process.wait(timeout=25)
            except (OSError, subprocess.TimeoutExpired):
                process.kill()
                process.wait(timeout=5)
        stream = self.streams.pop(role, None)
        if stream:
            stream.close()
        if stop_file:
            stop_file.unlink(missing_ok=True)

    def start(self):
        self.start_process("dashboard")
        with httpx.Client(trust_env=False, timeout=1) as client:
            for _ in range(60):
                process = self.processes["dashboard"]
                if process.poll() is not None:
                    raise RuntimeError("Dashboard could not start. Inspect var/desktop/dashboard.log.")
                try:
                    r = client.get(
                        self.url + "/api/status",
                        headers={"Authorization": "Bearer " + self.credentials["operator"]},
                    )
                    if r.status_code == 200 and r.json()["mode"] == self.mode:
                        break
                except (httpx.HTTPError, ValueError):
                    pass
                time.sleep(0.2)
            else:
                raise RuntimeError("Dashboard did not become healthy; check its log and firewall.")
        self.start_process("worker", self.feed_connected)
        atomic_json(self.state / "running.json", {"url": self.url, "mode": self.mode})

    def connect(self):
        path = self.credentials.get("terminal", "")
        if not path or not Path(path).is_file():
            return "Choose your broker's terminal64.exe, then sign in to a hedging DEMO account."
        self.start_process("bridge")
        try:
            with httpx.Client(trust_env=False, timeout=2) as client:
                response = client.get(
                    f"http://127.0.0.1:{self.bridge_port}/account",
                    headers={"Authorization": "Bearer " + self.credentials["bridge"]},
                )
                response.raise_for_status()
                account = response.json()
            if account.get("mode") != "demo" or not account.get("hedging"):
                return "MT5 must be signed in to a hedging DEMO account. The worker remains disconnected."
            if self.mode == "demo" and not account.get("trading_allowed"):
                return "Enable MT5 Algo Trading and allow external Python trading, then click Connect MT5."
        except (httpx.HTTPError, ValueError):
            return "Waiting for MT5 demo login. Keep the terminal open, then click Connect MT5 again."
        if not self.feed_connected:
            self.stop_process("worker")
            self.start_process("worker", feed=True)
            self.feed_connected = True
        return (
            "Automatic DEMO execution enabled. Every strategy and risk condition must pass before an order."
            if self.mode == "demo"
            else "MT5 demo feed connected. Executions remain simulated in PAPER mode."
        )

    def restart_worker(self):
        self.stop_process("worker")
        self.start_process("worker", self.feed_connected)

    def close(self):
        try:
            for role in ("worker", "bridge", "dashboard"):
                self.stop_process(role)
        finally:
            self.job.close()


def gui(supervisor: Supervisor, vault: Vault):
    import tkinter as tk
    from tkinter import filedialog, messagebox, simpledialog, ttk

    window = tk.Tk()
    window.title("MSnR · Local control center")
    window.geometry("760x520")
    window.minsize(680, 480)
    frame = ttk.Frame(window, padding=28)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="MSnR · Trading Ledger", font=("Segoe UI", 23, "bold")).pack(anchor="w")
    ttk.Label(
        frame, text=f"{supervisor.mode.upper()} MODE  /  automatic execution  /  live trading disabled"
    ).pack(anchor="w", pady=10)
    status = tk.StringVar(value="Starting dashboard and market worker…")
    services = tk.StringVar(value="")
    ttk.Label(frame, textvariable=status, wraplength=690).pack(anchor="w", pady=16)
    ttk.Label(frame, textvariable=services).pack(anchor="w", pady=10)
    busy = False
    closed = False

    def action(fn):
        nonlocal busy
        if busy:
            return
        busy = True

        def run():
            nonlocal busy
            try:
                result = fn()
                window.after(0, lambda: status.set(result or "Ready."))
            except Exception as exc:
                message = str(exc)
                window.after(0, lambda: status.set("Action failed: " + message))
            finally:
                busy = False

        threading.Thread(target=run, daemon=True).start()

    def open_dashboard():
        webbrowser.open(supervisor.url)

    def copy_key():
        window.clipboard_clear()
        window.clipboard_append(supervisor.credentials["operator"])
        status.set("Sign-in key copied. Paste it into the dashboard's Sign in form.")

    def terminal():
        filename = filedialog.askopenfilename(
            title="Choose your broker's MT5 terminal64.exe", filetypes=[("MT5 terminal", "terminal64.exe")]
        )
        if filename:
            if busy:
                messagebox.showinfo("Please wait", "Wait for the current operation to finish.")
                return

            def change():
                supervisor.stop_process("worker")
                supervisor.stop_process("bridge")
                supervisor.feed_connected = False
                supervisor.credentials["terminal"] = filename
                vault.save(supervisor.credentials)
                supervisor.start_process("worker")
                return "Terminal selected. Sign in to the demo account and click Connect MT5."

            action(change)

    def discord():
        from urllib.parse import urlsplit

        value = simpledialog.askstring("Discord (optional)", "Webhook URL; leave empty to disable:", show="*")
        if value is None or busy:
            return
        value = value.strip()
        parsed = urlsplit(value)
        if value and (
            parsed.scheme != "https"
            or parsed.netloc != "discord.com"
            or not parsed.path.startswith("/api/webhooks/")
            or parsed.query
            or parsed.fragment
        ):
            messagebox.showerror("Invalid webhook", "Use an HTTPS discord.com/api/webhooks/ URL.")
            return
        supervisor.credentials["webhook"] = value
        vault.save(supervisor.credentials)
        action(lambda: (supervisor.restart_worker(), "Discord setting saved securely; worker restarted.")[1])

    buttons = ttk.Frame(frame)
    buttons.pack(fill="x", pady=16)
    for i, (label, command) in enumerate(
        [
            ("Open dashboard", open_dashboard),
            ("Copy sign-in key", copy_key),
            ("Choose MT5 terminal", terminal),
            ("Connect MT5", lambda: action(supervisor.connect)),
            ("Configure Discord", discord),
            ("Open logs", lambda: os.startfile(supervisor.state)),
        ]
    ):
        ttk.Button(buttons, text=label, command=command).grid(
            row=i // 2, column=i % 2, sticky="ew", padx=(0, 12), pady=5
        )
    buttons.columnconfigure((0, 1), weight=1)
    ttk.Label(
        frame,
        text="Keep this window open while monitoring. Closing it stops these services.\nMT5 login and a broker demo account are supplied by you. No account is created automatically.",
        wraplength=690,
    ).pack(anchor="w", pady=12)

    def close():
        nonlocal closed
        if busy:
            status.set("Wait for the current operation to finish, then close the control window.")
            return
        closed = True
        try:
            if window.clipboard_get() == supervisor.credentials["operator"]:
                window.clipboard_clear()
        except tk.TclError:
            pass
        window.destroy()

    def refresh():
        if not closed:
            services.set(
                "   |   ".join(
                    f"{role.title()}: {'running' if p.poll() is None else 'stopped'}"
                    for role, p in list(supervisor.processes.items())
                )
            )
            window.after(1000, refresh)

    def startup():
        supervisor.start()
        webbrowser.open(supervisor.url)
        return (
            supervisor.connect()
            if supervisor.credentials.get("terminal")
            else (
                "Dashboard ready. Click Copy sign-in key to sign in. Select MT5 when your demo account is ready."
            )
        )

    window.protocol("WM_DELETE_WINDOW", close)
    refresh()
    action(startup)
    window.mainloop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--mode", choices=("demo", "paper"), default="demo")
    parser.add_argument(
        "--self-test", action="store_true", help="Verify local service startup; no MT5 orders"
    )
    args = parser.parse_args()
    root = args.root.resolve()
    state = root / "var/desktop"
    state.mkdir(parents=True, exist_ok=True)
    lock = InstanceLock(state / "instance.lock")
    supervisor = None
    try:
        vault = Vault(state / "credentials.dpapi")
        credentials = vault.read()
        supervisor = Supervisor(root, credentials, args.mode)
        if args.self_test:
            supervisor.start()
            with httpx.Client(trust_env=False) as client:
                assert client.get(supervisor.url + "/health").status_code == 200
                assert client.get(supervisor.url + "/api/status").status_code == 401
            # Give the worker a chance to reserve/release its real database lease.
            time.sleep(2)
            supervisor.close()
            from .store import Store

            store = Store(supervisor.database)
            assert store.state("worker_lease") is None
            assert store.verify_chain()
            print(
                "PASS: encrypted credentials, isolated services, authentication, shutdown and lease release"
            )
        else:
            gui(supervisor, vault)
    finally:
        if supervisor:
            supervisor.close()
        lock.close()


if __name__ == "__main__":
    main()
