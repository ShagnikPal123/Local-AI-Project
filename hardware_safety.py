"""Hardware Safety & Strain Regulator for protecting physical components during heavy workloads."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
import shutil
import subprocess
import time
from typing import Optional, Tuple

try:
    import pynvml
    NVML_AVAILABLE = True
except ImportError:
    NVML_AVAILABLE = False

logger = logging.getLogger("HardwareSafety")

# Fields requested from nvidia-smi, in order. Used when pynvml is absent, which is
# the common case: pynvml is an optional dependency, but nvidia-smi ships with every
# NVIDIA driver install. Without this fallback the monitor reported all-zero readings
# and then declared the machine safe on the strength of them — blind, not safe.
_SMI_FIELDS = (
    "temperature.gpu",
    "memory.used",
    "memory.total",
    "utilization.gpu",
    "power.draw",
)
_SMI_TIMEOUT_SECONDS = 2.0


def _read_nvidia_smi() -> Optional[dict]:
    """Read live GPU telemetry via nvidia-smi.

    Returns None whenever the reading cannot be trusted — no driver, no GPU, a
    timeout, or output that does not parse. A safety probe must never raise into
    its caller, and must never invent numbers it did not actually measure.
    """
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                f"--query-gpu={','.join(_SMI_FIELDS)}",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=_SMI_TIMEOUT_SECONDS,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return None

    if result.returncode != 0 or not result.stdout.strip():
        return None

    first_gpu = result.stdout.strip().splitlines()[0]
    parts = [p.strip() for p in first_gpu.split(",")]
    if len(parts) != len(_SMI_FIELDS):
        return None

    try:
        values = [float(p) for p in parts]
    except ValueError:
        # Fields can read "[N/A]" on some laptop GPUs, notably power.draw.
        return None

    temp, used_mb, total_mb, util, power = values
    # Sanity-check before trusting a reading enough to gate safety on it.
    if not (0.0 < temp < 150.0) or total_mb <= 0.0:
        return None

    return {
        "gpu_temp": temp,
        "vram_used_mb": used_mb,
        "vram_total_mb": total_mb,
        "gpu_utilization": util,
        "power_draw_watts": power,
    }


@dataclass
class HardwareStatus:
    gpu_temp: float = 0.0
    vram_used_mb: float = 0.0
    vram_total_mb: float = 0.0
    gpu_utilization: float = 0.0  # Percentage
    power_draw_watts: float = 0.0
    disk_free_gb: float = 0.0
    throttle_recommended: bool = False
    status_summary: str = "nominal"


class HardwareSafetyMonitor:
    """Monitor GPU/CPU/Disk health and dynamically regulate compute strain."""

    # Telemetry is re-read at most this often. The monitor is consulted on every
    # turn (and the roadmap calls for continuous checking), so an uncached
    # subprocess probe would put ~50ms of process spawn on every request. Short
    # enough that a thermal ramp is still caught well before the threshold.
    _CACHE_TTL_SECONDS = 2.0

    def __init__(self, temp_threshold: float = 82.0, vram_buffer_mb: float = 800.0):
        self.temp_threshold = temp_threshold
        self.vram_buffer_mb = vram_buffer_mb
        self.initialized = False
        self._cached_status: Optional[Tuple[float, "HardwareStatus"]] = None
        # None = not yet probed. True/False once nvidia-smi has been tried, so a
        # machine with no NVIDIA GPU pays the spawn cost once, not every turn.
        self._smi_usable: Optional[bool] = None

        if NVML_AVAILABLE:
            try:
                pynvml.nvmlInit()
                self.initialized = True
            except Exception as e:
                logger.debug(f"NVML could not initialize: {e}")

    def reset_cache(self) -> None:
        """Drop cached telemetry so the next read hits the hardware."""
        self._cached_status = None
        self._smi_usable = None

    def get_disk_free_gb(self, path: str = ".") -> float:
        """Return free disk space in GB for the workspace directory."""
        try:
            usage = shutil.disk_usage(os.path.abspath(path))
            return round(usage.free / (1024**3), 2)
        except Exception:
            return 0.0

    def _status_from_readings(self, readings: dict, disk_free: float, source: str) -> HardwareStatus:
        """Build a HardwareStatus from a trusted telemetry reading."""
        temp = readings["gpu_temp"]
        vram_used = readings["vram_used_mb"]
        vram_total = readings["vram_total_mb"]

        throttle = (
            temp >= (self.temp_threshold - 4.0)
            or (vram_total - vram_used) < self.vram_buffer_mb
        )
        summary = "throttled_high_temp" if temp >= self.temp_threshold else f"nominal ({source})"

        return HardwareStatus(
            gpu_temp=temp,
            vram_used_mb=round(vram_used, 1),
            vram_total_mb=round(vram_total, 1),
            gpu_utilization=readings["gpu_utilization"],
            power_draw_watts=round(readings["power_draw_watts"], 1),
            disk_free_gb=disk_free,
            throttle_recommended=throttle,
            status_summary=summary,
        )

    def get_hardware_status(self) -> HardwareStatus:
        """Fetch current hardware health status.

        Order of preference: cached reading, NVML, nvidia-smi, then a conservative
        no-telemetry fallback. The fallback reports that it has no readings rather
        than reporting zeros, so callers can tell "cool and idle" apart from "blind".
        """
        cached = self._cached_status
        if cached is not None and (time.monotonic() - cached[0]) < self._CACHE_TTL_SECONDS:
            return cached[1]

        status = self._read_status_uncached()
        previous = self._cached_status[1] if self._cached_status else None
        self._cached_status = (time.monotonic(), status)

        # Only log the transition, not every poll — this runs on every turn.
        if previous is not None and previous.throttle_recommended != status.throttle_recommended:
            try:
                from event_log import ok as log_ok, warn as log_warn

                if status.throttle_recommended:
                    log_warn(f"Throttling: GPU {status.gpu_temp}C", "safety")
                else:
                    log_ok("Throttling cleared", "safety")
            except Exception:
                pass
        return status

    def _read_status_uncached(self) -> HardwareStatus:
        disk_free = self.get_disk_free_gb()

        if not self.initialized:
            # pynvml missing or failed to init. nvidia-smi ships with the driver,
            # so try it before giving up on telemetry entirely.
            if self._smi_usable is not False:
                readings = _read_nvidia_smi()
                self._smi_usable = readings is not None
                if readings is not None:
                    return self._status_from_readings(readings, disk_free, "nvidia-smi")

            return HardwareStatus(
                disk_free_gb=disk_free,
                status_summary="no_gpu_telemetry (conservative fallback)",
            )

        try:
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            temp = float(pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU))
            mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
            util = float(pynvml.nvmlDeviceGetUtilizationRates(handle).gpu)
            power = float(pynvml.nvmlDeviceGetPowerUsage(handle) / 1000.0)

            vram_used = float(mem.used / (1024**2))
            vram_total = float(mem.total / (1024**2))

            throttle = temp >= (self.temp_threshold - 4.0) or (vram_total - vram_used) < self.vram_buffer_mb
            summary = "throttled_high_temp" if temp >= self.temp_threshold else "nominal"

            return HardwareStatus(
                gpu_temp=temp,
                vram_used_mb=round(vram_used, 1),
                vram_total_mb=round(vram_total, 1),
                gpu_utilization=util,
                power_draw_watts=round(power, 1),
                disk_free_gb=disk_free,
                throttle_recommended=throttle,
                status_summary=summary,
            )
        except Exception as e:
            # NVML broke mid-session (driver reset, GPU removed). Fall through to
            # nvidia-smi rather than going blind.
            readings = _read_nvidia_smi()
            if readings is not None:
                return self._status_from_readings(readings, disk_free, "nvidia-smi")
            return HardwareStatus(
                disk_free_gb=disk_free,
                status_summary=f"nvml_error: {e}",
            )

    def is_safe_to_run(self, job_type: str = "inference", required_vram_mb: float = 0.0) -> Tuple[bool, str]:
        """Check if hardware conditions are safe for a specific workload."""
        status = self.get_hardware_status()

        if status.gpu_temp > self.temp_threshold and status.gpu_temp > 0.0:
            return False, f"GPU temperature too high: {status.gpu_temp}°C (Safe limit: {self.temp_threshold}°C)"

        if job_type in ["load-model", "fine-tune"]:
            if status.vram_total_mb > 0:
                available_vram = status.vram_total_mb - status.vram_used_mb
                if available_vram < (required_vram_mb + self.vram_buffer_mb):
                    return False, f"Insufficient VRAM: {available_vram:.1f}MB available, requires {required_vram_mb:.1f}MB."

        if status.disk_free_gb < 1.0 and status.disk_free_gb > 0.0:
            return False, f"Low disk space: {status.disk_free_gb}GB free. Maintain at least 1GB for safe operation."

        return True, "Hardware parameters within safe limits."

    def calculate_strain_throttle(self) -> float:
        """Calculate dynamic sleep / delay throttle (in seconds) to stabilize hot hardware."""
        status = self.get_hardware_status()
        if status.gpu_temp >= self.temp_threshold:
            return 2.5
        elif status.gpu_temp >= (self.temp_threshold - 5.0):
            return 0.8
        return 0.0


SAFETY_MONITOR = HardwareSafetyMonitor()
