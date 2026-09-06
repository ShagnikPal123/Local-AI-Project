"""Local storage, session/cookie persistence, and custom document database."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import threading
import time
from typing import Any, Dict, List, Optional
import uuid
from paths import data_path


class LocalStorage:
    """Persistent key-value local storage with optional TTL expiration."""

    def __init__(self, storage_path: Optional[str | Path] = None):
        self.path = Path(storage_path) if storage_path else data_path("local_storage.json")
        self._lock = threading.Lock()
        self._data: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    self._data = raw
            except Exception:
                self._data = {}

    def _save(self) -> None:
        try:
            self.path.write_text(json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def set_item(self, key: str, value: Any, ttl_seconds: Optional[float] = None) -> None:
        """Store an item with optional time-to-live expiration."""
        with self._lock:
            expires_at = time.time() + ttl_seconds if ttl_seconds is not None else None
            self._data[key] = {
                "value": value,
                "expires_at": expires_at,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            self._save()

    def get_item(self, key: str, default: Any = None) -> Any:
        """Retrieve an item, returning default if missing or expired."""
        with self._lock:
            record = self._data.get(key)
            if not record:
                return default
            if record.get("expires_at") and time.time() > record["expires_at"]:
                del self._data[key]
                self._save()
                return default
            return record.get("value", default)

    def remove_item(self, key: str) -> bool:
        """Remove a key from storage."""
        with self._lock:
            if key in self._data:
                del self._data[key]
                self._save()
                return True
            return False

    def clear(self) -> None:
        """Clear all stored key-value items."""
        with self._lock:
            self._data.clear()
            self._save()

    def keys(self) -> List[str]:
        """Return all active keys."""
        with self._lock:
            now = time.time()
            active = []
            for k, v in list(self._data.items()):
                if v.get("expires_at") and now > v["expires_at"]:
                    del self._data[k]
                else:
                    active.append(k)
            return active


class SessionStore:
    """Manages browser sessions and cookies for Web/API interactions."""

    def __init__(self, session_ttl_seconds: float = 86400.0):
        self.session_ttl = session_ttl_seconds
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._cookies: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def create_session(self, user_id: str = "default_user", metadata: Optional[Dict[str, Any]] = None) -> str:
        """Generate a new authenticated session token."""
        token = str(uuid.uuid4())
        now = time.time()
        with self._lock:
            self._sessions[token] = {
                "user_id": user_id,
                "metadata": metadata or {},
                "created_at": now,
                "last_active": now,
                "expires_at": now + self.session_ttl,
            }
        return token

    def get_session(self, token: str) -> Optional[Dict[str, Any]]:
        """Validate and touch an active session."""
        with self._lock:
            session = self._sessions.get(token)
            if not session:
                return None
            if time.time() > session["expires_at"]:
                del self._sessions[token]
                return None
            session["last_active"] = time.time()
            return dict(session)

    def set_cookie(self, name: str, value: str, path: str = "/", secure: bool = False, httponly: bool = True) -> None:
        """Store cookie configuration."""
        with self._lock:
            self._cookies[name] = {
                "name": name,
                "value": value,
                "path": path,
                "secure": secure,
                "httponly": httponly,
                "set_at": time.time(),
            }

    def get_cookie(self, name: str) -> Optional[str]:
        """Retrieve a cookie value."""
        with self._lock:
            record = self._cookies.get(name)
            return record["value"] if record else None


class Collection:
    """A collection of JSON document records with querying, indexing, and mutations."""

    def __init__(self, name: str, db: CustomDatabase):
        self.name = name
        self.db = db
        self._docs: Dict[str, Dict[str, Any]] = {}
        self._indexes: Dict[str, Dict[Any, List[str]]] = {}

    def insert(self, doc: Dict[str, Any]) -> str:
        """Insert a single document, returning its assigned ID."""
        doc_id = str(doc.get("_id") or uuid.uuid4())
        stored = dict(doc)
        stored["_id"] = doc_id
        stored["_created_at"] = datetime.now(timezone.utc).isoformat()
        self._docs[doc_id] = stored
        self.db._persist()
        return doc_id

    def insert_many(self, docs: List[Dict[str, Any]]) -> List[str]:
        """Insert multiple documents."""
        ids = []
        for d in docs:
            ids.append(self.insert(d))
        return ids

    def find(self, query: Optional[Dict[str, Any]] = None, limit: int = 0) -> List[Dict[str, Any]]:
        """Query documents matching filter criteria."""
        results = []
        for doc in self._docs.values():
            if self._matches(doc, query or {}):
                results.append(dict(doc))
                if 0 < limit <= len(results):
                    break
        return results

    def find_one(self, query: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Find the first matching document."""
        res = self.find(query=query, limit=1)
        return res[0] if res else None

    def update(self, query: Dict[str, Any], update_fields: Dict[str, Any]) -> int:
        """Update matching documents with new field values."""
        count = 0
        for doc in self._docs.values():
            if self._matches(doc, query):
                doc.update(update_fields)
                doc["_updated_at"] = datetime.now(timezone.utc).isoformat()
                count += 1
        if count > 0:
            self.db._persist()
        return count

    def delete(self, query: Dict[str, Any]) -> int:
        """Delete matching documents."""
        to_del = [doc_id for doc_id, doc in self._docs.items() if self._matches(doc, query)]
        for doc_id in to_del:
            del self._docs[doc_id]
        if to_del:
            self.db._persist()
        return len(to_del)

    def count(self, query: Optional[Dict[str, Any]] = None) -> int:
        """Count matching documents."""
        if not query:
            return len(self._docs)
        return len(self.find(query=query))

    def _matches(self, doc: Dict[str, Any], query: Dict[str, Any]) -> bool:
        for k, v in query.items():
            if doc.get(k) != v:
                return False
        return True


class CustomDatabase:
    """Lightweight local document database supporting collections, querying, and indexing."""

    def __init__(self, db_path: Optional[str | Path] = None):
        self.path = Path(db_path) if db_path else data_path("custom_db.json")
        self._collections: Dict[str, Collection] = {}
        self._lock = threading.Lock()
        self._load()

    def collection(self, name: str) -> Collection:
        """Get or create a named collection."""
        with self._lock:
            if name not in self._collections:
                col = Collection(name=name, db=self)
                self._collections[name] = col
            return self._collections[name]

    def _load(self) -> None:
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    for col_name, docs_dict in raw.items():
                        col = self.collection(col_name)
                        col._docs = docs_dict
            except Exception:
                pass

    def _persist(self) -> None:
        with self._lock:
            export_data = {}
            for col_name, col in self._collections.items():
                export_data[col_name] = col._docs
            try:
                self.path.write_text(json.dumps(export_data, indent=2, ensure_ascii=False), encoding="utf-8")
            except OSError:
                pass
