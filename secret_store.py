'''Local persistent API-key storage.

Keys are never written into Python source. An optional OS keyring is used first;
the JSON fallback exists for machines without the optional dependency.
'''
from __future__ import annotations
import json
from pathlib import Path
from typing import Iterable
from paths import data_path
_STORE = data_path('.secrets.json')
_SERVICE = 'nyx-ichos'

def _read() -> dict[str, list[str]]:
    try:
        data = json.loads(_STORE.read_text(encoding='utf-8'))
        return {str(k): [str(v) for v in values if str(v).strip()] for k, values in data.items()}
    except (OSError, json.JSONDecodeError, AttributeError):
        return {}

def get_keys(name: str) -> list[str]:
    try:
        import keyring
        value = keyring.get_password(_SERVICE, name)
        if value:
            return [item.strip() for item in value.split(',') if item.strip()]
    except Exception:
        pass
    return _read().get(name, [])

def set_keys(name: str, keys: Iterable[str]) -> list[str]:
    values = list(dict.fromkeys(item.strip() for item in keys if item and item.strip()))
    try:
        import keyring
        keyring.set_password(_SERVICE, name, ','.join(values))
        return values
    except Exception:
        data = _read()
        data[name] = values
        _STORE.write_text(json.dumps(data, indent=2), encoding='utf-8')
        return values

def add_key(name: str, key: str) -> list[str]:
    return set_keys(name, [*get_keys(name), key])
