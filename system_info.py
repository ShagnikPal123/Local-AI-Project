"""Accurate system specifications and live readings (OVERHAUL_CONTRACTS.md §4.1).

The owner's complaint was specific: the web UI showed the wrong PC details,
because ``device_profile.py`` names the CPU via ``platform.processor()`` which
on Windows reports the *architecture string* ("AMD64 Family 26 Model 36…"),
not the product name. Everything here reports a real, sourced value or an
explicit ``None`` — unknown fields are ``null`` in JSON, never guessed.

Two layers:

* :func:`collect_specs` — the machine's identity: OS, device, CPU, memory
  modules, GPUs, disks, volumes, displays, network, battery. Expensive parts
  (a PowerShell CIM query for names CIM cannot see) are cached on disk until
  ``refresh=True``.
* :func:`collect_live` — the machine right now: per-core CPU, memory, GPU
  telemetry via the existing hardware_safety monitor, disk/network rates
  (computed between two psutil samples), battery, top processes.

psutil is a hard requirement (pinned in requirements.txt); the CIM subprocess
is only used where psutil cannot see (product names), and every subprocess has
a timeout. Tests mock the OS boundary — this module never runs in a test.
"""

from __future__ import annotations

import ctypes
import json
import logging
import platform
import struct
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from paths import data_path

_LOG = logging.getLogger("nyx.system_info")

#: The cached "identity" half. Refreshed only on request; it changes rarely.
_SPECS_CACHE = data_path("system/specs_cache.json")
_SPECS_CACHE_TTL = 6 * 3600.0

_CIM_TIMEOUT = 8


def _round(value: Any, digits: int = 2) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return round(number, digits)


def _cim_query(namespace_class: str, properties: List[str]) -> List[Dict[str, str]]:
    """One PowerShell Get-CimInstance call, parsed as JSON. Never raises.

    Used only for facts psutil cannot report (device product names, memory
    part numbers, monitor names). A missing PowerShell or a slow WMI service
    costs an empty list, not a failure — the fields simply stay null.
    """
    select = ", ".join(properties)
    script = (
        f"Get-CimInstance -ClassName {namespace_class} | "
        f"Select-Object {select} | ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=_CIM_TIMEOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        _LOG.debug("CIM query for %s failed: %s", namespace_class, error)
        return []
    if result.returncode != 0 or not result.stdout.strip():
        return []
    try:
        parsed = json.loads(result.stdout)
    except ValueError:
        return []
    if isinstance(parsed, dict):
        return [parsed]
    return parsed if isinstance(parsed, list) else []


# ---------------------------------------------------------------------------
# Specs (identity, cached)
# ---------------------------------------------------------------------------


def collect_specs(refresh: bool = False) -> Dict[str, Any]:
    """The machine's identity. Cached on disk; ``refresh`` forces a rescan."""
    if not refresh:
        cached = _load_specs_cache()
        if cached is not None:
            return cached

    specs: Dict[str, Any] = {
        "os": _os_specs(),
        "device": _device_specs(),
        "cpu": _cpu_specs(),
        "memory": _memory_specs(),
        "gpus": _gpu_specs(),
        "disks": _disk_specs(),
        "volumes": _volume_specs(),
        "displays": _display_specs(),
        "network": _network_specs(),
        "battery": _battery_specs(),
    }
    specs["collected_at"] = time.time()
    _save_specs_cache(specs)
    return specs


def _load_specs_cache() -> Optional[Dict[str, Any]]:
    try:
        raw = json.loads(Path(_SPECS_CACHE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    collected = raw.get("collected_at", 0)
    if time.time() - collected > _SPECS_CACHE_TTL:
        return None
    return raw


def _save_specs_cache(specs: Dict[str, Any]) -> None:
    try:
        Path(_SPECS_CACHE).parent.mkdir(parents=True, exist_ok=True)
        Path(_SPECS_CACHE).write_text(json.dumps(specs, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _os_specs() -> Dict[str, Any]:
    import psutil

    release, version = platform.system(), platform.release()
    build = platform.version() or None
    try:
        boot = psutil.boot_time()
        uptime = time.time() - boot if boot else None
    except Exception:  # noqa: BLE001
        uptime = None
    return {
        "name": f"{release} {version}".strip() or platform.system() or None,
        "version": version or None,
        "build": build,
        "arch": platform.machine() or None,
        "hostname": platform.node() or None,
        "user": _current_user(),
        "uptime_seconds": _round(uptime, 0),
    }


def _current_user() -> Optional[str]:
    try:
        import getpass

        return getpass.getuser() or None
    except Exception:  # noqa: BLE001
        return None


def _device_specs() -> Dict[str, Any]:
    """Manufacturer/model/bios/motherboard from Win32 CIM (nulls elsewhere)."""
    if platform.system() != "Windows":
        return {"manufacturer": None, "model": None, "bios": None, "motherboard": None}
    rows = _cim_query("Win32_ComputerSystem", ["Manufacturer", "Model"])
    bios = _cim_query("Win32_BIOS", ["SMBIOSBIOSVersion", "Manufacturer"])
    board = _cim_query("Win32_BaseBoard", ["Manufacturer", "Product"])
    return {
        "manufacturer": rows[0].get("Manufacturer") or None if rows else None,
        "model": rows[0].get("Model") or None if rows else None,
        "bios": (bios[0].get("SMBIOSBIOSVersion") or None) if bios else None,
        "motherboard": (
            f"{board[0].get('Manufacturer', '')} {board[0].get('Product', '')}".strip() or None
        ) if board else None,
    }


def _cpu_specs() -> Dict[str, Any]:
    """The real product name — the exact detail platform.processor() gets wrong."""
    import psutil

    name = _cpu_product_name()
    freq = None
    try:
        raw = psutil.cpu_freq()
        # Windows reports WMI's fixed base speed as both current and max — not a max.
        if raw is not None and not (platform.system() == "Windows" and raw.max == raw.current):
            freq = _round(raw.max or raw.current, 0)
    except Exception:  # noqa: BLE001
        freq = None
    return {
        "name": name,
        "vendor": _cpu_vendor(name),
        "cores": psutil.cpu_count(logical=False) or None,
        "threads": psutil.cpu_count(logical=True) or None,
        "max_mhz": freq,
    }


def _cpu_product_name() -> Optional[str]:
    if platform.system() == "Windows":
        rows = _cim_query("Win32_Processor", ["Name"])
        if rows and rows[0].get("Name", "").strip():
            return rows[0]["Name"].strip()
        # Registry fallback: the same string without a WMI round trip.
        try:
            result = subprocess.run(
                ["reg", "query", r"HKLM\HARDWARE\DESCRIPTION\System\CentralProcessor\0", "/v", "ProcessorNameString"],
                capture_output=True, text=True, timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            for line in result.stdout.splitlines():
                if "ProcessorNameString" in line and "REG_SZ" in line:
                    value = line.split("REG_SZ", 1)[1].strip()
                    if value:
                        return value
        except (OSError, subprocess.TimeoutExpired):
            pass
        return None
    # Linux/macOS: /proc/cpuinfo or sysctl.
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("model name") and ":" in line:
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return None


def _cpu_vendor(name: Optional[str]) -> Optional[str]:
    lowered = (name or "").lower()
    if "amd" in lowered or "ryzen" in lowered:
        return "AMD"
    if "intel" in lowered or "core(tm)" in lowered:
        return "Intel"
    if "apple" in lowered or "m1" in lowered or "m2" in lowered or "m3" in lowered:
        return "Apple"
    if "arm" in lowered:
        return "ARM"
    return None


def _memory_specs() -> Dict[str, Any]:
    """Total RAM plus, on Windows, the actual modules (part numbers included)."""
    import psutil

    total_gb = _round(psutil.virtual_memory().total / (1024 ** 3), 1)
    modules: List[Dict[str, Any]] = []
    speed_mhz = None
    if platform.system() == "Windows":
        rows = _cim_query(
            "Win32_PhysicalMemory",
            ["Capacity", "Speed", "Manufacturer", "PartNumber"],
        )
        for row in rows:
            try:
                capacity_gb = _round(int(row.get("Capacity", "0")) / (1024 ** 3), 1)
            except ValueError:
                capacity_gb = None
            try:
                module_speed = int(row.get("Speed", "0") or 0) or None
            except ValueError:
                module_speed = None
            modules.append({
                "capacity_gb": capacity_gb,
                "speed_mhz": module_speed,
                "manufacturer": row.get("Manufacturer") or None,
                "part": (row.get("PartNumber") or "").strip() or None,
            })
            if module_speed and not speed_mhz:
                speed_mhz = module_speed
    return {"total_gb": total_gb, "speed_mhz": speed_mhz, "modules": modules or None}


def _gpu_specs() -> List[Dict[str, Any]]:
    """GPUs from the device profile's nvidia-smi probe plus CIM for the rest."""
    gpus: List[Dict[str, Any]] = []
    if platform.system() == "Windows":
        rows = _cim_query("Win32_VideoController", ["Name", "AdapterRAM", "DriverVersion"])
        for row in rows:
            name = (row.get("Name") or "").strip()
            if not name:
                continue
            try:
                vram_gb = _round(int(row.get("AdapterRAM", "0") or 0) / (1024 ** 3), 1)
            except ValueError:
                vram_gb = None
            # AdapterRAM is a 32-bit value: anything over 4 GB reads wrong, so
            # nvidia-smi (which reports the truth) overrides it when present.
            if "nvidia" in name.lower():
                from device_profile import _detect_nvidia_gpu

                detected_name, detected_vram = _detect_nvidia_gpu()
                if detected_name:
                    name = detected_name
                if detected_vram:
                    vram_gb = _round(detected_vram, 1)
            gpus.append({
                "name": name,
                "vendor": "NVIDIA" if "nvidia" in name.lower()
                else "AMD" if "amd" in name.lower() or "radeon" in name.lower()
                else "Intel" if "intel" in name.lower()
                else None,
                "vram_gb": vram_gb,
                "driver": row.get("DriverVersion") or None,
            })
    else:
        from device_profile import _detect_nvidia_gpu

        detected_name, detected_vram = _detect_nvidia_gpu()
        if detected_name:
            gpus.append({
                "name": detected_name, "vendor": "NVIDIA",
                "vram_gb": _round(detected_vram, 1) or None, "driver": None,
            })
    return gpus


def _disk_specs() -> List[Dict[str, Any]]:
    """Physical disks from CIM; falls back to a single psutil-derived summary."""
    if platform.system() == "Windows":
        rows = _cim_query("Win32_DiskDrive", ["Model", "Size", "MediaType", "InterfaceType"])
        disks: List[Dict[str, Any]] = []
        for row in rows:
            try:
                size_gb = _round(int(row.get("Size", "0") or 0) / (1024 ** 3), 1)
            except ValueError:
                size_gb = None
            media = (row.get("MediaType") or "").strip()
            bus = (row.get("InterfaceType") or "").strip() or None
            disks.append({
                "model": (row.get("Model") or "").strip() or None,
                "size_gb": size_gb,
                "media": "SSD" if "ssd" in media.lower() or "fixed" in media.lower() else media or None,
                "bus": "NVMe" if "nvme" in (row.get("Model") or "").lower() else bus,
            })
        if disks:
            return disks
    import psutil

    usage = psutil.disk_usage("/")
    return [{
        "model": None,
        "size_gb": _round(usage.total / (1024 ** 3), 1),
        "media": None,
        "bus": None,
    }]


def _volume_specs() -> List[Dict[str, Any]]:
    import psutil

    volumes: List[Dict[str, Any]] = []
    for partition in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(partition.mountpoint)
        except (OSError, PermissionError):
            continue
        total = usage.total or 1
        volumes.append({
            "mount": partition.mountpoint,
            "fs": partition.fstype or None,
            "total_gb": _round(usage.total / (1024 ** 3), 1),
            "free_gb": _round(usage.free / (1024 ** 3), 1),
            "percent": _round(usage.used / total * 100, 1),
        })
    return volumes


def _display_specs() -> List[Dict[str, Any]]:
    """Displays from the OS. Pillow reports the primary's size on Windows."""
    displays: List[Dict[str, Any]] = []
    if platform.system() == "Windows":
        try:
            from PIL import ImageGrab

            image = ImageGrab.grab()
            displays.append({
                "name": None,
                "width": image.width,
                "height": image.height,
                "refresh_hz": None,
                "scale_percent": None,
                "primary": True,
            })
        except Exception:  # noqa: BLE001 - screen capture needs an interactive session
            pass
    if not displays:
        try:
            import tkinter

            root = tkinter.Tk()
            root.withdraw()
            displays.append({
                "name": None, "width": root.winfo_screenwidth(),
                "height": root.winfo_screenheight(), "refresh_hz": None,
                "scale_percent": None, "primary": True,
            })
            root.destroy()
        except Exception:  # noqa: BLE001
            pass
    return displays


def _network_specs() -> List[Dict[str, Any]]:
    import psutil

    addrs = psutil.net_if_addrs()
    stats = psutil.net_if_stats()
    networks: List[Dict[str, Any]] = []
    for name, address_list in addrs.items():
        ipv4 = None
        mac = None
        for address in address_list:
            import socket

            if address.family == socket.AF_INET and ipv4 is None:
                ipv4 = address.address
            import psutil as _psutil

            if address.family == _psutil.AF_LINK:
                mac = address.address
        stat = stats.get(name)
        networks.append({
            "name": name,
            "ipv4": ipv4,
            "mac": mac,
            "speed_mbps": stat.speed if stat and stat.speed else None,
            "up": bool(stat.isup) if stat else None,
        })
    return networks


def _battery_specs() -> Dict[str, Any]:
    import psutil

    battery = psutil.sensors_battery()
    if battery is None:
        return {"present": False, "percent": None, "plugged": None, "seconds_left": None}
    return {
        "present": True,
        "percent": _round(battery.percent, 0),
        "plugged": battery.power_plugged,
        "seconds_left": battery.secsleft if isinstance(battery.secsleft, int) and battery.secsleft > 0 else None,
    }


# ---------------------------------------------------------------------------
# Live readings (never cached)
# ---------------------------------------------------------------------------


#: How long one live sample measures. CPU, disk, network and per-process CPU all
#: come from this same window, so the numbers agree with each other.
_LIVE_WINDOW_SECONDS = 0.5
_SMI_FIELDS = "name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw"
_smi_missing = False


def _now() -> float:
    return time.monotonic()


def _smi_number(text: str) -> Optional[float]:
    try:
        return float(text)
    except (TypeError, ValueError):
        return None  # "[N/A]" — laptop GPUs often don't report power


def _nvidia_live() -> List[Dict[str, Any]]:
    """Every NVIDIA GPU's live readings from nvidia-smi; fields it can't read are null."""
    global _smi_missing
    if _smi_missing:
        return []
    try:
        result = subprocess.run(["nvidia-smi", f"--query-gpu={_SMI_FIELDS}", "--format=csv,noheader,nounits"],
                                capture_output=True, text=True, timeout=3,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except FileNotFoundError:
        _smi_missing = True
        return []
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    gpus = []
    for line in (result.stdout or "").strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 6:
            continue
        util, used, total, temp, power = (_smi_number(p) for p in parts[1:])
        gpus.append({"name": parts[0], "util_percent": util, "vram_used_mb": used, "vram_total_mb": total,
                     "temp_c": temp, "power_w": power})
    return gpus


def _windows_process_snapshot() -> Optional[Dict[int, Tuple[str, int, int]]]:
    """``{pid: (name, cpu_time_100ns, private_working_set_bytes)}`` for every process.

    One ``NtQuerySystemInformation(SystemProcessInformation)`` call — how Task
    Manager reads them. psutil instead opens each process and, for protected ones,
    re-lists the whole system per process, which took ~1.7 s for 330 processes.
    Offsets are the documented x64 ``SYSTEM_PROCESS_INFORMATION`` layout.
    """
    if platform.system() != "Windows" or struct.calcsize("P") != 8:
        return None
    try:
        ntdll = ctypes.WinDLL("ntdll")
        size = ctypes.c_ulong(1 << 20)
        for _ in range(4):
            buffer = ctypes.create_string_buffer(size.value)
            status = ntdll.NtQuerySystemInformation(5, buffer, size, ctypes.byref(size))
            if status == 0:
                break
            if status & 0xFFFFFFFF != 0xC0000004:  # STATUS_INFO_LENGTH_MISMATCH → grow and retry
                return None
            size = ctypes.c_ulong(size.value + (1 << 16))
        else:
            return None
        base = ctypes.addressof(buffer)
        raw = buffer.raw
        processes: Dict[int, Tuple[str, int, int]] = {}
        offset = 0
        while True:
            next_entry, = struct.unpack_from("<I", raw, offset)
            private_ws, = struct.unpack_from("<q", raw, offset + 8)
            user_time, kernel_time = struct.unpack_from("<qq", raw, offset + 40)
            name_len, = struct.unpack_from("<H", raw, offset + 56)
            name_ptr, = struct.unpack_from("<Q", raw, offset + 64)
            pid, = struct.unpack_from("<Q", raw, offset + 80)
            name = ""
            if name_ptr and name_len and base <= name_ptr < base + len(raw):
                start = name_ptr - base
                name = raw[start:start + name_len].decode("utf-16-le", errors="replace")
            processes[int(pid)] = (name or ("System Idle Process" if pid == 0 else ""), user_time + kernel_time, private_ws)
            if not next_entry:
                break
            offset += next_entry
        return processes
    except Exception:  # noqa: BLE001 - fall back to psutil
        return None


def _top_processes_windows(before: Dict[int, Tuple[str, int, int]], after: Dict[int, Tuple[str, int, int]],
                           elapsed: float, threads: int) -> List[Dict[str, Any]]:
    rows = []
    for pid, (name, cpu_after, private_ws) in after.items():
        if pid == 0:
            continue
        previous = before.get(pid)
        delta = max(0, cpu_after - previous[1]) if previous and previous[0] == name else 0
        percent = delta / (elapsed * 1e7 * threads) * 100.0
        rows.append({"pid": pid, "name": name, "cpu_percent": _round(min(percent, 100.0), 1),
                     "memory_mb": _round(private_ws / (1024 ** 2), 0)})
    return sorted(rows, key=lambda r: (-(r["cpu_percent"] or 0), -(r["memory_mb"] or 0)))[:10]


def collect_live() -> Dict[str, Any]:
    """The machine right now, measured over one short window.

    psutil's CPU percentages are deltas since the previous call, so the first
    reading of a fresh counter is always 0 — which is why per-core and per-process
    CPU used to show 0 everywhere. Everything here is primed first, then read once
    after the window.
    """
    import psutil

    memory = psutil.virtual_memory()
    freq = None
    try:
        raw = psutil.cpu_freq()
        # On Windows psutil reports WMI's fixed base speed as both current and max.
        freq = _round(raw.current, 0) if raw and raw.current != raw.max else None
    except Exception:  # noqa: BLE001
        freq = None

    tracked = []
    snapshot_before = _windows_process_snapshot()
    try:
        for proc in ([] if snapshot_before is not None else psutil.process_iter(["pid", "name"])):
            if proc.info.get("pid") == 0:
                continue  # "System Idle Process" is idle time, not a program
            try:
                proc.cpu_percent(None)
                tracked.append(proc)
            except Exception:  # noqa: BLE001 - access denied or already gone
                continue
    except Exception:  # noqa: BLE001
        tracked = []

    disk_start = psutil.disk_io_counters()
    net_start = psutil.net_io_counters()
    started = _now()
    per_core = psutil.cpu_percent(interval=_LIVE_WINDOW_SECONDS, percpu=True)  # blocks for the window
    elapsed = max(_now() - started, 1e-3)
    disk_end = psutil.disk_io_counters()
    net_end = psutil.net_io_counters()
    cpu_percent = _round(sum(per_core) / len(per_core), 1) if per_core else None

    def rate(end: Any, start: Any, field: str) -> Optional[float]:
        if end is None or start is None:
            return None
        return _round(max(0.0, getattr(end, field) - getattr(start, field)) / elapsed, 0)

    processes: List[Dict[str, Any]] = []
    threads = psutil.cpu_count(logical=True) or 1
    for proc in tracked:
        try:
            with proc.oneshot():
                rows_cpu = proc.cpu_percent(None) / threads  # match Task Manager: share of the whole CPU
                rss = proc.memory_info().rss
            processes.append({"pid": proc.info.get("pid"), "name": proc.info.get("name") or "",
                              "cpu_percent": _round(rows_cpu, 1), "memory_mb": _round(rss / (1024 ** 2), 0)})
        except Exception:  # noqa: BLE001
            continue
    processes = sorted(processes, key=lambda r: (-(r["cpu_percent"] or 0), -(r["memory_mb"] or 0)))[:10]
    if snapshot_before is not None:
        snapshot_after = _windows_process_snapshot()
        if snapshot_after is not None:
            processes = _top_processes_windows(snapshot_before, snapshot_after, elapsed, threads)

    gpus = _nvidia_live()

    return {
        "cpu": {"percent": cpu_percent, "per_core": per_core, "freq_mhz": freq},
        "memory": {
            "used_gb": _round(memory.used / (1024 ** 3), 2),
            "total_gb": _round(memory.total / (1024 ** 3), 2),
            "percent": _round(memory.percent, 1),
        },
        "gpus": gpus,
        "disk_io": {
            "read_bps": rate(disk_end, disk_start, "read_bytes"),
            "write_bps": rate(disk_end, disk_start, "write_bytes"),
        },
        "net_io": {
            "sent_bps": rate(net_end, net_start, "bytes_sent"),
            "recv_bps": rate(net_end, net_start, "bytes_recv"),
        },
        "battery": _battery_specs(),
        "top_processes": processes,
        "ts": time.time(),
    }


def register_system_tools(registry: Any) -> None:
    """Expose specs and live readings as tools (category ``general``: read-only)."""
    from tools import TOOL_REGISTRY, ToolParam  # noqa: PLC0415 - registration is runtime

    registry = registry or TOOL_REGISTRY

    def specs_tool(refresh: bool = False) -> str:
        data = collect_specs(refresh=bool(refresh))
        cpu = data.get("cpu") or {}
        os_ = data.get("os") or {}
        memory = data.get("memory") or {}
        gpus = ", ".join(g.get("name") or "?" for g in (data.get("gpus") or [])) or "none detected"
        return (
            f"OS: {os_.get('name')} ({os_.get('arch')}); CPU: {cpu.get('name')} "
            f"({cpu.get('cores')}c/{cpu.get('threads')}t); RAM: {memory.get('total_gb')} GB; "
            f"GPU: {gpus}. Use system_live for current usage."
        )

    def live_tool() -> str:
        data = collect_live()
        cpu = data.get("cpu") or {}
        memory = data.get("memory") or {}
        gpus = "; ".join(
            f"{g.get('name') or 'GPU'} {g.get('util_percent')}% util, "
            f"{g.get('vram_used_mb')}/{g.get('vram_total_mb')} MB VRAM, {g.get('temp_c')}°C"
            for g in (data.get("gpus") or [])
        ) or "no GPU telemetry"
        return (
            f"CPU {cpu.get('percent')}%, RAM {memory.get('used_gb')}/{memory.get('total_gb')} GB "
            f"({memory.get('percent')}%). GPU: {gpus}. Per-core: {cpu.get('per_core')}."
        )

    registry.register(
        "system_specs",
        "Accurate specifications of this PC (OS, CPU, RAM, GPUs, disks, displays).",
        [ToolParam(name="refresh", param_type="boolean", description="Re-scan instead of using the cache",
                   required=False)],
        specs_tool,
        category="general",
        label="Reading system specs",
    )
    registry.register(
        "system_live",
        "Live usage: CPU per core, memory, GPU telemetry, disk and network rates.",
        [],
        live_tool,
        category="general",
        label="Reading live usage",
    )
