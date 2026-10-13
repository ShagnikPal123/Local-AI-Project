"""How loud the PC is right now — the peak on the default speakers, for the notch's sound pill.

The owner (2026-10-11): the third notch shows "the sounds playing. It is mainly for the sound the AI is outputting
but can be set to general for all sounds playing on a computer like music or games or videos." Ichos's own voice is
measured in the page (voicePlayer); everything else comes from here.

Windows keeps a peak meter on every output device (IAudioMeterInformation). Reading it needs no recording permission
and captures no audio — it is one number between 0 and 1. Called through the COM vtable with ctypes, so there is no
extra package to install. Anything other than Windows, or any COM failure, reads as silence.
"""

from __future__ import annotations

import ctypes
import sys
import threading
from typing import Any, Dict, Optional

_local = threading.local()

CLSID_MMDeviceEnumerator = "{BCDE0395-E52F-467C-8E3D-C4579291692E}"
IID_IMMDeviceEnumerator = "{A95664D2-9614-4F35-A746-DE8DB63617E6}"
IID_IAudioMeterInformation = "{C02216F6-8C67-4B5B-9D00-D008E73E0064}"
CLSCTX_ALL = 23
E_RENDER, E_MULTIMEDIA = 0, 1


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort), ("Data3", ctypes.c_ushort),
                ("Data4", ctypes.c_ubyte * 8)]


def _guid(text: str) -> _GUID:
    value = _GUID()
    ctypes.oledll.ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(value))
    return value


def _call(obj: ctypes.c_void_p, index: int, *args: Any, argtypes: tuple = ()) -> int:
    """Call method ``index`` of a COM object's vtable."""
    vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    method = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)(vtable[index])
    return method(obj, *args)


def _meter() -> Optional[ctypes.c_void_p]:
    """This thread's meter on the default output device (COM objects belong to the thread that made them)."""
    meter = getattr(_local, "meter", None)
    if meter is not None:
        return meter
    if sys.platform != "win32":
        return None
    ctypes.windll.ole32.CoInitializeEx(None, 0)
    enumerator = ctypes.c_void_p()
    clsid, iid = _guid(CLSID_MMDeviceEnumerator), _guid(IID_IMMDeviceEnumerator)
    if ctypes.windll.ole32.CoCreateInstance(ctypes.byref(clsid), None, CLSCTX_ALL, ctypes.byref(iid),
                                            ctypes.byref(enumerator)) != 0:
        return None
    device = ctypes.c_void_p()
    # IMMDeviceEnumerator::GetDefaultAudioEndpoint (vtable 4)
    if _call(enumerator, 4, E_RENDER, E_MULTIMEDIA, ctypes.byref(device),
             argtypes=(ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p))) != 0:
        return None
    meter = ctypes.c_void_p()
    meter_iid = _guid(IID_IAudioMeterInformation)
    # IMMDevice::Activate (vtable 3)
    if _call(device, 3, ctypes.byref(meter_iid), CLSCTX_ALL, None, ctypes.byref(meter),
             argtypes=(ctypes.POINTER(_GUID), ctypes.c_ulong, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))) != 0:
        return None
    _local.meter = meter
    return meter


def peak() -> float:
    """0.0 (silent) to 1.0 (full scale) on the default speakers right now."""
    try:
        meter = _meter()
        if meter is None:
            return 0.0
        value = ctypes.c_float(0.0)
        # IAudioMeterInformation::GetPeakValue (vtable 3)
        if _call(meter, 3, ctypes.byref(value), argtypes=(ctypes.POINTER(ctypes.c_float),)) != 0:
            _local.meter = None  # the device changed (headphones in or out): make a new one next time
            return 0.0
        return max(0.0, min(1.0, float(value.value)))
    except Exception:  # noqa: BLE001 - a meter that fails is just quiet
        _local.meter = None
        return 0.0


def level() -> Dict[str, Any]:
    value = peak()
    return {"peak": round(value, 4), "playing": value > 0.01, "supported": sys.platform == "win32"}
