"""Pico's light local model: the biggest under the size cap that fits, never an embedding model."""

import light_model

GB = 1024 ** 3
INSTALLED = [
    {"name": "llama3.2:1b", "bytes": int(1.3 * GB)},
    {"name": "qwen2.5:3b", "bytes": int(1.9 * GB)},
    {"name": "llama3.1:8b", "bytes": int(4.7 * GB)},
    {"name": "nomic-embed-text", "bytes": int(0.3 * GB)},
    {"name": "qwen2.5:32b", "bytes": int(19 * GB)},
]


def test_biggest_under_the_cap():
    picked = light_model.pick(2.0, installed=INSTALLED, fits=lambda gb: "gpu")
    assert picked[:2] == ("ollama", "qwen2.5:3b")


def test_no_cap_takes_the_biggest_that_fits_this_pc():
    picked = light_model.pick(0.0, installed=INSTALLED, fits=lambda gb: "no" if gb > 10 else "ram")
    assert picked[1] == "llama3.1:8b"


def test_nothing_small_enough_means_none():
    assert light_model.pick(1.0, installed=INSTALLED, fits=lambda gb: "gpu") is None
    assert light_model.pick(2.0, installed=[], fits=lambda gb: "gpu") is None
