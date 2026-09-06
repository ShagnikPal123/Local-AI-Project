"""Hardware safety telemetry (ROADMAP X1, X2, X6, X7).

Session 3 found the safety monitor blind on the owner's actual machine: pynvml was
not installed, so every reading came back as zeros and `is_safe_to_run` approved
the workload on the strength of those zeros. nvidia-smi was working the whole time.

A monitor that cannot see the GPU must say so, not report a cool idle GPU.
"""

import subprocess
from unittest.mock import patch

from hardware_safety import HardwareSafetyMonitor, _read_nvidia_smi


SMI_OK = "45, 776, 16303, 51, 39.99\n"


def _monitor():
    m = HardwareSafetyMonitor()
    m.initialized = False  # force the no-pynvml path
    m.reset_cache()
    return m


class _Result:
    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.returncode = returncode


# --- nvidia-smi parsing --------------------------------------------------------

def test_reads_live_telemetry_from_nvidia_smi():
    with patch("hardware_safety.subprocess.run", return_value=_Result(SMI_OK)):
        readings = _read_nvidia_smi()
    assert readings["gpu_temp"] == 45.0
    assert readings["vram_total_mb"] == 16303.0
    assert readings["gpu_utilization"] == 51.0


def test_monitor_uses_nvidia_smi_when_pynvml_is_missing():
    """The exact production bug: no pynvml must not mean no telemetry."""
    with patch("hardware_safety.subprocess.run", return_value=_Result(SMI_OK)):
        status = _monitor().get_hardware_status()
    assert status.gpu_temp == 45.0
    assert status.vram_total_mb == 16303.0
    assert "nvidia-smi" in status.status_summary


def test_no_telemetry_is_reported_as_unknown_not_as_zero():
    """Blind must be distinguishable from cool-and-idle."""
    with patch("hardware_safety.subprocess.run", side_effect=FileNotFoundError()):
        status = _monitor().get_hardware_status()
    assert "no_gpu_telemetry" in status.status_summary


# --- the probe must never raise into its caller --------------------------------

def test_missing_nvidia_smi_does_not_raise():
    with patch("hardware_safety.subprocess.run", side_effect=FileNotFoundError()):
        assert _read_nvidia_smi() is None


def test_timeout_does_not_raise():
    with patch(
        "hardware_safety.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="nvidia-smi", timeout=2.0),
    ):
        assert _read_nvidia_smi() is None


def test_nonzero_exit_is_not_trusted():
    with patch("hardware_safety.subprocess.run", return_value=_Result("", returncode=9)):
        assert _read_nvidia_smi() is None


def test_unparseable_output_is_not_trusted():
    """Laptop GPUs report '[N/A]' for power.draw; that must not become 0.0."""
    with patch(
        "hardware_safety.subprocess.run",
        return_value=_Result("45, 776, 16303, 51, [N/A]\n"),
    ):
        assert _read_nvidia_smi() is None


def test_absurd_temperature_is_rejected():
    """A garbage reading must not be trusted enough to gate safety on."""
    with patch("hardware_safety.subprocess.run", return_value=_Result("999, 1, 2, 3, 4\n")):
        assert _read_nvidia_smi() is None


def test_zero_total_vram_is_rejected():
    with patch("hardware_safety.subprocess.run", return_value=_Result("45, 0, 0, 0, 0\n")):
        assert _read_nvidia_smi() is None


# --- throttling decisions ------------------------------------------------------

def test_hot_gpu_is_refused():
    with patch("hardware_safety.subprocess.run", return_value=_Result("95, 776, 16303, 51, 40\n")):
        safe, reason = _monitor().is_safe_to_run(job_type="inference")
    assert safe is False
    assert "temperature" in reason.lower()


def test_near_threshold_recommends_throttle_before_refusing():
    with patch("hardware_safety.subprocess.run", return_value=_Result("79, 776, 16303, 51, 40\n")):
        status = _monitor().get_hardware_status()
    assert status.throttle_recommended is True


def test_vram_pressure_recommends_throttle():
    with patch("hardware_safety.subprocess.run", return_value=_Result("45, 16000, 16303, 51, 40\n")):
        status = _monitor().get_hardware_status()
    assert status.throttle_recommended is True


# --- cost: this runs on every turn ---------------------------------------------

def test_telemetry_is_cached_between_calls():
    monitor = _monitor()
    with patch("hardware_safety.subprocess.run", return_value=_Result(SMI_OK)) as run:
        monitor.get_hardware_status()
        monitor.get_hardware_status()
        monitor.get_hardware_status()
    assert run.call_count == 1


def test_missing_gpu_is_probed_once_not_every_turn():
    """A machine with no NVIDIA GPU must not pay a process spawn per request."""
    monitor = _monitor()
    with patch("hardware_safety.subprocess.run", side_effect=FileNotFoundError()) as run:
        monitor.get_hardware_status()
        monitor._cached_status = None  # expire only the reading cache
        monitor.get_hardware_status()
    assert run.call_count == 1
