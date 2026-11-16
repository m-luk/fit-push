"""Windows taskbar identity for the fit-push app window.

A Chromium ``--app`` window belongs to the browser: pinned to the taskbar it becomes a
browser shortcut (browser icon, and it opens the URL without starting the server). Setting
the window's AppUserModel properties gives it fit-push's own taskbar identity: its own
taskbar button, and a pin that shows the fit-push icon and runs the fit-push launcher.

https://learn.microsoft.com/windows/win32/shell/appids
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TITLE = "fit-push"  # <title> of index.html: how the app window is found
BROWSER_EXES = ("msedge.exe", "chrome.exe", "brave.exe", "chromium.exe", "vivaldi.exe")


@dataclass(frozen=True)
class Identity:
    app_id: str
    command: str
    name: str
    icon: str | None  # "path,index"


def identity() -> Identity | None:
    """How a pinned fit-push window relaunches: the desktop exe, or this checkout's dev launcher."""
    if getattr(sys, "frozen", False):
        exe = sys.executable
        return Identity("fit-push.app", subprocess.list2cmdline([exe]), "fit-push", f"{exe},0")
    command = os.environ.get("FITPUSH_RELAUNCH")
    if not command:
        script = ROOT / "scripts" / "devapp.py"
        if not script.is_file():
            return None
        command = subprocess.list2cmdline([sys.executable, str(script), "launch"])
    icon = ROOT / "build" / "devapp" / "fit-push.ico"
    return Identity("fit-push.dev", command, "fit-push (dev)", f"{icon},0" if icon.is_file() else None)


def tag_app_windows(timeout: float = 20.0) -> None:
    """Give fit-push app windows that appear within `timeout` s their taskbar identity (Windows only).

    For a launcher that only opens a window for an already running server and exits: the
    thread is non-daemon so it finishes first. Never raises.
    """
    if sys.platform != "win32" or not (ident := identity()):
        return
    threading.Thread(target=_tag_loop, args=(ident, timeout), name="fitpush-taskbar").start()


def _tag_loop(ident: Identity, timeout: float) -> None:
    try:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            windows = _app_windows()
            if windows:
                for hwnd in windows:
                    _set_identity(hwnd, ident)
                return
            time.sleep(0.25)
    except Exception:  # pragma: no cover - cosmetic; must never break the launcher
        pass


def watch_app_windows(on_all_closed: Callable[[], None], grace: float = 4.0, appear: float = 60.0) -> bool:
    """Tag fit-push app windows as they appear and call `on_all_closed` once the last one is gone.

    The server process runs this. "Gone" means no app window for `grace` seconds, so a page
    reload (the title is briefly the URL) or a dev auto-reload doesn't count. If no window
    shows up within `appear` seconds nothing is stopped. Windows only; returns whether it
    started.
    """
    if sys.platform != "win32":
        return False
    ident = identity()
    threading.Thread(
        target=_watch_loop, args=(ident, on_all_closed, grace, appear), name="fitpush-windows", daemon=True
    ).start()
    return True


def _watch_loop(ident: Identity | None, on_all_closed: Callable[[], None], grace: float, appear: float) -> None:
    tagged: set[int] = set()
    started = last_seen = time.monotonic()
    seen = False
    try:
        while True:
            now = time.monotonic()
            windows = _app_windows()
            if windows:
                seen, last_seen = True, now
                for hwnd in set(windows) - tagged:
                    if ident:
                        _set_identity(hwnd, ident)
                    tagged.add(hwnd)
            elif seen and now - last_seen >= grace:
                on_all_closed()
                return
            elif not seen and now - started >= appear:
                return
            time.sleep(0.5)
    except Exception:  # pragma: no cover - must never break the server
        return


def stop_server() -> None:
    """Stop fit-push like Ctrl+C in its console: uvicorn (also its --reload worker) and the launchers exit."""
    if sys.platform == "win32" and _kernel32.GenerateConsoleCtrlEvent(0, 0):  # CTRL_C_EVENT to this console
        return
    import _thread
    import signal

    _thread.interrupt_main(signal.SIGINT)


# ----------------------------------------------------------------------------- Win32 (ctypes)

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    _ole32 = ctypes.WinDLL("ole32", use_last_error=True)

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", ctypes.c_uint32),
            ("Data2", ctypes.c_uint16),
            ("Data3", ctypes.c_uint16),
            ("Data4", ctypes.c_ubyte * 8),
        ]

    def _guid(s: str) -> GUID:
        u = uuid.UUID(s)
        g = GUID(u.time_low, u.time_mid, u.time_hi_version)
        g.Data4[:] = list(u.bytes[8:])
        return g

    class PROPERTYKEY(ctypes.Structure):
        _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]

    class PROPVARIANT(ctypes.Structure):
        _fields_ = [
            ("vt", ctypes.c_ushort),
            ("reserved1", ctypes.c_ushort),
            ("reserved2", ctypes.c_ushort),
            ("reserved3", ctypes.c_ushort),
            ("pwszVal", ctypes.c_wchar_p),
            ("pad", ctypes.c_void_p),
        ]

    _VT_LPWSTR = 31
    _IID_IPropertyStore = _guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")
    _AUMID_FMT = "9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"
    _PKEY_ID = PROPERTYKEY(_guid(_AUMID_FMT), 5)
    _PKEY_RELAUNCH_COMMAND = PROPERTYKEY(_guid(_AUMID_FMT), 2)
    _PKEY_RELAUNCH_ICON = PROPERTYKEY(_guid(_AUMID_FMT), 3)
    _PKEY_RELAUNCH_NAME = PROPERTYKEY(_guid(_AUMID_FMT), 4)

    _SetValue = ctypes.WINFUNCTYPE(
        ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(PROPERTYKEY), ctypes.POINTER(PROPVARIANT)
    )
    _Commit = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)
    _Release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)
    _EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    _shell32.SHGetPropertyStoreForWindow.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(GUID),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    _shell32.SHGetPropertyStoreForWindow.restype = ctypes.c_long
    _user32.EnumWindows.argtypes = [_EnumProc, wintypes.LPARAM]
    _user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    _user32.IsWindowVisible.argtypes = [wintypes.HWND]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.GenerateConsoleCtrlEvent.argtypes = [wintypes.DWORD, wintypes.DWORD]

    def _process_name(hwnd: int) -> str:
        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        handle = _kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(len(buf))
            ok = _kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size))
            return Path(buf.value).name.lower() if ok else ""
        finally:
            _kernel32.CloseHandle(handle)

    def _app_windows() -> list[int]:
        """Visible Chromium top-level windows titled exactly like the app (browser tabs add a suffix)."""
        found: list[int] = []

        def visit(hwnd: int, _: int) -> bool:
            if _user32.IsWindowVisible(hwnd):
                title = ctypes.create_unicode_buffer(256)
                _user32.GetWindowTextW(hwnd, title, 256)
                cls = ctypes.create_unicode_buffer(64)
                _user32.GetClassNameW(hwnd, cls, 64)
                if title.value == TITLE and cls.value == "Chrome_WidgetWin_1" and _process_name(hwnd) in BROWSER_EXES:
                    found.append(hwnd)
            return True

        _user32.EnumWindows(_EnumProc(visit), 0)
        return found

    def _set_identity(hwnd: int, ident: Identity) -> bool:
        store = ctypes.c_void_p()
        if _shell32.SHGetPropertyStoreForWindow(hwnd, ctypes.byref(_IID_IPropertyStore), ctypes.byref(store)) < 0:
            return False
        vtbl = ctypes.cast(store, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        set_value, commit, release = _SetValue(vtbl[6]), _Commit(vtbl[7]), _Release(vtbl[2])
        try:
            values = [(_PKEY_RELAUNCH_COMMAND, ident.command), (_PKEY_RELAUNCH_NAME, ident.name)]
            if ident.icon:
                values.append((_PKEY_RELAUNCH_ICON, ident.icon))
            values.append((_PKEY_ID, ident.app_id))  # last: the taskbar reads the relaunch data on ID change
            ok = True
            for key, text in values:
                pv = PROPVARIANT(vt=_VT_LPWSTR, pwszVal=text)
                ok = set_value(store, ctypes.byref(key), ctypes.byref(pv)) >= 0 and ok
            return commit(store) >= 0 and ok
        finally:
            release(store)

else:

    def _app_windows() -> list[int]:
        return []

    def _set_identity(hwnd: int, ident: Identity) -> bool:
        return False
