"""Tests for system_info.py.

The OS boundary is mocked wholesale — psutil, subprocess, PIL, platform — so
these tests never read the real machine (AGENTS.md: tests never touch the OS).
What is tested is the contract the UI and tools depend on:

* unknown fields are ``None``/absent, never invented numbers;
* the CPU product name comes from CIM, not ``platform.processor()``;
* the specs cache is used and refreshed on demand;
* live readings compute rates between two samples;
* both tools register with category ``general``.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

import system_info


@pytest.fixture
def fake_psutil():
    """A psutil module good enough for every call system_info makes."""
    module = MagicMock()
    module.virtual_memory.return_value = MagicMock(total=32 * 1024 ** 3, used=12 * 1024 ** 3, percent=37.5)
    module.cpu_count.side_effect = lambda logical=True: 24 if logical else 12
    module.cpu_freq.return_value = MagicMock(current=2800.0, max=5089.0)
    module.boot_time.return_value = 0
    module.disk_partitions.return_value = []
    module.net_if_addrs.return_value = {}
    module.net_if_stats.return_value = {}
    module.sensors_battery.return_value = None
    module.process_iter.return_value = []
    module.disk_io_counters.return_value = None
    module.net_io_counters.return_value = None
    module.cpu_percent.return_value = 11.0
    module.AF_LINK = -1
    with patch.dict("sys.modules", {"psutil": module}):
        yield module


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(system_info, "_SPECS_CACHE", str(tmp_path / "specs_cache.json"))


# --- specs -----------------------------------------------------------------------


def test_cpu_name_comes_from_cim_not_platform_processor(fake_psutil):
    """The exact bug the owner reported: 'AMD64 Family 26 Model 36…'."""
    with patch.object(system_info, "_cim_query") as cim:
        def side_effect(cls, props):
            if cls == "Win32_Processor":
                return [{"Name": "AMD Ryzen AI 9 HX 370 w/ Radeon 890M"}]
            return []
        cim.side_effect = side_effect
        specs = system_info.collect_specs(refresh=True)
    assert specs["cpu"]["name"] == "AMD Ryzen AI 9 HX 370 w/ Radeon 890M"
    assert specs["cpu"]["vendor"] == "AMD"


def test_cpu_name_falls_back_to_registry_then_none(fake_psutil):
    with patch.object(system_info, "_cim_query", return_value=[]):
        reg = MagicMock(returncode=1, stdout="")
        with patch("subprocess.run", return_value=reg):
            specs = system_info.collect_specs(refresh=True)
    assert specs["cpu"]["name"] is None
    assert specs["cpu"]["vendor"] is None


def test_unknown_fields_are_null_not_guessed(fake_psutil):
    with patch.object(system_info, "_cim_query", return_value=[]):
        specs = system_info.collect_specs(refresh=True)
    assert specs["device"]["model"] is None
    assert specs["device"]["bios"] is None
    assert specs["memory"]["speed_mhz"] is None
    assert specs["displays"][0]["refresh_hz"] is None


def test_specs_are_cached_until_refresh(fake_psutil):
    with patch.object(system_info, "_cim_query", return_value=[]) as cim:
        system_info.collect_specs(refresh=True)
        assert cim.call_count > 0
        cim.reset_mock()
        system_info.collect_specs()
        assert cim.call_count == 0  # served from cache
        system_info.collect_specs(refresh=True)
        assert cim.call_count > 0


def test_cim_failure_costs_an_empty_list_not_a_crash(fake_psutil):
    with patch("subprocess.run", side_effect=OSError("no powershell")):
        assert system_info._cim_query("Win32_Processor", ["Name"]) == []


def test_memory_modules_parsed_from_cim(fake_psutil):
    rows = [{"Capacity": str(16 * 1024 ** 3), "Speed": "7500", "Manufacturer": "Crucial", "PartNumber": "CT16G56C46S5"}]
    with patch.object(system_info, "_cim_query", return_value=rows):
        specs = system_info.collect_specs(refresh=True)
    assert specs["memory"]["modules"][0]["capacity_gb"] == 16.0
    assert specs["memory"]["modules"][0]["speed_mhz"] == 7500
    assert specs["memory"]["total_gb"] == 32.0


# --- live ---------------------------------------------------------------------------


def test_live_reports_cpu_memory_and_rates(fake_psutil):
    first = MagicMock(read_bytes=1000, write_bytes=500, bytes_sent=2000, bytes_recv=8000)
    second = MagicMock(read_bytes=2000, write_bytes=1500, bytes_sent=3000, bytes_recv=9000)
    fake_psutil.disk_io_counters.side_effect = [first, second]
    fake_psutil.net_io_counters.side_effect = [first, second]
    fake_psutil.cpu_percent.return_value = [3.0, 12.0]

    with patch.object(system_info, "_now", side_effect=[10.0, 10.25]), \
            patch.object(system_info, "_nvidia_live", return_value=[]):
        live = system_info.collect_live()

    assert fake_psutil.cpu_percent.call_args.kwargs == {"interval": system_info._LIVE_WINDOW_SECONDS, "percpu": True}
    assert live["cpu"]["percent"] == 7.5  # the mean of the cores, from the same window
    assert live["cpu"]["per_core"] == [3.0, 12.0]
    assert live["memory"]["total_gb"] == 32.0
    # (2000-1000) bytes over the measured 0.25 s = 4000 B/s (it used to divide by a fixed 0.5)
    assert live["disk_io"]["read_bps"] == 4000.0
    assert live["net_io"]["sent_bps"] == 4000.0


def test_process_cpu_is_primed_then_read_and_idle_is_skipped(fake_psutil):
    class Proc:
        def __init__(self, pid, name, cpu, rss):
            self.info = {"pid": pid, "name": name}
            self._readings, self._rss = [0.0, cpu], rss

        def cpu_percent(self, interval=None):
            return self._readings.pop(0)

        def oneshot(self):
            return MagicMock(__enter__=lambda s: s, __exit__=lambda *a: False)

        def memory_info(self):
            return MagicMock(rss=self._rss)

    idle = Proc(0, "System Idle Process", 2300.0, 0)
    busy = Proc(40, "game.exe", 480.0, 2048 * 1024 ** 2)
    quiet = Proc(41, "notepad.exe", 0.0, 30 * 1024 ** 2)
    fake_psutil.process_iter.return_value = [idle, busy, quiet]
    fake_psutil.cpu_percent.return_value = [20.0] * 24
    with patch.object(system_info, "_nvidia_live", return_value=[]), \
            patch.object(system_info, "_windows_process_snapshot", return_value=None):
        live = system_info.collect_live()
    names = [p["name"] for p in live["top_processes"]]
    assert names == ["game.exe", "notepad.exe"]
    assert live["top_processes"][0]["cpu_percent"] == 20.0  # 480 % of one thread / 24 threads


def test_windows_snapshot_math_matches_task_manager():
    before = {0: ("System Idle Process", 0, 0), 40: ("game.exe", 1_000_000, 0), 41: ("notepad.exe", 5, 0),
              42: ("old.exe", 0, 0)}
    # game.exe used 2.4 s of CPU time over a 0.5 s window on 24 threads → 20 % of the machine.
    after = {0: ("System Idle Process", 99_000_000, 0), 40: ("game.exe", 1_000_000 + 24_000_000, 2048 * 1024 ** 2),
             41: ("notepad.exe", 5, 30 * 1024 ** 2), 42: ("reused.exe", 9_000_000, 0)}
    rows = system_info._top_processes_windows(before, after, elapsed=0.5, threads=24)
    assert [r["name"] for r in rows] == ["game.exe", "notepad.exe", "reused.exe"]
    assert rows[0]["cpu_percent"] == 20.0 and rows[0]["memory_mb"] == 2048.0
    assert rows[2]["cpu_percent"] == 0.0  # a reused pid is not charged the old process's time


def test_windows_snapshot_reads_this_machine():
    snapshot = system_info._windows_process_snapshot()
    if snapshot is None:
        pytest.skip("not 64-bit Windows")
    import os

    assert os.getpid() in snapshot and snapshot[os.getpid()][0].lower().startswith("python")


def test_nvidia_readings_tolerate_missing_fields():
    output = "NVIDIA GeForce RTX 5080 Laptop GPU, 26, 589, 16303, 41, [N/A]\n"
    with patch("subprocess.run", return_value=MagicMock(returncode=0, stdout=output)):
        gpus = system_info._nvidia_live()
    assert gpus == [{"name": "NVIDIA GeForce RTX 5080 Laptop GPU", "util_percent": 26.0, "vram_used_mb": 589.0,
                     "vram_total_mb": 16303.0, "temp_c": 41.0, "power_w": None}]


def test_battery_absent_is_present_false(fake_psutil):
    fake_psutil.cpu_percent.return_value = [1.0]
    with patch.object(system_info, "_nvidia_live", return_value=[]):
        live = system_info.collect_live()
    assert live["battery"]["present"] is False


# --- tools ---------------------------------------------------------------------------


def test_both_tools_register_with_general_category():
    registry = MagicMock()
    system_info.register_system_tools(registry)
    assert registry.register.call_count == 2
    for call in registry.register.call_args_list:
        assert call.kwargs["category"] == "general"
        # Parameters must be ToolParam objects: the prompt builder reads
        # .required/.param_type, and a dict here broke every chat service.
        assert all(hasattr(p, "param_type") for p in call.args[2])


def test_specs_tool_string_mentions_cpu_and_ram(fake_psutil):
    with patch.object(system_info, "_cim_query", return_value=[]):
        system_info.collect_specs(refresh=True)
    registry = MagicMock()
    system_info.register_system_tools(registry)
    specs_register = registry.register.call_args_list[0]
    handler = specs_register.args[3]
    text = handler(refresh=False)
    assert "RAM: 32.0 GB" in text
