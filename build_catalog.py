"""Real components the Build studio can drop into a project.

The owner asked for a studio that "finds different solutions such as if I want
to store an AI it thinks of things like pi or arduino". That comparison is only
worth anything if the parts are real, so each entry here carries the actual
outline of the board or component in millimetres and the pins you would really
wire to. Everything is a compact dict that ``expand()`` turns into the same
validated part spec the owner would get by drawing one by hand.

Dimensions are *nominal* - the published board outline, rounded to 0.1 mm. That
is right for laying out an enclosure and for checking that a thing fits, and it
is not a substitute for the datasheet when you are about to cut metal. Every
expanded part says so in ``summary`` so the claim travels with the data.

Coordinates: X is the long edge, Z the short edge, Y is up. A board's origin is
the centre of its PCB, so a placement at the origin sits centred in the space.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

#: Pin names of the 40-pin Raspberry Pi header, in physical pin order (1..40).
PI_HEADER = [
    ("3V3", "power", 3.3), ("5V", "power", 5.0),
    ("GPIO2 SDA", "i2c", 3.3), ("5V", "power", 5.0),
    ("GPIO3 SCL", "i2c", 3.3), ("GND", "gnd", 0.0),
    ("GPIO4", "digital", 3.3), ("GPIO14 TXD", "uart", 3.3),
    ("GND", "gnd", 0.0), ("GPIO15 RXD", "uart", 3.3),
    ("GPIO17", "digital", 3.3), ("GPIO18 PWM", "pwm", 3.3),
    ("GPIO27", "digital", 3.3), ("GND", "gnd", 0.0),
    ("GPIO22", "digital", 3.3), ("GPIO23", "digital", 3.3),
    ("3V3", "power", 3.3), ("GPIO24", "digital", 3.3),
    ("GPIO10 MOSI", "spi", 3.3), ("GND", "gnd", 0.0),
    ("GPIO9 MISO", "spi", 3.3), ("GPIO25", "digital", 3.3),
    ("GPIO11 SCLK", "spi", 3.3), ("GPIO8 CE0", "spi", 3.3),
    ("GND", "gnd", 0.0), ("GPIO7 CE1", "spi", 3.3),
    ("GPIO0 ID_SD", "i2c", 3.3), ("GPIO1 ID_SC", "i2c", 3.3),
    ("GPIO5", "digital", 3.3), ("GND", "gnd", 0.0),
    ("GPIO6", "digital", 3.3), ("GPIO12 PWM", "pwm", 3.3),
    ("GPIO13 PWM", "pwm", 3.3), ("GND", "gnd", 0.0),
    ("GPIO19", "digital", 3.3), ("GPIO16", "digital", 3.3),
    ("GPIO26", "digital", 3.3), ("GPIO20", "digital", 3.3),
    ("GND", "gnd", 0.0), ("GPIO21", "digital", 3.3),
]


def _header_pins(names: List[tuple], *, x0: float, z0: float, y: float,
                 pitch: float = 2.54, rows: int = 2) -> List[Dict[str, Any]]:
    """Lay a 0.1 inch header out the way it really sits on the board.

    Physical pin 1 is at (x0, z0); odd pins run along the first row, even pins
    along the second, which is what makes "pin 6 is a ground" true in the 3D
    view and not just in the label.
    """
    pins: List[Dict[str, Any]] = []
    for index, (name, kind, voltage) in enumerate(names):
        column = index // rows if rows > 1 else index
        row = index % rows if rows > 1 else 0
        pins.append({
            "id": f"h{index + 1}",
            "name": f"{index + 1} {name}",
            "kind": kind,
            "direction": "power" if kind == "power" else ("gnd" if kind == "gnd" else "bidir"),
            "voltage": voltage,
            "at": [x0 + column * pitch, y, z0 + row * pitch],
        })
    return pins


def _simple_pins(entries: List[tuple], *, x0: float, z0: float, y: float, pitch: float = 2.54,
                 along: str = "x", prefix: str = "p") -> List[Dict[str, Any]]:
    """A straight row of pins. Give each row on one part its own ``prefix``:
    two rows both numbered p1, p2 would collide and the second would be lost."""
    pins = []
    for index, entry in enumerate(entries):
        name, kind, voltage = entry[0], entry[1], entry[2]
        direction = entry[3] if len(entry) > 3 else ("power" if kind == "power" else "gnd" if kind == "gnd" else "bidir")
        offset = index * pitch
        pins.append({
            "id": f"{prefix}{index + 1}",
            "name": name,
            "kind": kind,
            "direction": direction,
            "voltage": voltage,
            "required": kind in ("power", "gnd"),
            "at": [x0 + (offset if along == "x" else 0.0), y, z0 + (offset if along == "z" else 0.0)],
        })
    return pins


def _pcb(w: float, d: float, h: float = 1.6, color: str = "#0f5132") -> Dict[str, Any]:
    return {"type": "box", "name": "PCB", "size": {"w": w, "d": d, "h": h}, "color": color,
            "round": 1.0, "note": "The bare board outline."}


METAL = "#b8bcc6"
BLACK = "#1c1c22"
CHIP = "#6b6f78"


def _block(name: str, w: float, d: float, h: float, at: List[float], note: str = "",
           round_mm: float = 0.4, color: str = "") -> Dict[str, Any]:
    block = {"type": "box", "name": name, "size": {"w": w, "d": d, "h": h}, "at": at,
             "round": round_mm, "note": note}
    if not color:
        lowered = name.lower()
        if any(word in lowered for word in ("usb", "ethernet", "hdmi", "shield", "can")):
            color = METAL
        elif any(word in lowered for word in ("header", "jack", "terminal", "trimmer")):
            color = BLACK
        elif any(word in lowered for word in ("soc", "rp2040", "module", "chip")):
            color = CHIP
    if color:
        block["color"] = color
    return block


def _mount_holes(w: float, d: float, inset: float, r: float, board_h: float) -> Dict[str, Any]:
    """Four M2.5/M3 holes, as one cut with a 2x2 array - one feature, not four."""
    return {
        "type": "cylinder", "name": "Mounting holes", "op": "cut",
        "size": {"r": r, "h": board_h * 4},
        "at": [-w / 2 + inset, 0.0, -d / 2 + inset],
        "repeat": {"count": 2, "step": [w - inset * 2, 0.0, 0.0]},
        "mirror": ["z"],
        "note": f"M{r * 2:.1f} clearance holes, {inset:.1f} mm in from each corner.",
    }


#: Everything the studio can place. Grouped so the picker can show sections.
CATALOG: Dict[str, Dict[str, Any]] = {}


def _register(entry: Dict[str, Any]) -> None:
    CATALOG[entry["id"]] = entry


# --- computers you could put an AI on -----------------------------------------

_register({
    "id": "raspberry-pi-5",
    "name": "Raspberry Pi 5 (8 GB)",
    "group": "Compute",
    "kind": "electronic",
    "color": "#0f5132",
    "summary": "Quad-core Cortex-A76 single-board computer. Nominal outline 85 x 56 x 1.6 mm; runs a full Linux, so it can host a local model.",
    "specs": {"voltage": 5.0, "recommended_supply_ma": 5000, "draw_ma": 2500, "price_usd": 80.0,
              "ram_gb": 8, "runs": "Linux, Python, containers", "storage": "microSD or NVMe HAT"},
    "tags": ["compute", "linux", "ai"],
    "features": [
        _pcb(85, 56),
        _block("USB 3.0 stack", 17.5, 13.5, 16.0, [85 / 2 - 9.0, 8.8, -56 / 2 + 11.0], "Blue USB 3 pair."),
        _block("USB 2.0 stack", 17.5, 13.5, 16.0, [85 / 2 - 9.0, 8.8, -56 / 2 + 29.0], "Black USB 2 pair."),
        _block("Ethernet", 21.0, 16.0, 13.5, [85 / 2 - 11.0, 7.5, 56 / 2 - 9.0], "Gigabit RJ45."),
        _block("USB-C power", 9.0, 7.5, 3.2, [-85 / 2 + 11.2, 2.4, -56 / 2 + 3.0], "5 V 5 A in."),
        _block("SoC + heat spreader", 20.0, 20.0, 2.6, [0.0, 2.1, 0.0], "BCM2712. Put a heatsink on it."),
        _block("GPIO header", 51.0, 5.0, 8.5, [3.5, 5.0, 56 / 2 - 6.0], "2 x 20 at 2.54 mm."),
        _mount_holes(85, 56, 3.5, 1.4, 1.6),
    ],
    "pins": _header_pins(PI_HEADER, x0=-85 / 2 + 7.0, z0=56 / 2 - 7.3, y=9.0),
})

_register({
    "id": "raspberry-pi-zero-2w",
    "name": "Raspberry Pi Zero 2 W",
    "group": "Compute",
    "kind": "electronic",
    "color": "#0f5132",
    "summary": "Quad-core A53 at 65 x 30 x 1.6 mm. Small and low-power; fine for a voice front end, too slow for a large model.",
    "specs": {"voltage": 5.0, "recommended_supply_ma": 2500, "draw_ma": 450, "price_usd": 15.0,
              "ram_gb": 0.5, "runs": "Linux, Python", "storage": "microSD"},
    "tags": ["compute", "linux", "tiny"],
    "features": [
        _pcb(65, 30),
        _block("Mini HDMI", 11.0, 7.5, 3.5, [-65 / 2 + 12.4, 2.6, -30 / 2 + 3.0]),
        _block("Micro USB", 8.0, 5.5, 2.8, [-65 / 2 + 41.4, 2.2, -30 / 2 + 3.0], "Power in."),
        _block("GPIO header", 51.0, 5.0, 8.5, [0.0, 5.0, 30 / 2 - 3.5], "2 x 20 at 2.54 mm."),
        _mount_holes(65, 30, 3.5, 1.4, 1.6),
    ],
    "pins": _header_pins(PI_HEADER, x0=-65 / 2 + 3.5, z0=30 / 2 - 4.8, y=9.0),
})

_register({
    "id": "jetson-orin-nano",
    "name": "Jetson Orin Nano dev kit",
    "group": "Compute",
    "kind": "electronic",
    "color": "#123524",
    "summary": "NVIDIA carrier board, nominal 103 x 90.5 mm. 40 TOPS class GPU: the option that actually runs a mid-size model locally, at a much higher price and heat budget.",
    "specs": {"voltage": 19.0, "recommended_supply_ma": 3400, "draw_ma": 2600, "price_usd": 249.0,
              "ram_gb": 8, "runs": "Linux, CUDA, TensorRT", "storage": "NVMe"},
    "tags": ["compute", "gpu", "ai"],
    "features": [
        _pcb(103, 90.5, 1.6, "#123524"),
        _block("Module + heatsink", 69.6, 45.0, 26.0, [0.0, 14.0, 6.0], "SO-DIMM module under a finned heatsink."),
        _block("Fan", 40.0, 40.0, 10.0, [0.0, 32.0, 6.0], "Included cooler."),
        _block("Ethernet", 21.0, 16.0, 13.5, [103 / 2 - 11.0, 7.5, 90.5 / 2 - 9.0]),
        _block("USB stack", 17.5, 27.0, 16.0, [103 / 2 - 9.0, 8.8, -8.0]),
        _block("Barrel jack", 9.5, 13.0, 11.0, [-103 / 2 + 6.0, 5.5, 90.5 / 2 - 12.0], "19 V in."),
        _mount_holes(103, 90.5, 4.0, 1.6, 1.6),
    ],
    "pins": _header_pins(PI_HEADER, x0=-103 / 2 + 12.0, z0=-90.5 / 2 + 7.0, y=9.0),
})

_register({
    "id": "arduino-uno-r4-wifi",
    "name": "Arduino Uno R4 WiFi",
    "group": "Compute",
    "kind": "electronic",
    "color": "#00979d",
    "summary": "Microcontroller, nominal 68.6 x 53.4 mm. No operating system: it reacts in microseconds and never boots, which is what you want holding a relay, not a model.",
    "specs": {"voltage": 5.0, "recommended_supply_ma": 1000, "draw_ma": 90, "price_usd": 27.5,
              "ram_gb": 0.00003, "runs": "One compiled sketch", "storage": "256 KB flash"},
    "tags": ["microcontroller", "realtime"],
    "features": [
        _pcb(68.6, 53.4, 1.6, "#00979d"),
        _block("USB-C", 9.0, 7.5, 3.2, [-68.6 / 2 + 5.0, 2.4, 53.4 / 2 - 14.0]),
        _block("Barrel jack", 9.0, 13.5, 11.0, [-68.6 / 2 + 5.5, 5.5, -53.4 / 2 + 9.0]),
        _block("Digital header", 38.0, 2.6, 8.5, [9.0, 5.0, 53.4 / 2 - 2.5], "D0-D13."),
        _block("Power header", 20.0, 2.6, 8.5, [-16.0, 5.0, -53.4 / 2 + 2.5], "3V3, 5V, GND, VIN."),
        _block("Analog header", 15.0, 2.6, 8.5, [14.0, 5.0, -53.4 / 2 + 2.5], "A0-A5."),
        _block("LED matrix", 24.0, 8.0, 1.2, [6.0, 1.6, 6.0], "12 x 8 on-board LEDs."),
    ],
    "pins": _simple_pins([
        ("VIN", "power", 9.0), ("GND", "gnd", 0.0), ("5V", "power", 5.0), ("3V3", "power", 3.3),
        ("A0", "analog", 5.0), ("A1", "analog", 5.0), ("A2", "analog", 5.0), ("A3", "analog", 5.0),
        ("D2", "digital", 5.0), ("D3 PWM", "pwm", 5.0), ("D5 PWM", "pwm", 5.0), ("D6 PWM", "pwm", 5.0),
        ("D9 PWM", "pwm", 5.0), ("D10", "digital", 5.0), ("D11 MOSI", "spi", 5.0), ("D12 MISO", "spi", 5.0),
        ("D13 SCK", "spi", 5.0), ("SDA", "i2c", 5.0), ("SCL", "i2c", 5.0),
    ], x0=-68.6 / 2 + 8.0, z0=-53.4 / 2 + 2.5, y=9.0),
})

_register({
    "id": "esp32-devkit",
    "name": "ESP32 DevKit v1",
    "group": "Compute",
    "kind": "electronic",
    "color": "#1b1f23",
    "summary": "Dual-core microcontroller with WiFi and Bluetooth, nominal 51.5 x 25.5 mm. The cheap way to put a sensor on the network and talk to the AI over HTTP.",
    "specs": {"voltage": 3.3, "recommended_supply_ma": 500, "draw_ma": 240, "price_usd": 8.0,
              "runs": "One compiled firmware", "storage": "4 MB flash"},
    "tags": ["microcontroller", "wifi"],
    "features": [
        _pcb(51.5, 25.5, 1.6, "#1b1f23"),
        _block("ESP32 module", 18.0, 25.5, 3.2, [-51.5 / 2 + 11.0, 2.4, 0.0], "Shielded can plus antenna."),
        _block("Micro USB", 8.0, 5.5, 2.8, [51.5 / 2 - 3.0, 2.2, 0.0]),
        _block("Header", 38.0, 2.6, 8.5, [2.0, 5.0, -25.5 / 2 + 1.5]),
        _block("Header", 38.0, 2.6, 8.5, [2.0, 5.0, 25.5 / 2 - 1.5]),
    ],
    "pins": _simple_pins([
        ("VIN 5V", "power", 5.0), ("3V3", "power", 3.3), ("GND", "gnd", 0.0),
        ("GPIO2", "digital", 3.3), ("GPIO4", "digital", 3.3), ("GPIO5", "digital", 3.3),
        ("GPIO16 RX", "uart", 3.3), ("GPIO17 TX", "uart", 3.3),
        ("GPIO21 SDA", "i2c", 3.3), ("GPIO22 SCL", "i2c", 3.3),
        ("GPIO34 ADC", "analog", 3.3), ("GPIO35 ADC", "analog", 3.3),
    ], x0=-51.5 / 2 + 6.0, z0=-25.5 / 2 + 1.5, y=9.0),
})

_register({
    "id": "pico-rp2040",
    "name": "Raspberry Pi Pico",
    "group": "Compute",
    "kind": "electronic",
    "color": "#2d333b",
    "summary": "RP2040 microcontroller, nominal 51 x 21 x 1 mm. Two dollars, deterministic timing, castellated edges so it can be soldered flat onto your own board.",
    "specs": {"voltage": 3.3, "recommended_supply_ma": 300, "draw_ma": 45, "price_usd": 4.0,
              "runs": "MicroPython or C", "storage": "2 MB flash"},
    "tags": ["microcontroller", "tiny"],
    "features": [
        _pcb(51, 21, 1.0, "#2d333b"),
        _block("RP2040", 7.0, 7.0, 0.9, [0.0, 0.95, 0.0]),
        _block("Micro USB", 8.0, 5.5, 2.8, [-51 / 2 + 2.0, 1.9, 0.0]),
        {"type": "cylinder", "name": "Castellations", "op": "cut", "size": {"r": 0.8, "h": 4.0},
         "at": [-51 / 2 + 4.7, 0.0, -21 / 2 + 1.6], "repeat": {"count": 20, "step": [2.54, 0.0, 0.0]},
         "mirror": ["z"], "note": "Half-holes along both long edges."},
    ],
    "pins": _simple_pins([
        ("VBUS 5V", "power", 5.0), ("3V3", "power", 3.3), ("GND", "gnd", 0.0),
        ("GP0 TX", "uart", 3.3), ("GP1 RX", "uart", 3.3), ("GP2", "digital", 3.3), ("GP3", "digital", 3.3),
        ("GP4 SDA", "i2c", 3.3), ("GP5 SCL", "i2c", 3.3), ("GP26 ADC0", "analog", 3.3),
    ], x0=-51 / 2 + 4.7, z0=-21 / 2 + 1.6, y=1.0),
})

# --- power --------------------------------------------------------------------

_register({
    "id": "psu-5v-5a",
    "name": "5 V 5 A power supply",
    "group": "Power",
    "kind": "electronic",
    "color": "#1a1a21",
    "summary": "Wall supply with a USB-C output, 25 W. Sized for a Pi 5 with an NVMe drive and a fan.",
    "specs": {"voltage": 5.0, "supply_ma": 5000, "price_usd": 12.0},
    "tags": ["power"],
    "features": [
        _block("Brick", 60.0, 45.0, 30.0, [0.0, 15.0, 0.0], "", 3.0),
        {"type": "cylinder", "name": "Cable", "size": {"r": 2.0, "h": 120.0}, "rot": [0, 0, 90],
         "at": [-60.0, 8.0, 0.0], "note": "1.5 m lead."},
    ],
    "pins": [
        {"id": "out5", "name": "5V out", "kind": "power", "direction": "out", "voltage": 5.0,
         "at": [-30.0, 8.0, 0.0], "required": True},
        {"id": "outg", "name": "GND out", "kind": "gnd", "direction": "gnd", "voltage": 0.0,
         "at": [-30.0, 5.0, 0.0], "required": True},
    ],
})

_register({
    "id": "buck-lm2596",
    "name": "LM2596 buck converter",
    "group": "Power",
    "kind": "electronic",
    "color": "#1c3d5a",
    "summary": "Adjustable step-down module, nominal 43 x 21 x 14 mm. Takes 7-35 V in and holds 3 A out; set the output with the trimmer before wiring anything to it.",
    "specs": {"voltage": 5.0, "supply_ma": 3000, "draw_ma": 10, "price_usd": 2.5},
    "tags": ["power", "regulator"],
    "features": [
        _pcb(43, 21, 1.6, "#1c3d5a"),
        {"type": "cylinder", "name": "Input capacitor", "size": {"r": 4.0, "h": 12.0}, "at": [-12.0, 6.8, 0.0]},
        {"type": "cylinder", "name": "Output capacitor", "size": {"r": 4.0, "h": 12.0}, "at": [12.0, 6.8, 0.0]},
        {"type": "cylinder", "name": "Inductor", "size": {"r": 5.0, "h": 6.0}, "at": [0.0, 3.8, 4.0]},
        _block("Trimmer", 6.0, 6.0, 5.0, [0.0, 3.3, -6.0], "Turn this before connecting the load."),
    ],
    "pins": _simple_pins([
        ("IN+", "power", 12.0, "in"), ("IN-", "gnd", 0.0, "gnd"),
    ], x0=-43 / 2 + 3.0, z0=0.0, y=1.6, pitch=5.0, prefix="in") + _simple_pins([
        ("OUT+", "power", 5.0, "out"), ("OUT-", "gnd", 0.0, "gnd"),
    ], x0=43 / 2 - 8.0, z0=0.0, y=1.6, pitch=5.0, prefix="out"),
})

_register({
    "id": "lipo-2000",
    "name": "LiPo cell 2000 mAh",
    "group": "Power",
    "kind": "electronic",
    "color": "#3a3a46",
    "summary": "Single 3.7 V pouch cell, nominal 60 x 35 x 7 mm. Needs a protection board and a proper charger - never wire one straight to a supply.",
    "specs": {"voltage": 3.7, "supply_ma": 2000, "price_usd": 9.0, "capacity_mah": 2000},
    "tags": ["power", "battery"],
    "features": [_block("Cell", 60.0, 35.0, 7.0, [0.0, 3.5, 0.0], "", 1.5)],
    "pins": [
        {"id": "bp", "name": "B+", "kind": "power", "direction": "out", "voltage": 3.7, "at": [30.0, 3.5, -6.0], "required": True},
        {"id": "bm", "name": "B-", "kind": "gnd", "direction": "gnd", "voltage": 0.0, "at": [30.0, 3.5, 6.0], "required": True},
    ],
})

# --- input, output, motion ----------------------------------------------------

_register({
    "id": "fan-40mm",
    "name": "40 mm fan",
    "group": "Cooling",
    "kind": "electronic",
    "color": "#26262e",
    "summary": "Standard 40 x 40 x 10 mm cooling fan on 32 mm mounting centres.",
    "specs": {"voltage": 5.0, "draw_ma": 150, "price_usd": 6.0, "noise_dba": 25},
    "tags": ["cooling"],
    "features": [
        _block("Frame", 40.0, 40.0, 10.0, [0.0, 5.0, 0.0], "", 2.0, "#26262e"),
        {"type": "cylinder", "name": "Bore", "op": "cut", "size": {"r": 18.5, "h": 12.0}, "at": [0.0, 5.0, 0.0],
         "note": "The air path straight through the frame."},
        {"type": "cylinder", "name": "Hub", "size": {"r": 8.0, "h": 9.0}, "at": [0.0, 5.0, 0.0], "color": "#1c1c22"},
        {"type": "box", "name": "Blades", "size": {"w": 10.0, "d": 7.0, "h": 1.2}, "at": [0.0, 5.0, 0.0],
         "rot": [25, 0, 0], "radial": {"count": 7, "axis": "y", "radius": 13.0}, "round": 0.4, "color": "#3a3a46",
         "note": "Seven pitched blades on a ring around the hub."},
        {"type": "cylinder", "name": "Screw holes", "op": "cut", "size": {"r": 1.6, "h": 14.0},
         "at": [-16.0, 5.0, -16.0], "repeat": {"count": 2, "step": [32.0, 0.0, 0.0]}, "mirror": ["z"],
         "note": "M3 on 32 mm centres."},
    ],
    "pins": _simple_pins([
        ("+5V", "power", 5.0, "in"), ("GND", "gnd", 0.0, "gnd"), ("PWM", "pwm", 5.0, "in"),
    ], x0=-6.0, z0=20.0, y=5.0),
})

_register({
    "id": "heatsink-40mm",
    "name": "Finned heatsink 40 mm",
    "group": "Cooling",
    "kind": "mechanical",
    "color": "#8b8f98",
    "summary": "Aluminium heatsink, 40 x 40 x 18 mm, eleven fins. Sits on the SoC with a thermal pad.",
    "specs": {"price_usd": 7.0, "material": "aluminium"},
    "material": "Aluminium 6063",
    "tags": ["cooling", "printed"],
    "features": [
        _block("Base", 40.0, 40.0, 4.0, [0.0, 2.0, 0.0], "", 1.0),
        {"type": "box", "name": "Fins", "size": {"w": 1.6, "d": 40.0, "h": 14.0}, "at": [-18.0, 11.0, 0.0],
         "repeat": {"count": 11, "step": [3.6, 0.0, 0.0]}, "round": 0.4, "blend": 0.8,
         "note": "Eleven fins, 2 mm gap - printable in metal, machinable in aluminium."},
    ],
    "pins": [],
})

_register({
    "id": "oled-ssd1306",
    "name": "OLED display 0.96in",
    "group": "Input / output",
    "kind": "electronic",
    "color": "#14141a",
    "summary": "128 x 64 I2C OLED module, nominal 27.3 x 27.8 mm. Four wires and it shows you what the AI is doing.",
    "specs": {"voltage": 3.3, "draw_ma": 20, "price_usd": 5.0},
    "tags": ["display", "i2c"],
    "features": [
        _pcb(27.3, 27.8, 1.2, "#14141a"),
        _block("Glass", 26.0, 14.5, 1.4, [0.0, 1.9, -3.0], "The lit area is smaller than the glass."),
        _block("Header", 10.2, 2.6, 8.5, [0.0, 5.0, 27.8 / 2 - 2.0]),
    ],
    "pins": _simple_pins([
        ("GND", "gnd", 0.0, "gnd"), ("VCC", "power", 3.3, "in"),
        ("SCL", "i2c", 3.3, "in"), ("SDA", "i2c", 3.3, "bidir"),
    ], x0=-3.81, z0=27.8 / 2 - 2.0, y=9.0),
})

_register({
    "id": "dht22",
    "name": "DHT22 temperature / humidity",
    "group": "Sensors",
    "kind": "electronic",
    "color": "#e9ecef",
    "summary": "Nominal 25.1 x 15.1 x 7.7 mm sensor on a single data wire. Slow (one reading every two seconds) but accurate enough to watch an enclosure heat up.",
    "specs": {"voltage": 3.3, "draw_ma": 2, "price_usd": 4.0},
    "tags": ["sensor"],
    "features": [
        _block("Body", 25.1, 15.1, 7.7, [0.0, 3.9, 0.0], "", 1.0),
        {"type": "cylinder", "name": "Vents", "op": "cut", "size": {"r": 1.2, "h": 10.0}, "rot": [90, 0, 0],
         "at": [-8.0, 5.0, 0.0], "repeat": {"count": 5, "step": [4.0, 0.0, 0.0]}},
    ],
    "pins": _simple_pins([
        ("VCC", "power", 3.3, "in"), ("DATA", "digital", 3.3, "bidir"), ("NC", "net", 0.0, "passive"),
        ("GND", "gnd", 0.0, "gnd"),
    ], x0=-3.81, z0=0.0, y=-2.0),
})

_register({
    "id": "hc-sr04",
    "name": "HC-SR04 distance sensor",
    "group": "Sensors",
    "kind": "electronic",
    "color": "#1c3d5a",
    "summary": "Ultrasonic range finder, nominal 45 x 20 x 15 mm, useful from 2 cm to 4 m.",
    "specs": {"voltage": 5.0, "draw_ma": 15, "price_usd": 3.0},
    "tags": ["sensor"],
    "features": [
        _pcb(45, 20, 1.6, "#1c3d5a"),
        {"type": "cylinder", "name": "Transducers", "size": {"r": 8.0, "h": 12.0}, "at": [-12.0, 7.6, 0.0],
         "repeat": {"count": 2, "step": [24.0, 0.0, 0.0]}, "note": "Transmit and receive cans."},
        {"type": "cylinder", "name": "Crystal", "size": {"r": 4.0, "h": 3.5}, "rot": [90, 0, 0], "at": [0.0, 3.4, 4.0]},
    ],
    "pins": _simple_pins([
        ("VCC", "power", 5.0, "in"), ("TRIG", "digital", 5.0, "in"),
        ("ECHO", "digital", 5.0, "out"), ("GND", "gnd", 0.0, "gnd"),
    ], x0=-3.81, z0=-10.0, y=-2.0),
})

_register({
    "id": "servo-sg90",
    "name": "SG90 micro servo",
    "group": "Motion",
    "kind": "electronic",
    "color": "#3b82f6",
    "summary": "Hobby servo, nominal 22.8 x 12.2 x 28.5 mm plus mounting tabs. Draws a surprising amount when it stalls - give it its own 5 V.",
    "specs": {"voltage": 5.0, "draw_ma": 700, "price_usd": 3.0, "torque_kgcm": 1.8},
    "tags": ["motion"],
    "features": [
        _block("Case", 22.8, 12.2, 22.5, [0.0, 11.3, 0.0], "", 1.0),
        _block("Tabs", 32.2, 12.2, 2.5, [0.0, 17.0, 0.0], "Mounting flanges.", 1.0),
        {"type": "cylinder", "name": "Tab holes", "op": "cut", "size": {"r": 1.1, "h": 6.0},
         "at": [-13.7, 17.0, 0.0], "repeat": {"count": 2, "step": [27.4, 0.0, 0.0]}},
        {"type": "cylinder", "name": "Gearbox", "size": {"r": 5.8, "h": 4.0}, "at": [-5.9, 24.5, 0.0]},
        {"type": "cylinder", "name": "Output shaft", "size": {"r": 2.4, "h": 4.5}, "at": [-5.9, 28.0, 0.0]},
    ],
    "pins": _simple_pins([
        ("GND (brown)", "gnd", 0.0, "gnd"), ("+5V (red)", "power", 5.0, "in"), ("SIG (orange)", "pwm", 5.0, "in"),
    ], x0=11.4, z0=-2.54, y=8.0, pitch=2.54, along="z"),
})

_register({
    "id": "nema17",
    "name": "NEMA 17 stepper",
    "group": "Motion",
    "kind": "electronic",
    "color": "#2b2b33",
    "summary": "Standard 42.3 mm square stepper, 48 mm long, 5 mm shaft. Needs a driver - it is never wired straight to a board.",
    "specs": {"voltage": 12.0, "draw_ma": 1500, "price_usd": 14.0, "torque_ncm": 45},
    "tags": ["motion"],
    "features": [
        _block("Body", 42.3, 42.3, 48.0, [0.0, 24.0, 0.0], "", 2.0),
        {"type": "cylinder", "name": "Boss", "size": {"r": 11.0, "h": 2.0}, "at": [0.0, 49.0, 0.0]},
        {"type": "cylinder", "name": "Shaft", "size": {"r": 2.5, "h": 24.0}, "at": [0.0, 61.0, 0.0]},
        {"type": "cylinder", "name": "Mount holes", "op": "cut", "size": {"r": 1.6, "h": 10.0},
         "at": [-15.5, 47.0, -15.5], "repeat": {"count": 2, "step": [31.0, 0.0, 0.0]}, "mirror": ["z"],
         "note": "M3 on 31 mm centres."},
    ],
    "pins": _simple_pins([
        ("A+", "net", 12.0, "passive"), ("A-", "net", 12.0, "passive"),
        ("B+", "net", 12.0, "passive"), ("B-", "net", 12.0, "passive"),
    ], x0=-3.81, z0=-21.0, y=8.0),
})

_register({
    "id": "relay-1ch",
    "name": "Relay module 1 channel",
    "group": "Input / output",
    "kind": "electronic",
    "color": "#1c3d5a",
    "summary": "Opto-isolated relay board, nominal 43 x 17 x 19 mm. Switches mains-class loads from a logic pin - treat the screw terminal side as dangerous.",
    "specs": {"voltage": 5.0, "draw_ma": 72, "price_usd": 3.0, "switching": "10 A 250 VAC"},
    "tags": ["output", "mains"],
    "features": [
        _pcb(43, 17, 1.6, "#1c3d5a"),
        _block("Relay can", 19.0, 15.5, 15.5, [8.0, 8.4, 0.0], "", 0.6),
        _block("Terminal block", 12.0, 10.0, 11.0, [-14.0, 6.1, 0.0], "Mains side. Cover this."),
    ],
    "pins": _simple_pins([
        ("VCC", "power", 5.0, "in"), ("IN", "digital", 5.0, "in"), ("GND", "gnd", 0.0, "gnd"),
    ], x0=-3.81, z0=8.0, y=1.6),
})

_register({
    "id": "led-5mm",
    "name": "LED 5 mm",
    "group": "Input / output",
    "kind": "electronic",
    "color": "#ef4444",
    "summary": "Through-hole LED. Always in series with a resistor: 220 ohm from a 5 V pin, 150 ohm from 3.3 V.",
    "specs": {"voltage": 2.0, "draw_ma": 20, "price_usd": 0.1},
    "tags": ["output"],
    "features": [
        {"type": "cylinder", "name": "Body", "size": {"r": 2.5, "h": 6.5}, "at": [0.0, 3.25, 0.0]},
        {"type": "sphere", "name": "Dome", "size": {"r": 2.5}, "at": [0.0, 6.5, 0.0], "blend": 0.6},
        {"type": "cylinder", "name": "Rim", "size": {"r": 2.9, "h": 1.0}, "at": [0.0, 0.5, 0.0]},
        {"type": "box", "name": "Legs", "size": {"w": 0.5, "d": 0.5, "h": 24.0}, "at": [-1.27, -12.0, 0.0],
         "repeat": {"count": 2, "step": [2.54, 0.0, 0.0]}},
    ],
    "pins": [
        {"id": "a", "name": "Anode (long leg)", "kind": "net", "direction": "in", "voltage": 2.0,
         "at": [-1.27, -12.0, 0.0], "required": True},
        {"id": "k", "name": "Cathode (flat side)", "kind": "gnd", "direction": "gnd", "voltage": 0.0,
         "at": [1.27, -12.0, 0.0], "required": True},
    ],
})

_register({
    "id": "resistor-thru",
    "name": "Resistor 1/4 W",
    "group": "Input / output",
    "kind": "electronic",
    "color": "#c2a878",
    "summary": "Through-hole resistor, 6.5 mm body on 0.6 mm leads. Set the value in the part specs.",
    "specs": {"ohms": 220, "price_usd": 0.02, "power_w": 0.25},
    "tags": ["passive"],
    "features": [
        {"type": "cylinder", "name": "Body", "size": {"r": 1.25, "h": 6.5}, "rot": [0, 0, 90], "at": [0.0, 0.0, 0.0],
         "round": 0.6},
        {"type": "cylinder", "name": "Leads", "size": {"r": 0.3, "h": 26.0}, "rot": [0, 0, 90], "at": [0.0, 0.0, 0.0]},
    ],
    "pins": [
        {"id": "a", "name": "Leg A", "kind": "net", "direction": "passive", "at": [-13.0, 0.0, 0.0], "required": True},
        {"id": "b", "name": "Leg B", "kind": "net", "direction": "passive", "at": [13.0, 0.0, 0.0], "required": True},
    ],
})

# --- structure ----------------------------------------------------------------

_register({
    "id": "breadboard-830",
    "name": "Breadboard 830 point",
    "group": "Structure",
    "kind": "mechanical",
    "color": "#e5e5ea",
    "summary": "Full-size solderless breadboard, nominal 165 x 55 x 10 mm. Prototype here before you commit to a perfboard.",
    "specs": {"price_usd": 5.0},
    "tags": ["prototyping"],
    "features": [
        _block("Body", 165.0, 55.0, 10.0, [0.0, 5.0, 0.0], "", 2.0),
        {"type": "box", "name": "Centre channel", "op": "cut", "size": {"w": 160.0, "d": 5.0, "h": 3.0},
         "at": [0.0, 10.0, 0.0]},
        {"type": "box", "name": "Rail grooves", "op": "cut", "size": {"w": 160.0, "d": 1.2, "h": 1.0},
         "at": [0.0, 10.0, -24.0], "mirror": ["z"]},
    ],
    "pins": [],
})

_register({
    "id": "standoff-m3-10",
    "name": "M3 standoff 10 mm",
    "group": "Structure",
    "kind": "fastener",
    "color": "#b08d57",
    "summary": "Brass hex standoff, 10 mm body, M3 female both ends. Four of these lift a board off a plate.",
    "specs": {"price_usd": 0.3},
    "material": "Brass",
    "tags": ["fastener"],
    "features": [
        {"type": "cylinder", "name": "Hex body", "size": {"r": 2.8, "h": 10.0}, "at": [0.0, 5.0, 0.0], "sides": 6},
        {"type": "cylinder", "name": "Thread", "op": "cut", "size": {"r": 1.25, "h": 12.0}, "at": [0.0, 5.0, 0.0]},
    ],
    "pins": [
        {"id": "top", "name": "Top", "kind": "mech", "direction": "passive", "at": [0.0, 10.0, 0.0]},
        {"id": "bottom", "name": "Bottom", "kind": "mech", "direction": "passive", "at": [0.0, 0.0, 0.0]},
    ],
})

_register({
    "id": "base-plate",
    "name": "Base plate 120 x 90",
    "group": "Structure",
    "kind": "enclosure",
    "color": "#4c4f58",
    "summary": "A printable plate with a rounded edge and four M3 holes. Start an enclosure here and cut what you need out of it.",
    "specs": {"price_usd": 0.0},
    "material": "PETG",
    "tags": ["printed", "enclosure"],
    "features": [
        {"type": "box", "name": "Plate", "size": {"w": 120.0, "d": 90.0, "h": 4.0}, "at": [0.0, 2.0, 0.0], "round": 3.0},
        {"type": "cylinder", "name": "Mount holes", "op": "cut", "size": {"r": 1.7, "h": 8.0},
         "at": [-52.0, 2.0, -37.0], "repeat": {"count": 2, "step": [104.0, 0.0, 0.0]}, "mirror": ["z"]},
    ],
    "pins": [],
})

_register({
    "id": "vented-lid",
    "name": "Vented lid 120 x 90",
    "group": "Structure",
    "kind": "enclosure",
    "color": "#3f4249",
    "summary": "A lid that matches the base plate, with a slot array over the hot side. Print it face down.",
    "specs": {"price_usd": 0.0},
    "material": "PETG",
    "tags": ["printed", "enclosure"],
    "features": [
        {"type": "box", "name": "Lid", "size": {"w": 120.0, "d": 90.0, "h": 3.0}, "at": [0.0, 1.5, 0.0], "round": 3.0},
        {"type": "box", "name": "Lip", "size": {"w": 114.0, "d": 84.0, "h": 5.0}, "at": [0.0, -2.0, 0.0], "round": 2.0},
        {"type": "box", "name": "Lip pocket", "op": "cut", "size": {"w": 110.0, "d": 80.0, "h": 6.0},
         "at": [0.0, -2.5, 0.0], "round": 2.0},
        {"type": "box", "name": "Vent slots", "op": "cut", "size": {"w": 3.0, "d": 40.0, "h": 8.0},
         "at": [-27.0, 1.5, 0.0], "repeat": {"count": 10, "step": [6.0, 0.0, 0.0]}, "round": 1.4,
         "note": "Ten 3 mm slots - wide enough to print without support."},
        {"type": "cylinder", "name": "Mount holes", "op": "cut", "size": {"r": 1.7, "h": 10.0},
         "at": [-52.0, 1.5, -37.0], "repeat": {"count": 2, "step": [104.0, 0.0, 0.0]}, "mirror": ["z"]},
    ],
    "pins": [],
})


NOMINAL_NOTE = "Nominal published dimensions, rounded to 0.1 mm. Check the datasheet before cutting metal or ordering."


def groups() -> List[str]:
    seen: List[str] = []
    for entry in CATALOG.values():
        if entry["group"] not in seen:
            seen.append(entry["group"])
    return seen


def listing() -> List[Dict[str, Any]]:
    """Enough to draw the picker without expanding every part."""
    out = []
    for entry in CATALOG.values():
        out.append({
            "id": entry["id"],
            "name": entry["name"],
            "group": entry["group"],
            "kind": entry["kind"],
            "color": entry["color"],
            "summary": entry["summary"],
            "specs": entry.get("specs", {}),
            "tags": entry.get("tags", []),
            "pin_count": len(entry.get("pins", [])),
        })
    return sorted(out, key=lambda e: (e["group"], e["name"]))


def expand(catalog_id: str) -> Optional[Dict[str, Any]]:
    """Turn a catalog entry into a part spec, ready for ``clean_part``."""
    entry = CATALOG.get(str(catalog_id or "").strip())
    if not entry:
        return None
    return {
        "name": entry["name"],
        "kind": entry["kind"],
        "color": entry["color"],
        "material": entry.get("material", ""),
        "summary": f"{entry['summary']} {NOMINAL_NOTE}",
        "features": [dict(f) for f in entry["features"]],
        "pins": [dict(p) for p in entry.get("pins", [])],
        "specs": dict(entry.get("specs", {})),
        "tags": list(entry.get("tags", [])),
        "source": "catalog",
        "catalog_id": entry["id"],
    }


def search(query: str, limit: int = 12) -> List[Dict[str, Any]]:
    """Loose text match so the AI can look a part up by how someone said it."""
    words = [w for w in str(query or "").lower().split() if w]
    if not words:
        return listing()[:limit]
    scored = []
    for entry in listing():
        haystack = " ".join([entry["name"], entry["group"], entry["summary"], " ".join(entry["tags"])]).lower()
        score = sum(1 for word in words if word in haystack)
        if score:
            scored.append((score, entry))
    scored.sort(key=lambda pair: -pair[0])
    return [entry for _, entry in scored[:limit]]
