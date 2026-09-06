"""Tests for hardware safety and strain regulation."""

from unittest.mock import patch

from hardware_safety import HardwareSafetyMonitor, HardwareStatus


def test_hardware_safety_disk_check():
    monitor = HardwareSafetyMonitor()
    free_gb = monitor.get_disk_free_gb()
    assert isinstance(free_gb, float)
    assert free_gb >= 0.0


def test_hardware_safety_throttle_on_high_temp():
    monitor = HardwareSafetyMonitor(temp_threshold=80.0)
    with patch.object(
        monitor,
        "get_hardware_status",
        return_value=HardwareStatus(gpu_temp=85.0, throttle_recommended=True),
    ):
        safe, reason = monitor.is_safe_to_run()
        assert safe is False
        assert "temperature too high" in reason.lower()

        delay = monitor.calculate_strain_throttle()
        assert delay > 0.0


def test_hardware_safety_normal_status():
    monitor = HardwareSafetyMonitor(temp_threshold=80.0)
    with patch.object(
        monitor,
        "get_hardware_status",
        return_value=HardwareStatus(gpu_temp=55.0, throttle_recommended=False, disk_free_gb=50.0),
    ):
        safe, reason = monitor.is_safe_to_run()
        assert safe is True
        assert monitor.calculate_strain_throttle() == 0.0
