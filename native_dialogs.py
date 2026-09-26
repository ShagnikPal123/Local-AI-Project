"""The real Windows folder picker, opened by the engine on the owner's own desktop.

Request H1 (the owner's main focus): "in the code tab, make sure that there is a button where I
can search my files and it opens file explorer and when I click on the folder or folders I want
it takes those."

A browser page cannot do this: ``showDirectoryPicker()`` hands back a sandboxed handle with no
path, one folder at a time, and the engine needs real paths to read and edit. The engine runs on
the same PC, in the owner's session (started by the tray launcher), so it opens Windows' own
``IFileOpenDialog`` with ``FOS_PICKFOLDERS | FOS_ALLOWMULTISELECT`` — the Explorer dialog with
search, Quick access, "New folder" and Ctrl/Shift-click for several folders.

Plain ``ctypes`` COM: no pywin32 or comtypes in the venv, and nothing is compiled at runtime
(an ``Add-Type`` DLL in %TEMP% is the kind of thing Smart App Control blocks).
"""

from __future__ import annotations

import ctypes
import os
import sys
import threading
import uuid
from ctypes import wintypes
from typing import List, Optional

_LOCK = threading.Lock()

FOS_NOCHANGEDIR = 0x8
FOS_PICKFOLDERS = 0x20
FOS_FORCEFILESYSTEM = 0x40
FOS_ALLOWMULTISELECT = 0x200
FOS_PATHMUSTEXIST = 0x800
SIGDN_FILESYSPATH = 0x80058000 - (1 << 32)  # as a signed int
ERROR_CANCELLED_HRESULT = 0x800704C7 - (1 << 32)


class DialogUnavailable(RuntimeError):
    """This machine or session cannot show a native dialog (not Windows, no desktop)."""


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def parse(cls, text: str) -> "_GUID":
        value = uuid.UUID(text)
        guid = cls()
        guid.Data1, guid.Data2, guid.Data3 = value.fields[0], value.fields[1], value.fields[2]
        tail = value.bytes[8:]
        for index in range(8):
            guid.Data4[index] = tail[index]
        return guid


CLSID_FILE_OPEN_DIALOG = "DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7"
IID_IFILE_OPEN_DIALOG = "D57C7288-D4AD-4768-BE02-9D969532D960"
IID_ISHELL_ITEM = "43826D1E-E718-42EE-BC55-A1E261C37BFE"


def _method(pointer: ctypes.c_void_p, index: int, restype, *argtypes):
    """Method ``index`` of a COM object's vtable, callable with the object as ``this``."""
    vtable = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    prototype = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
    function = prototype(vtable[index])
    return lambda *args: function(pointer, *args)


def _release(pointer: Optional[ctypes.c_void_p]) -> None:
    if pointer:
        _method(pointer, 2, wintypes.ULONG)()


def _check(hresult: int, what: str) -> None:
    if hresult < 0:
        raise DialogUnavailable(f"{what} failed (0x{hresult & 0xFFFFFFFF:08X})")


def _item_path(item: ctypes.c_void_p) -> str:
    ole32 = ctypes.windll.ole32
    name = ctypes.c_wchar_p()
    _check(_method(item, 5, ctypes.c_long, ctypes.c_int, ctypes.POINTER(ctypes.c_wchar_p))(SIGDN_FILESYSPATH, ctypes.byref(name)),
           "Reading the folder path")
    try:
        return name.value or ""
    finally:
        ole32.CoTaskMemFree(name)


def _pick(title: str, start: str, multiple: bool, owner: int) -> List[str]:
    ole32 = ctypes.windll.ole32
    shell32 = ctypes.windll.shell32
    ole32.CoInitializeEx(None, 0x2)  # apartment-threaded, as the dialog requires
    dialog = ctypes.c_void_p()
    try:
        clsid, iid = _GUID.parse(CLSID_FILE_OPEN_DIALOG), _GUID.parse(IID_IFILE_OPEN_DIALOG)
        _check(ole32.CoCreateInstance(ctypes.byref(clsid), None, 1, ctypes.byref(iid), ctypes.byref(dialog)),
               "Opening the folder picker")
        options = wintypes.DWORD()
        _method(dialog, 10, ctypes.c_long, ctypes.POINTER(wintypes.DWORD))(ctypes.byref(options))
        flags = options.value | FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM | FOS_PATHMUSTEXIST | FOS_NOCHANGEDIR
        if multiple:
            flags |= FOS_ALLOWMULTISELECT
        _method(dialog, 9, ctypes.c_long, wintypes.DWORD)(flags)
        _method(dialog, 17, ctypes.c_long, wintypes.LPCWSTR)(title)
        _method(dialog, 18, ctypes.c_long, wintypes.LPCWSTR)("Open in Nyx" if multiple else "Choose folder")
        if start and os.path.isdir(start):
            item = ctypes.c_void_p()
            shell32.SHCreateItemFromParsingName.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p, ctypes.c_void_p,
                                                            ctypes.POINTER(ctypes.c_void_p)]
            item_iid = _GUID.parse(IID_ISHELL_ITEM)
            if shell32.SHCreateItemFromParsingName(start, None, ctypes.byref(item_iid), ctypes.byref(item)) >= 0:
                _method(dialog, 12, ctypes.c_long, ctypes.c_void_p)(item)
                _release(item)

        # No owner window: owning the browser's window from another process disables it while
        # the picker is open, and a picker that ended up behind something made Nyx look frozen.
        # _present() centres it on the owner's monitor and brings it to the front instead.
        presenter = threading.Thread(target=_present, args=(title, owner), name="nyx-picker-present", daemon=True)
        presenter.start()
        shown = _method(dialog, 3, ctypes.c_long, wintypes.HWND)(None)
        if shown == ERROR_CANCELLED_HRESULT:
            return []
        _check(shown, "Showing the folder picker")

        results = ctypes.c_void_p()
        _check(_method(dialog, 27, ctypes.c_long, ctypes.POINTER(ctypes.c_void_p))(ctypes.byref(results)),
               "Reading the chosen folders")
        try:
            count = wintypes.DWORD()
            _method(results, 7, ctypes.c_long, ctypes.POINTER(wintypes.DWORD))(ctypes.byref(count))
            paths = []
            for index in range(count.value):
                item = ctypes.c_void_p()
                if _method(results, 8, ctypes.c_long, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p))(index, ctypes.byref(item)) < 0:
                    continue
                try:
                    path = _item_path(item)
                    if path:
                        paths.append(path)
                finally:
                    _release(item)
            return paths
        finally:
            _release(results)
    finally:
        _release(dialog)
        ole32.CoUninitialize()


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


def _present(title: str, owner: int, wait: float = 8.0) -> None:
    """Find the picker once it is on screen, centre it on the monitor the owner clicked from, and raise it.

    Measured 2026-09-15: without this the picker opened at (2560, -367) — half off the top of a
    second monitor — and behind the app window.
    """
    import time

    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = wintypes.HWND
    pid = ctypes.windll.kernel32.GetCurrentProcessId()
    deadline = time.monotonic() + wait
    found: List[int] = []
    while not found and time.monotonic() < deadline:
        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def visit(hwnd, _param):
            owner_pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner_pid))
            if owner_pid.value == pid and user32.IsWindowVisible(hwnd):
                buffer = ctypes.create_unicode_buffer(256)
                user32.GetWindowTextW(hwnd, buffer, 256)
                if buffer.value == title:
                    found.append(int(hwnd))
                    return False
            return True

        user32.EnumWindows(visit, 0)
        if not found:
            time.sleep(0.05)
    if not found:
        return
    hwnd = found[0]
    try:
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        width, height = rect.right - rect.left, rect.bottom - rect.top
        user32.MonitorFromWindow.restype = wintypes.HANDLE
        monitor = user32.MonitorFromWindow(wintypes.HWND(owner or hwnd), 2)  # MONITOR_DEFAULTTONEAREST
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        if monitor and user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            work = info.rcWork
            width = min(width, work.right - work.left)
            height = min(height, work.bottom - work.top)
            x = work.left + (work.right - work.left - width) // 2
            y = work.top + (work.bottom - work.top - height) // 2
            user32.SetWindowPos(hwnd, 0, x, y, width, height, 0x0004 | 0x0010)  # NOZORDER | NOACTIVATE

        # Windows only lets the process that owns the foreground hand it over. Borrow the
        # foreground thread's input queue for a moment, as the shell does for its own dialogs.
        foreground = user32.GetForegroundWindow()
        this_thread = ctypes.windll.kernel32.GetCurrentThreadId()
        fg_thread = user32.GetWindowThreadProcessId(foreground, None) if foreground else 0
        dialog_thread = user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), None)
        attached = []
        for thread in {fg_thread, dialog_thread} - {0, this_thread}:
            if user32.AttachThreadInput(this_thread, thread, True):
                attached.append(thread)
        try:
            user32.ShowWindow(hwnd, 5)  # SW_SHOW
            user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002)  # HWND_TOPMOST, NOSIZE | NOMOVE
            user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, 0x0001 | 0x0002)  # back to HWND_NOTOPMOST, still on top
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            if int(user32.GetForegroundWindow() or 0) != hwnd:
                user32.FlashWindow(hwnd, True)  # Windows kept focus elsewhere: at least flash it in the taskbar
        finally:
            for thread in attached:
                user32.AttachThreadInput(this_thread, thread, False)
    except Exception:  # pragma: no cover - presentation is best effort; the picker still works
        pass


def _foreground_owner() -> int:
    """The window the owner just clicked in (the browser or app), so the picker opens on top of it."""
    try:
        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.restype = wintypes.HWND
        return int(user32.GetForegroundWindow() or 0)
    except Exception:  # pragma: no cover
        return 0


def pick_folders(title: str = "Choose folders to open in Nyx", start: str = "", multiple: bool = True,
                 timeout: float = 600.0) -> List[str]:
    """Show the picker and wait for the owner. ``[]`` means they cancelled.

    Runs on its own apartment-threaded thread, one picker at a time. Raises
    :class:`DialogUnavailable` off Windows, or when a picker is already open.
    """
    if sys.platform != "win32":
        raise DialogUnavailable("The folder picker opens on Windows. Type the folder path instead.")
    if not _LOCK.acquire(blocking=False):
        raise DialogUnavailable("A folder picker is already open on this PC — finish or cancel that one first.")
    outcome: dict = {}
    owner = _foreground_owner()

    def run() -> None:
        try:
            outcome["paths"] = _pick(title, start or os.path.expanduser("~"), multiple, owner)
        except Exception as error:  # noqa: BLE001 - reported to the caller below
            outcome["error"] = error

    try:
        worker = threading.Thread(target=run, name="nyx-folder-picker", daemon=True)
        worker.start()
        worker.join(timeout)
        if worker.is_alive():
            raise DialogUnavailable("The folder picker was left open too long; nothing was opened.")
    finally:
        _LOCK.release()
    if "error" in outcome:
        error = outcome["error"]
        raise error if isinstance(error, DialogUnavailable) else DialogUnavailable(str(error))
    return list(outcome.get("paths") or [])
