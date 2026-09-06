"""Detect, cache, and profile local hardware for safe model-tier selection and strain regulation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import platform
import subprocess
from typing import Optional

PROFILE_CACHE_PATH = Path(__file__).with_name("device_profile.json")

# Hardware capability and preferred model tags
MODEL_TIERS = {
    "large": "qwen3.6:35b",
    "medium": "llama3.1:8b",
    "small": "llama3.2:3b",
    "tiny": "llama3.2:1b",
}


@dataclass(frozen=True)
class DeviceProfile:
    """Hardware facts needed to choose an appropriate local model size and strain limits."""

    operating_system: str
    cpu_name: str
    cpu_cores: int
    ram_gb: float
    gpu_name: str | None
    vram_gb: float

    @property
    def max_workers(self) -> int:
        """Calculate safe maximum concurrent agent workers based on system resources."""
        if self.ram_gb >= 32 and self.vram_gb >= 12:
            return 8
        elif self.ram_gb >= 16 and self.vram_gb >= 6:
            return 4
        elif self.ram_gb >= 8:
            return 2
        return 1

    @property
    def max_context_chars(self) -> int:
        """Calculate safe prompt context budget (in characters) to prevent RAM/VRAM exhaustion."""
        if self.ram_gb >= 32 or self.vram_gb >= 12:
            return 32000
        elif self.ram_gb >= 16 or self.vram_gb >= 6:
            return 16000
        elif self.ram_gb >= 8:
            return 8000
        return 4000

    @property
    def recommended_power_mode(self) -> str:
        """Recommend power profile: 'performance', 'balanced', or 'eco'."""
        if self.vram_gb >= 12 and self.ram_gb >= 16:
            return "performance"
        elif self.ram_gb >= 8:
            return "balanced"
        return "eco"


@dataclass(frozen=True)
class Tier:
    """A device capability tier and its currently preferred Ollama model tag."""

    name: str
    model_tag: str
    max_workers: int = 2
    recommended_power_mode: str = "balanced"


def get_device_profile(force_refresh: bool = False) -> DeviceProfile:
    """Return cached hardware profile unless explicitly asked to rescan."""
    if not force_refresh:
        cached_profile = _load_cached_profile()
        if cached_profile is not None:
            return cached_profile

    profile = _detect_device_profile()
    _save_cached_profile(profile)
    return profile


def select_tier(profile: DeviceProfile) -> Tier:
    """Choose the largest conservative model tier supported by the profile."""
    if profile.vram_gb >= 12 and profile.ram_gb >= 16:
        tier_name = "large"
    elif profile.vram_gb >= 6 and profile.ram_gb >= 8:
        tier_name = "medium"
    elif profile.vram_gb > 0 or profile.ram_gb >= 4:
        tier_name = "small"
    else:
        tier_name = "tiny"

    return Tier(
        name=tier_name,
        model_tag=MODEL_TIERS[tier_name],
        max_workers=profile.max_workers,
        recommended_power_mode=profile.recommended_power_mode,
    )


def _detect_device_profile() -> DeviceProfile:
    """Collect hardware values, using safe defaults when utilities are absent."""
    gpu_name, vram_gb = _detect_nvidia_gpu()
    return DeviceProfile(
        operating_system=platform.system() or "Unknown",
        cpu_name=platform.processor() or "Unknown CPU",
        cpu_cores=os.cpu_count() or 1,
        ram_gb=_detect_ram_gb(),
        gpu_name=gpu_name,
        vram_gb=vram_gb,
    )


def _detect_ram_gb() -> float:
    """Read installed RAM through Windows CIM or portable POSIX fallbacks."""
    if platform.system() == "Windows":
        ram_gb = _detect_windows_ram_gb()
        if ram_gb is not None:
            return ram_gb
    try:
        return round(
            (os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")) / (1024**3),
            2,
        )
    except (AttributeError, OSError, ValueError):
        return 0.0


def _detect_windows_ram_gb() -> float | None:
    """Ask Windows for RAM without making an optional package mandatory."""
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory",
            ],
            capture_output=True,
            check=True,
            text=True,
            timeout=5,
        )
        return round(int(result.stdout.strip()) / (1024**3), 2)
    except (
        FileNotFoundError,
        OSError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        ValueError,
    ):
        return None


def _detect_nvidia_gpu() -> tuple[str | None, float]:
    """Detect the first NVIDIA GPU through optional ``nvidia-smi`` output."""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            check=True,
            text=True,
            timeout=5,
        )
        first_line = result.stdout.strip().splitlines()[0]
        gpu_name, vram_mb = (value.strip() for value in first_line.split(",", 1))
        return gpu_name or None, round(float(vram_mb) / 1024, 2)
    except (
        FileNotFoundError,
        IndexError,
        OSError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        ValueError,
    ):
        return None, 0.0


def _load_cached_profile() -> DeviceProfile | None:
    """Load valid cache data, ignoring missing or corrupt cache files safely."""
    try:
        with PROFILE_CACHE_PATH.open("r", encoding="utf-8") as cache_file:
            data = json.load(cache_file)
        gpu_name = data["gpu_name"]
        if gpu_name is not None and not isinstance(gpu_name, str):
            raise ValueError("gpu_name must be a string or null")
        return DeviceProfile(
            operating_system=str(data["operating_system"]),
            cpu_name=str(data["cpu_name"]),
            cpu_cores=int(data["cpu_cores"]),
            ram_gb=float(data["ram_gb"]),
            gpu_name=gpu_name,
            vram_gb=float(data["vram_gb"]),
        )
    except (
        FileNotFoundError,
        OSError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ):
        return None


def _save_cached_profile(profile: DeviceProfile) -> None:
    """Persist cache data when possible; a failed cache write is non-fatal."""
    try:
        with PROFILE_CACHE_PATH.open("w", encoding="utf-8") as cache_file:
            json.dump(asdict(profile), cache_file, indent=2)
    except OSError:
        pass
