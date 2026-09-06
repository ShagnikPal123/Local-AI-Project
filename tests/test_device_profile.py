"""Offline behavior tests for hardware detection and model-tier selection."""

import json
from unittest.mock import Mock, patch

import pytest

import device_profile
from device_profile import DeviceProfile, get_device_profile, select_tier


def _profile(ram_gb: float, vram_gb: float) -> DeviceProfile:
    return DeviceProfile("Windows", "Test CPU", 8, ram_gb, "Test GPU", vram_gb)


@pytest.mark.parametrize(
    ("ram_gb", "vram_gb", "name", "model_tag"),
    [
        (16, 12, "large", "qwen3.6:35b"),
        (8, 6, "medium", "llama3.1:8b"),
        (4, 0, "small", "llama3.2:3b"),
        (2, 0, "tiny", "llama3.2:1b"),
    ],
)
def test_select_tier_uses_memory_thresholds(ram_gb, vram_gb, name, model_tag):
    tier = select_tier(_profile(ram_gb, vram_gb))
    assert (tier.name, tier.model_tag) == (name, model_tag)


def test_get_device_profile_uses_valid_cache(tmp_path, monkeypatch):
    cache_path = tmp_path / "device_profile.json"
    cache_path.write_text(json.dumps({
        "operating_system": "Windows", "cpu_name": "Cached CPU", "cpu_cores": 8,
        "ram_gb": 16, "gpu_name": "Cached GPU", "vram_gb": 8,
    }), encoding="utf-8")
    monkeypatch.setattr(device_profile, "PROFILE_CACHE_PATH", cache_path)
    with patch("device_profile._detect_device_profile") as detect:
        profile = get_device_profile()
    assert profile.cpu_name == "Cached CPU"
    detect.assert_not_called()


def test_force_refresh_detects_and_overwrites_cache(tmp_path, monkeypatch):
    cache_path = tmp_path / "device_profile.json"
    monkeypatch.setattr(device_profile, "PROFILE_CACHE_PATH", cache_path)
    detected = _profile(32, 16)
    with patch("device_profile._detect_device_profile", return_value=detected) as detect:
        assert get_device_profile(force_refresh=True) == detected
    assert json.loads(cache_path.read_text(encoding="utf-8"))["vram_gb"] == 16
    detect.assert_called_once()


def test_corrupt_cache_is_regenerated(tmp_path, monkeypatch):
    cache_path = tmp_path / "device_profile.json"
    cache_path.write_text("not JSON", encoding="utf-8")
    monkeypatch.setattr(device_profile, "PROFILE_CACHE_PATH", cache_path)
    with patch("device_profile._detect_device_profile", return_value=_profile(8, 6)) as detect:
        assert get_device_profile().vram_gb == 6
    detect.assert_called_once()


def test_nvidia_detection_parses_name_and_vram():
    result = Mock(stdout="NVIDIA RTX 5070 Ti, 16384\n")
    with patch("device_profile.subprocess.run", return_value=result):
        assert device_profile._detect_nvidia_gpu() == ("NVIDIA RTX 5070 Ti", 16.0)


def test_nvidia_detection_returns_safe_fallback_when_missing():
    with patch("device_profile.subprocess.run", side_effect=FileNotFoundError):
        assert device_profile._detect_nvidia_gpu() == (None, 0.0)


def test_windows_ram_detection_returns_safe_fallback_when_powershell_fails():
    with patch("device_profile.subprocess.run", side_effect=FileNotFoundError):
        assert device_profile._detect_windows_ram_gb() is None

