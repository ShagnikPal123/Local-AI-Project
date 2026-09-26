"""Tools that reach the computer itself — commands, code, files, processes, sound, power.

The owner's words: "It should be able to interact with the machine on every
level. Nothing should be restricted unless the user asks for it."

So every tool here works by default, and every one is held to the owner's
permission setting for its category (``permissions.py``) by the tool registry —
set "shell" to *ask* and each command pauses for approval in the chat; set it to
*block* and Nyx says it is blocked. Every call shows in the step timeline with a
readable label, so nothing happens out of sight.

Two protections that are not restrictions on the owner:

* credential files on the protected list are not read or overwritten, so API
  keys never end up in a model provider's logs (the owner can edit the list);
* deletes go to the Recycle Bin unless ``permanent=true`` — recoverable by default.

Every subprocess has a timeout and no console window, and long output is cut
with a note rather than flooding the model's context.
"""

from __future__ import annotations

import base64
import fnmatch
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_MAX_OUTPUT = 12_000
_MAX_TIMEOUT = 900


def _progress(text: str) -> None:
    try:
        from tool_context import progress

        progress(text)
    except Exception:
        pass


def _clip(text: str, limit: int = _MAX_OUTPUT) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    head = text[: limit // 2]
    tail = text[-limit // 2:]
    return f"{head}\n… [{len(text) - limit:,} characters omitted] …\n{tail}"


def _protected(path: Path) -> bool:
    try:
        from permissions import is_protected_path

        return is_protected_path(str(path))
    except Exception:
        return False


def _resolve(path: str) -> Path:
    raw = os.path.expandvars(os.path.expanduser((path or "").strip().strip('"')))
    return Path(raw).resolve()


def _timeout(value: Any, default: int = 120) -> int:
    try:
        return max(1, min(int(value), _MAX_TIMEOUT))
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Commands and code
# ---------------------------------------------------------------------------


def run_command(command: str, shell: str = "powershell", cwd: str = "", timeout_seconds: int = 30) -> str:
    """Run a PowerShell or Command Prompt command and return its output."""
    text = (command or "").strip()
    if not text:
        return "Error: no command given."
    # Reject interactive editors and GUI launchers that would hang
    lowered = text.lower()
    blocked = ["vim", "nano", "less", "more", "vi", "emacs", "gedit", "notepad++", "code", "subl", "start "
               "explorer", "open ", "xdg-open"]
    for b in blocked:
        if b in lowered:
            return f"Error: command contains blocked interactive/GUI launcher '{b}'. Use non-interactive tools."
    import self_guard

    refusal = self_guard.check_command(text)
    if refusal:
        return refusal
    kind = (shell or "powershell").strip().lower()
    if kind in ("pwsh", "ps", "powershell"):
        argv = ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", text]
    elif kind in ("cmd", "command prompt"):
        argv = ["cmd", "/d", "/s", "/c", text]
    else:
        return f"Error: unknown shell {shell!r}; use powershell or cmd."
    workdir = _resolve(cwd) if cwd else Path.home()
    if not workdir.is_dir():
        return f"Error: working folder not found: {workdir}"
    limit = _timeout(timeout_seconds)
    _progress(f"Running in {kind}: {text[:80]}")
    started = time.perf_counter()
    try:
        result = subprocess.run(argv, cwd=str(workdir), capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=limit, creationflags=_NO_WINDOW)
    except subprocess.TimeoutExpired as expired:
        partial = (expired.stdout or "") if isinstance(expired.stdout, str) else ""
        return f"Timed out after {limit}s.\n{_clip(partial)}"
    except OSError as error:
        return f"Error: could not start {kind}: {error}"
    seconds = time.perf_counter() - started
    parts = [f"Exit code {result.returncode} ({seconds:.1f}s, in {workdir})"]
    if result.stdout.strip():
        parts.append("Output:\n" + _clip(result.stdout.rstrip()))
    if result.stderr.strip():
        parts.append("Errors:\n" + _clip(result.stderr.rstrip(), 4000))
    if len(parts) == 1:
        parts.append("(no output)")
    return "\n".join(parts)


def run_python(code: str, timeout_seconds: int = 120) -> str:
    """Run Python code in a separate process with Nyx's interpreter and packages."""
    source = code or ""
    if not source.strip():
        return "Error: no code given."
    if getattr(sys, "frozen", False):
        return "Error: this packaged build has no separate Python interpreter to run code with."
    import self_guard

    refusal = self_guard.check_command(source)
    if refusal:
        return refusal
    scratch = Path(os.getenv("TEMP") or Path.home()) / "nyx_python"
    scratch.mkdir(parents=True, exist_ok=True)
    script = scratch / f"snippet_{int(time.time() * 1000)}.py"
    script.write_text(source, encoding="utf-8")
    limit = _timeout(timeout_seconds)
    _progress(f"Running Python ({len(source.splitlines())} lines)")
    try:
        result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=limit, cwd=str(scratch), creationflags=_NO_WINDOW)
    except subprocess.TimeoutExpired:
        return f"Timed out after {limit}s."
    finally:
        try:
            script.unlink()
        except OSError:
            pass
    parts = [f"Exit code {result.returncode}"]
    if result.stdout.strip():
        parts.append("Output:\n" + _clip(result.stdout.rstrip()))
    if result.stderr.strip():
        parts.append("Errors:\n" + _clip(result.stderr.rstrip(), 6000))
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------


def write_file(path: str, content: str, append: bool = False) -> str:
    target = _resolve(path)
    if _protected(target):
        return f"Blocked: {target.name} is a protected credential file."
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a" if append else "w", encoding="utf-8", newline="") as handle:
            handle.write(content or "")
    except OSError as error:
        return f"Error: {error}"
    return f"{'Appended to' if append else 'Wrote'} {target} ({target.stat().st_size:,} bytes)."


def make_folder(path: str) -> str:
    target = _resolve(path)
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        return f"Error: {error}"
    return f"Folder ready: {target}"


def _copy_or_move(source: str, destination: str, move: bool) -> str:
    src, dst = _resolve(source), _resolve(destination)
    if not src.exists():
        return f"Error: {src} does not exist."
    if _protected(src) or _protected(dst):
        return "Blocked: a protected credential file is involved."
    if dst.is_dir():
        dst = dst / src.name
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if move:
            shutil.move(str(src), str(dst))
        elif src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)
    except (OSError, shutil.Error) as error:
        return f"Error: {error}"
    return f"{'Moved' if move else 'Copied'} {src} → {dst}"


def move_path(source: str, destination: str) -> str:
    return _copy_or_move(source, destination, move=True)


def copy_path(source: str, destination: str) -> str:
    return _copy_or_move(source, destination, move=False)


def delete_path(path: str, permanent: bool = False) -> str:
    """Delete a file or folder — to the Recycle Bin unless permanent is true."""
    target = _resolve(path)
    if not target.exists():
        return f"Error: {target} does not exist."
    if _protected(target):
        return f"Blocked: {target.name} is a protected credential file."
    if target == Path(target.anchor) or target == Path.home():
        return f"Refused: {target} is a drive root or your whole user folder."
    if not permanent and sys.platform == "win32":
        method = "DeleteDirectory" if target.is_dir() else "DeleteFile"
        script = (
            "Add-Type -AssemblyName Microsoft.VisualBasic; "
            f"[Microsoft.VisualBasic.FileIO.FileSystem]::{method}($env:NYX_TARGET, "
            "'OnlyErrorDialogs', 'SendToRecycleBin')"
        )
        result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                                capture_output=True, text=True, timeout=60, creationflags=_NO_WINDOW,
                                env={**os.environ, "NYX_TARGET": str(target)})
        if result.returncode == 0 and not target.exists():
            return f"Moved {target} to the Recycle Bin."
        return f"Error: could not recycle {target}: {result.stderr.strip()[:300]}"
    try:
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
    except OSError as error:
        return f"Error: {error}"
    return f"Permanently deleted {target}."


def search_files(query: str, root: str = "", limit: int = 50) -> str:
    """Find files by name (wildcards allowed) under a folder, newest first."""
    pattern = (query or "").strip()
    if not pattern:
        return "Error: give part of a file name, or a wildcard like *.pdf."
    if not any(ch in pattern for ch in "*?"):
        pattern = f"*{pattern}*"
    base = _resolve(root) if root else Path.home()
    if not base.is_dir():
        return f"Error: folder not found: {base}"
    skip = {".git", "node_modules", ".venv", "venv", "__pycache__", "AppData", "$Recycle.Bin"}
    found: List[Path] = []
    scanned = 0
    deadline = time.monotonic() + 20
    for folder, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in skip and not d.startswith(".")]
        for name in files:
            scanned += 1
            if fnmatch.fnmatch(name.lower(), pattern.lower()):
                found.append(Path(folder) / name)
        if len(found) >= limit * 4 or time.monotonic() > deadline:
            break
    found.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    lines = [f"{len(found)} match(es) for {pattern} under {base} ({scanned:,} files checked):"]
    for item in found[: max(1, min(int(limit or 50), 200))]:
        try:
            stat = item.stat()
            lines.append(f"- {item}  ({stat.st_size:,} bytes, modified {time.strftime('%Y-%m-%d %H:%M', time.localtime(stat.st_mtime))})")
        except OSError:
            lines.append(f"- {item}")
    return "\n".join(lines)


def file_info(path: str) -> str:
    target = _resolve(path)
    if not target.exists():
        return f"Error: {target} does not exist."
    stat = target.stat()
    kind = "folder" if target.is_dir() else "file"
    extra = ""
    if target.is_dir():
        try:
            children = list(target.iterdir())
            extra = f", {len(children)} item(s) inside"
        except OSError:
            pass
    return (f"{target} — {kind}, {stat.st_size:,} bytes{extra}, modified "
            f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(stat.st_mtime))}, created "
            f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(stat.st_ctime))}")


def list_drives() -> str:
    try:
        import psutil

        lines = []
        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
                lines.append(f"- {part.mountpoint} ({part.fstype or '?'}): {usage.free / 1e9:.1f} GB free of "
                             f"{usage.total / 1e9:.1f} GB")
            except OSError:
                lines.append(f"- {part.mountpoint} (not ready)")
        return "Drives:\n" + "\n".join(lines)
    except ImportError:
        return "Drives: " + ", ".join(f"{d}:\\" for d in "CDEFGHIJ" if Path(f"{d}:\\").exists())


def download_file(url: str, path: str = "") -> str:
    import requests

    link = (url or "").strip()
    if not link.lower().startswith(("http://", "https://")):
        return "Error: give an http or https link."
    name = link.split("?")[0].rstrip("/").split("/")[-1] or "download"
    target = _resolve(path) if path else Path.home() / "Downloads" / name
    if target.is_dir():
        target = target / name
    if _protected(target):
        return "Blocked: that destination is a protected credential file."
    try:
        with requests.get(link, stream=True, timeout=60, headers={"User-Agent": "NyxIchos/1.0"}) as response:
            response.raise_for_status()
            total = int(response.headers.get("content-length") or 0)
            target.parent.mkdir(parents=True, exist_ok=True)
            written = 0
            last = time.monotonic()
            with target.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=256 * 1024):
                    handle.write(chunk)
                    written += len(chunk)
                    if time.monotonic() - last > 1.5:
                        last = time.monotonic()
                        _progress(f"Downloaded {written / 1e6:.1f} MB" + (f" of {total / 1e6:.1f} MB" if total else ""))
    except Exception as error:  # noqa: BLE001 - reported to the model
        return f"Error: download failed: {error}"
    # Anything off the internet is checked where it landed, Windows Security
    # included. A bad download is removed again — it was never the owner's file.
    try:
        import file_guard

        verdict = file_guard.check_file(target, source=f"download from {link[:80]}")
    except Exception:  # noqa: BLE001 - a broken checker must not lose the download
        verdict = None
    if verdict is not None and verdict.blocked:
        try:
            target.unlink()
        except OSError:
            pass
        return f"Blocked and deleted: {verdict.message}"
    warning = f" Note: {' '.join(verdict.cautions)}." if verdict is not None and verdict.cautions else ""
    return f"Saved {target} ({written:,} bytes).{warning}"


def view_image(path: str) -> str:
    """Show a local picture to the model (resized), and to the chat timeline."""
    target = _resolve(path)
    if not target.is_file():
        return f"Error: {target} is not a file."
    if _protected(target):
        return "Blocked: protected file."
    try:
        import uploads
        from tool_context import attach_image

        data = target.read_bytes()
        mime = uploads._guess_mime(target.name, "")
        if not mime.startswith("image/"):
            return f"Error: {target.name} is not an image. Use read_document for files."
        prepared, prepared_mime = uploads.prepare_image(data, mime, max_edge=1600)
        shown = attach_image(prepared, prepared_mime, name=target.name)
    except Exception as error:  # noqa: BLE001
        return f"Error: {error}"
    return (f"Showing {target.name} to you now — look at it in your next step." if shown
            else f"{target.name} could not be attached here; use analyze_image to have the image-check model describe it.")


# ---------------------------------------------------------------------------
# Processes, apps, system
# ---------------------------------------------------------------------------


def list_processes(sort: str = "memory", limit: int = 25) -> str:
    try:
        import psutil
    except ImportError:
        return run_command("Get-Process | Sort-Object WS -Descending | Select-Object -First 25 Id,ProcessName,CPU,WS")
    rows = []
    for proc in psutil.process_iter(["pid", "name", "memory_info", "cpu_percent"]):
        try:
            info = proc.info
            rows.append((info["pid"], info["name"] or "?", (info["memory_info"].rss if info["memory_info"] else 0),
                         info["cpu_percent"] or 0.0))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    key = (lambda r: r[3]) if str(sort).lower().startswith("cpu") else (lambda r: r[2])
    rows.sort(key=key, reverse=True)
    lines = [f"{len(rows)} processes; top {min(len(rows), int(limit or 25))} by {sort}:"]
    for pid, name, rss, cpu in rows[: max(1, min(int(limit or 25), 200))]:
        lines.append(f"- {name} (pid {pid}): {rss / 1e6:.0f} MB, CPU {cpu:.0f}%")
    return "\n".join(lines)


def kill_process(target: str) -> str:
    """End a process by pid or by name (all processes with that name)."""
    try:
        import psutil
    except ImportError:
        return "Error: psutil is not installed."
    value = str(target or "").strip()
    if not value:
        return "Error: give a pid or a process name."
    victims = []
    if value.isdigit():
        try:
            victims = [psutil.Process(int(value))]
        except psutil.NoSuchProcess:
            return f"No process with pid {value}."
    else:
        wanted = value.lower().removesuffix(".exe")
        victims = [p for p in psutil.process_iter(["name"]) if (p.info["name"] or "").lower().removesuffix(".exe") == wanted]
    import self_guard

    own = self_guard.own_pids()
    hosts = self_guard.hosting_process_names()
    ended, refused = [], []
    for proc in victims:
        try:
            name = proc.name()
            refusal = self_guard.check_kill(proc.pid, name, hosts=hosts, pids=own)
            if refusal:
                refused.append(refusal)
                continue
            proc.terminate()
            ended.append(f"{name} ({proc.pid})")
        except (psutil.NoSuchProcess, psutil.AccessDenied) as error:
            ended.append(f"{proc.pid}: {error.__class__.__name__}")
    if refused and not ended:
        return refused[0]
    note = f" (left {len(refused)} alone: {refused[0]})" if refused else ""
    return (f"Ended: {', '.join(ended)}{note}" if ended else f"No running process matched {value!r}.")


def _key_tap(vk: int) -> None:
    import ctypes

    user32 = ctypes.windll.user32
    user32.keybd_event(vk, 0, 0, 0)
    user32.keybd_event(vk, 0, 2, 0)


def set_volume(percent: int = -1, mute: str = "") -> str:
    """Set the master volume (0–100) and/or mute ("on", "off", "toggle")."""
    if sys.platform != "win32":
        return "Error: volume control is implemented for Windows."
    try:
        level = int(percent)
    except (TypeError, ValueError):
        level = -1
    script = r"""
$code = @'
using System.Runtime.InteropServices;
[Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IAudioEndpointVolume { int f(); int g(); int h(); int i();
  int SetMasterVolumeLevelScalar(float fLevel, System.Guid pguidEventContext); int j();
  int GetMasterVolumeLevelScalar(out float pfLevel); int k(); int l(); int m(); int n();
  int SetMute([MarshalAs(UnmanagedType.Bool)] bool bMute, System.Guid pguidEventContext);
  int GetMute(out bool pbMute); }
[Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDevice { int Activate(ref System.Guid id, int clsCtx, int activationParams, out IAudioEndpointVolume aev); }
[Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDeviceEnumerator { int f(); int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice endpoint); }
[ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")] class MMDeviceEnumeratorComObject { }
public class NyxAudio {
  static IAudioEndpointVolume Vol() { var e = new MMDeviceEnumeratorComObject() as IMMDeviceEnumerator; IMMDevice d = null;
    Marshal.ThrowExceptionForHR(e.GetDefaultAudioEndpoint(0, 1, out d)); IAudioEndpointVolume v = null;
    var id = typeof(IAudioEndpointVolume).GUID; Marshal.ThrowExceptionForHR(d.Activate(ref id, 23, 0, out v)); return v; }
  public static float Get() { float l = 0; Marshal.ThrowExceptionForHR(Vol().GetMasterVolumeLevelScalar(out l)); return l; }
  public static void Set(float l) { Marshal.ThrowExceptionForHR(Vol().SetMasterVolumeLevelScalar(l, System.Guid.Empty)); }
  public static bool Muted() { bool m; Marshal.ThrowExceptionForHR(Vol().GetMute(out m)); return m; }
  public static void Mute(bool m) { Marshal.ThrowExceptionForHR(Vol().SetMute(m, System.Guid.Empty)); }
}
'@
Add-Type -TypeDefinition $code
$level = [int]$env:NYX_LEVEL; $mute = $env:NYX_MUTE
if ($level -ge 0) { [NyxAudio]::Set([Math]::Min(100, $level) / 100.0) }
if ($mute -eq 'on') { [NyxAudio]::Mute($true) } elseif ($mute -eq 'off') { [NyxAudio]::Mute($false) } elseif ($mute -eq 'toggle') { [NyxAudio]::Mute(-not [NyxAudio]::Muted()) }
Write-Output ("{0}|{1}" -f [Math]::Round([NyxAudio]::Get() * 100), [NyxAudio]::Muted())
"""
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True,
                            text=True, timeout=30, creationflags=_NO_WINDOW,
                            env={**os.environ, "NYX_LEVEL": str(level), "NYX_MUTE": (mute or "").lower()})
    out = (result.stdout or "").strip().splitlines()
    if result.returncode != 0 or not out or "|" not in out[-1]:
        return f"Error: could not change the volume: {(result.stderr or '').strip()[:300]}"
    now, muted = out[-1].split("|", 1)
    return f"Volume is {now}%{' (muted)' if muted.strip().lower() == 'true' else ''}."


_MEDIA_KEYS = {"play_pause": 0xB3, "next": 0xB0, "previous": 0xB1, "stop": 0xB2,
               "volume_up": 0xAF, "volume_down": 0xAE, "mute": 0xAD}


def media_key(key: str) -> str:
    name = (key or "").strip().lower().replace(" ", "_").replace("-", "_")
    name = {"play": "play_pause", "pause": "play_pause", "prev": "previous", "back": "previous", "skip": "next"}.get(name, name)
    if name not in _MEDIA_KEYS:
        return f"Error: use one of {', '.join(_MEDIA_KEYS)}."
    if sys.platform != "win32":
        return "Error: media keys are implemented for Windows."
    _key_tap(_MEDIA_KEYS[name])
    return f"Pressed {name.replace('_', ' ')}."


def lock_screen() -> str:
    if sys.platform != "win32":
        return "Error: locking is implemented for Windows."
    import ctypes

    ok = ctypes.windll.user32.LockWorkStation()
    return "Locked the screen." if ok else "Error: Windows refused to lock the screen."


def system_power(action: str, delay_seconds: int = 30) -> str:
    """sleep, restart, shutdown, or cancel a pending restart/shutdown."""
    choice = (action or "").strip().lower()
    delay = max(0, min(int(delay_seconds or 0), 3600))
    commands = {
        "restart": ["shutdown", "/r", "/t", str(delay)],
        "shutdown": ["shutdown", "/s", "/t", str(delay)],
        "cancel": ["shutdown", "/a"],
        "sleep": ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
    }
    if choice not in commands:
        return "Error: action must be sleep, restart, shutdown, or cancel."
    try:
        subprocess.run(commands[choice], capture_output=True, timeout=20, creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as error:
        return f"Error: {error}"
    if choice in ("restart", "shutdown"):
        return f"Windows will {choice} in {delay} seconds. Say 'cancel the {choice}' to stop it."
    return {"cancel": "Cancelled the pending restart/shutdown.", "sleep": "Putting the computer to sleep."}[choice]


def notify(title: str, message: str) -> str:
    """Show a Windows notification (toast)."""
    if sys.platform != "win32":
        return "Error: notifications are implemented for Windows."
    script = r"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$t = [System.Security.SecurityElement]::Escape($env:NYX_TITLE); $m = [System.Security.SecurityElement]::Escape($env:NYX_MESSAGE)
$xml.LoadXml("<toast><visual><binding template='ToastGeneric'><text>$t</text><text>$m</text></binding></visual></toast>")
$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show([Windows.UI.Notifications.ToastNotification]::new($xml))
"""
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True,
                            text=True, timeout=30, creationflags=_NO_WINDOW,
                            env={**os.environ, "NYX_TITLE": (title or "Nyx")[:120], "NYX_MESSAGE": (message or "")[:400]})
    return "Notification shown." if result.returncode == 0 else f"Error: {(result.stderr or '').strip()[:300]}"


def clipboard_get() -> str:
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", "Get-Clipboard -Raw"],
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
                            creationflags=_NO_WINDOW)
    text = (result.stdout or "").rstrip("\r\n")
    return f"Clipboard ({len(text)} characters):\n{_clip(text, 8000)}" if text else "The clipboard is empty (or holds no text)."


def clipboard_set(text: str) -> str:
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                             "Set-Clipboard -Value $env:NYX_CLIP"], capture_output=True, text=True, timeout=15,
                            creationflags=_NO_WINDOW, env={**os.environ, "NYX_CLIP": text or ""})
    return f"Copied {len(text or '')} characters to the clipboard." if result.returncode == 0 else \
        f"Error: {(result.stderr or '').strip()[:200]}"


def open_path(path: str) -> str:
    """Open a file, folder or program with its default app."""
    target = os.path.expandvars(os.path.expanduser((path or "").strip().strip('"')))
    if not target:
        return "Error: nothing to open."
    try:
        os.startfile(target)  # type: ignore[attr-defined]
    except (OSError, AttributeError) as error:
        return f"Error: could not open {target}: {error}"
    return f"Opened {target}."


def open_app(name: str) -> str:
    """Start an installed app by name (Start Menu search) or by path."""
    wanted = (name or "").strip()
    if not wanted:
        return "Error: say which app."
    if Path(os.path.expandvars(wanted)).exists():
        return open_path(wanted)
    script = (
        "$n = $env:NYX_APP; $app = Get-StartApps | Where-Object { $_.Name -like \"*$n*\" } | Select-Object -First 1; "
        "if ($app) { Start-Process \"shell:AppsFolder\\$($app.AppID)\"; Write-Output $app.Name } "
        "else { try { Start-Process $n -ErrorAction Stop; Write-Output $n } catch { exit 3 } }"
    )
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True,
                            text=True, timeout=30, creationflags=_NO_WINDOW, env={**os.environ, "NYX_APP": wanted})
    if result.returncode == 0 and result.stdout.strip():
        return f"Started {result.stdout.strip().splitlines()[-1]}."
    return f"Error: no installed app matched {wanted!r}."


def open_url(url: str) -> str:
    import webbrowser

    link = (url or "").strip()
    if not link.lower().startswith(("http://", "https://", "mailto:")):
        link = "https://" + link
    webbrowser.open(link)
    return f"Opened {link} in the default browser."


def get_environment() -> str:
    """Who and where: user, folders, OS, screen — so paths are right the first time."""
    home = Path.home()
    folders = {name: str(home / name) for name in ("Desktop", "Documents", "Downloads", "Pictures", "Music", "Videos")}
    try:
        result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                                 "[Environment]::GetFolderPath('Desktop'); [Environment]::GetFolderPath('MyDocuments')"],
                                capture_output=True, text=True, timeout=15, creationflags=_NO_WINDOW)
        lines = (result.stdout or "").strip().splitlines()
        if len(lines) >= 2:
            folders["Desktop"], folders["Documents"] = lines[0], lines[1]
    except (OSError, subprocess.SubprocessError):
        pass
    import platform

    data: Dict[str, Any] = {
        "user": os.getenv("USERNAME") or home.name,
        "computer": platform.node(),
        "os": f"{platform.system()} {platform.release()} (build {platform.version()})",
        "home": str(home),
        "folders": folders,
        "shell": "PowerShell",
        "python": sys.version.split()[0],
        "cwd": os.getcwd(),
    }
    return json.dumps(data, indent=2)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_machine_tools(registry: Any) -> None:
    from tools import ToolParam as P

    def reg(name, description, params, handler, category, label):
        registry.register(name, description, params, handler, category=category, label=label)

    reg("run_command", "Run a PowerShell (default) or Command Prompt command on this PC and get its output. "
        "Use for anything the other tools do not cover: installing software, git, system settings, scripts.",
        [P("command", "string", "The command to run"),
         P("shell", "string", "powershell or cmd", required=False, enum_values=["powershell", "cmd"]),
         P("cwd", "string", "Working folder (default: your user folder)", required=False),
         P("timeout_seconds", "number", "Give up after this many seconds (default 120, max 900)", required=False)],
        run_command, "shell", lambda a: f"Running: {str(a.get('command', ''))[:70]}")
    reg("run_python", "Write and run Python code (Nyx's Python, with numpy, requests, Pillow, pypdf available).",
        [P("code", "string", "The Python source to run"),
         P("timeout_seconds", "number", "Default 120", required=False)],
        run_python, "code", lambda a: f"Running Python ({len(str(a.get('code', '')).splitlines())} lines)")
    reg("write_file", "Create or overwrite a text file (or append to it).",
        [P("path", "string", "Full path"), P("content", "string", "Text to write"),
         P("append", "boolean", "Add to the end instead of replacing", required=False)],
        write_file, "files.write", lambda a: f"Writing {str(a.get('path', ''))[:70]}")
    reg("make_folder", "Create a folder (and any missing parents).", [P("path", "string", "Folder path")],
        make_folder, "files.write", lambda a: f"Creating folder {str(a.get('path', ''))[:60]}")
    reg("move_path", "Move or rename a file or folder.",
        [P("source", "string", "What to move"), P("destination", "string", "Where to (folder or new name)")],
        move_path, "files.write", lambda a: f"Moving {Path(str(a.get('source', ''))).name}")
    reg("copy_path", "Copy a file or folder.",
        [P("source", "string", "What to copy"), P("destination", "string", "Where to")],
        copy_path, "files.write", lambda a: f"Copying {Path(str(a.get('source', ''))).name}")
    reg("delete_path", "Delete a file or folder. Goes to the Recycle Bin unless permanent is true.",
        [P("path", "string", "What to delete"),
         P("permanent", "boolean", "Skip the Recycle Bin (only when the user asks)", required=False)],
        delete_path, "files.delete", lambda a: f"Deleting {str(a.get('path', ''))[:60]}")
    reg("search_files", "Find files by name or wildcard (e.g. *.pdf, invoice) under a folder, newest first.",
        [P("query", "string", "Part of the name or a wildcard"),
         P("root", "string", "Folder to search (default: your user folder)", required=False),
         P("limit", "number", "Max results (default 50)", required=False)],
        search_files, "files.read", lambda a: f"Searching for {str(a.get('query', ''))[:50]}")
    reg("file_info", "Size, dates and type of a file or folder.", [P("path", "string", "Path")],
        file_info, "files.read", lambda a: f"Inspecting {Path(str(a.get('path', ''))).name}")
    reg("list_drives", "Drives on this PC with free space.", [], list_drives, "files.read", "Listing drives")
    reg("download_file", "Download a file from the web to this PC (default: Downloads).",
        [P("url", "string", "http(s) link"), P("path", "string", "Destination file or folder", required=False)],
        download_file, "network", lambda a: f"Downloading {str(a.get('url', ''))[:60]}")
    reg("view_image", "Look at a picture on this PC yourself (it is attached to your next step).",
        [P("path", "string", "Full path to the image")], view_image, "files.read",
        lambda a: f"Looking at {Path(str(a.get('path', ''))).name}")
    reg("list_processes", "Running programs, sorted by memory or cpu.",
        [P("sort", "string", "memory or cpu", required=False, enum_values=["memory", "cpu"]),
         P("limit", "number", "How many (default 25)", required=False)],
        list_processes, "general", "Listing running programs")
    reg("kill_process", "End a running program by pid or name (e.g. notepad).", [P("target", "string", "pid or name")],
        kill_process, "system", lambda a: f"Ending {a.get('target', '')}")
    reg("set_volume", "Set the speaker volume (0-100) and/or mute on/off/toggle.",
        [P("percent", "number", "0-100 (omit to leave as is)", required=False),
         P("mute", "string", "on, off or toggle", required=False, enum_values=["on", "off", "toggle"])],
        set_volume, "system", lambda a: "Changing the volume")
    reg("media_key", "Press a media key: play_pause, next, previous, stop, volume_up, volume_down, mute.",
        [P("key", "string", "Which key")], media_key, "system", lambda a: f"Pressing {a.get('key', '')}")
    reg("lock_screen", "Lock the computer.", [], lock_screen, "system", "Locking the screen")
    reg("system_power", "Sleep, restart or shut down the PC (with a delay), or cancel a pending restart/shutdown.",
        [P("action", "string", "sleep, restart, shutdown or cancel", enum_values=["sleep", "restart", "shutdown", "cancel"]),
         P("delay_seconds", "number", "Delay before restart/shutdown (default 30)", required=False)],
        system_power, "system", lambda a: f"Power: {a.get('action', '')}")
    reg("notify", "Show a Windows notification.",
        [P("title", "string", "Title"), P("message", "string", "Text")], notify, "apps", "Showing a notification")
    reg("clipboard_get", "Read the text on the clipboard.", [], clipboard_get, "clipboard", "Reading the clipboard")
    reg("clipboard_set", "Put text on the clipboard.", [P("text", "string", "Text to copy")], clipboard_set,
        "clipboard", "Copying to the clipboard")
    reg("open_path", "Open a file, folder or program with its default app.", [P("path", "string", "Path")],
        open_path, "apps", lambda a: f"Opening {Path(str(a.get('path', ''))).name}")
    reg("open_app", "Start an installed app by name (e.g. Spotify, Word, Calculator).", [P("name", "string", "App name")],
        open_app, "apps", lambda a: f"Starting {a.get('name', '')}")
    reg("open_url", "Open a web page in the default browser.", [P("url", "string", "Link")], open_url, "web",
        lambda a: f"Opening {str(a.get('url', ''))[:60]}")
    reg("get_environment", "The user's name, folders (Desktop, Documents, Downloads…), OS and shell — check before "
        "building paths.", [], get_environment, "general", "Checking this PC's folders")
