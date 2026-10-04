"""Watchlist provider — checks travelers against security watchlists.

Implements a ``WatchlistProvider`` interface and a ``MockWatchlistProvider``
that seeds high-risk test subjects (Lookout Circulars, Interpol Red Notices).

The mock provider surfaces ``is_mocked = True`` to drive the required
violet "MOCKED DATA" badge in the dashboard UI.

Design: the interface is a simple callable that accepts a name and/or
document number and returns a hit-or-miss result. Production deployment
swaps the mock for a real registry client without touching the Risk Engine.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class WatchlistHit:
    """A single watchlist match result."""
    name: str
    id_number: Optional[str]
    flag_reason: str
    source: str
    match_confidence: float


@dataclass
class WatchlistResult:
    """Result of a watchlist check."""
    is_hit: bool
    hits: List[WatchlistHit] = field(default_factory=list)
    is_mocked: bool = False
    checked_name: Optional[str] = None
    checked_id: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "is_hit": self.is_hit,
            "hits": [
                {
                    "name": h.name,
                    "id_number": h.id_number,
                    "flag_reason": h.flag_reason,
                    "source": h.source,
                    "match_confidence": h.match_confidence,
                }
                for h in self.hits
            ],
            "is_mocked": self.is_mocked,
            "checked_name": self.checked_name,
            "checked_id": self.checked_id,
        }


class WatchlistProvider(ABC):
    """Abstract interface for watchlist lookups."""

    @abstractmethod
    def check(
        self,
        name: Optional[str] = None,
        id_number: Optional[str] = None,
    ) -> WatchlistResult:
        """Check a person against the watchlist.

        Args:
            name: Full name to check (fuzzy matched).
            id_number: Document/ID number to check (exact match).

        Returns:
            WatchlistResult indicating hit or clear.
        """
        ...

    @property
    @abstractmethod
    def is_mocked(self) -> bool:
        """Whether this provider uses mock/demo data."""
        ...


class DBWatchlistProvider(WatchlistProvider):
    """Supabase-backed watchlist provider — reads from ``watchlist_entries``.

    Use this in production instead of ``MockWatchlistProvider``. It queries
    the persistent table seeded by ``backend/seed.py`` so the list survives
    restarts and can be managed via Supabase dashboard / authority imports.

    ``is_mocked`` is ``False`` by default — hits are treated as real. Pass
    ``is_mocked=True`` only if the table still contains demo data and you
    want the violet MOCKED DATA badge to keep showing.
    """

    def __init__(self, entries: List[dict], is_mocked: bool = False) -> None:
        self._entries: List[dict] = list(entries or [])
        self._is_mocked = bool(is_mocked)

    @property
    def is_mocked(self) -> bool:
        return self._is_mocked

    def _normalize(self, s: Optional[str]) -> str:
        if not s:
            return ""
        return re.sub(r"[\s\-]", "", s.strip().lower())

    def _fuzzy_name_match(self, query: str, target: str) -> float:
        import difflib

        q_tokens = set(query.lower().split())
        t_tokens = set(target.lower().split())
        if not q_tokens or not t_tokens:
            return 0.0
        overlap = len(q_tokens & t_tokens) / max(len(q_tokens), len(t_tokens))
        seq = difflib.SequenceMatcher(None, query.lower(), target.lower()).ratio()
        return round(max(overlap, seq), 4)

    def _fuzzy_threshold(self) -> float:
        try:
            from pipeline.common import load_thresholds

            return float(load_thresholds().get("watchlist_fuzzy", 0.8))
        except Exception:
            return 0.8

    def check(
        self,
        name: Optional[str] = None,
        id_number: Optional[str] = None,
    ) -> WatchlistResult:
        hits: List[WatchlistHit] = []
        norm_id = self._normalize(id_number)
        norm_name = (name or "").strip().lower()
        for entry in self._entries:
            entry_norm_id = self._normalize(entry.get("id_number"))
            matched = False
            confidence = 0.0
            if norm_id and entry_norm_id and norm_id == entry_norm_id:
                matched = True
                confidence = 1.0
            if not matched and norm_name:
                name_score = self._fuzzy_name_match(norm_name, entry.get("name", ""))
                if name_score >= self._fuzzy_threshold():
                    matched = True
                    confidence = max(confidence, name_score)
            if matched:
                hits.append(WatchlistHit(
                    name=entry.get("name", ""),
                    id_number=entry.get("id_number"),
                    flag_reason=entry.get("flag_reason", "") or entry.get("reason", ""),
                    source=entry.get("source", "") or "Watchlist",
                    match_confidence=round(confidence, 2),
                ))
        return WatchlistResult(
            is_hit=len(hits) > 0,
            hits=hits,
            is_mocked=self._is_mocked,
            checked_name=name,
            checked_id=id_number,
        )

    def reload(self, entries: List[dict]) -> None:
        """Hot-reload entries without restarting (e.g. after an authority import)."""
        self._entries = list(entries or [])


class MockWatchlistProvider(DBWatchlistProvider):
    """Mock watchlist with seeded high-risk test subjects.

    All entries are SYNTHETIC and fictional (invented names, demo IDs) for
    demo/testing — never real persons. Real-person names must never be
    added here; production uses DBWatchlistProvider on authority data.
    All entries are clearly marked as mocked data. Subclasses
    ``DBWatchlistProvider`` with ``is_mocked=True``.
    """

    def __init__(self) -> None:
        super().__init__([
            {
                "name": "Arjun Veer Rathore",
                "id_number": "9876 5432 1098",
                "flag_reason": "Lookout Circular — Suspected fraudulent document ring",
                "source": "Lookout Circular",
            },
            {
                "name": "Kabir Anand Malhotra",
                "id_number": "BFKPT4567R",
                "flag_reason": "Interpol Red Notice — Counterfeit stamp paper network",
                "source": "Interpol Red Notice",
            },
            {
                "name": "Meera Krishnan Iyer",
                "id_number": "KER4567890",
                "flag_reason": "Lookout Circular — Identity fraud, multiple aliases",
                "source": "Lookout Circular",
            },
            {
                "name": "Farhan Iqbal Sheikh",
                "id_number": "L9876543",
                "flag_reason": "Interpol Blue Notice — Information gathering, travel document fraud",
                "source": "Interpol Blue Notice",
            },
            {
                "name": "Rohan Vikram Deshmukh",
                "id_number": "ALCPK3456Q",
                "flag_reason": "Lookout Circular — Financial irregularities, passport impoundment",
                "source": "Lookout Circular",
            },
        ], is_mocked=True)



_default_provider: Optional[WatchlistProvider] = None
_provider_lock: Optional[object] = None


def _get_lock():
    global _provider_lock
    if _provider_lock is None:
        import threading as _th
        _provider_lock = _th.Lock()
    return _provider_lock


def get_watchlist_provider() -> WatchlistProvider:
    """Get the global watchlist provider (creates MockWatchlistProvider on first call)."""
    global _default_provider
    if _default_provider is None:
        with _get_lock():
            if _default_provider is None:
                _default_provider = MockWatchlistProvider()
    return _default_provider


def set_watchlist_provider(provider: WatchlistProvider) -> None:
    """Override the global watchlist provider (copy-on-write + lock).

    The whole provider object is swapped atomically under a lock; readers
    always see a complete list, never a partially-mutated one. Never mutate
    ``provider._entries`` in place after publishing.

    Production note (audit P2 §2): In a production deployment, call this at
    startup with a ``DBWatchlistProvider`` instance backed by the
    ``watchlist_entries`` table.  The backend/seed.py already inserts matching
    records, so switching from the in-process MockWatchlistProvider to a
    DB-backed provider only requires implementing the ``check()`` query
    against SQLAlchemy's ``WatchlistEntry`` model.
    """
    global _default_provider
    with _get_lock():
        _default_provider = provider


def check_watchlist(
    name: Optional[str] = None,
    id_number: Optional[str] = None,
) -> WatchlistResult:
    """Convenience function: check against the current global watchlist provider."""
    return get_watchlist_provider().check(name=name, id_number=id_number)


async def load_db_watchlist_provider(is_mocked: bool = False) -> DBWatchlistProvider:
    """Load entries from Supabase ``watchlist_entries`` and return a DB provider.

    Call this at startup (after ``init_db``/``seed_all``) and pass the result
    to ``set_watchlist_provider``. Falls back to an empty list if the table is
    empty or unreachable — caller should then keep the mock for demo.
    """
    try:

        from backend.database import async_session as _async_session
        from backend.models import WatchlistEntry as _WatchlistEntry
        from sqlalchemy import select as _select
        async with _async_session() as session:
            res = await session.execute(_select(_WatchlistEntry))
            rows = res.scalars().all()
            entries = []
            for r in rows:
                reason = r.flag_reason or ""
                derived = reason.split("—")[0].split("-")[0].strip()
                entries.append(
                    {
                        "name": r.name,
                        "id_number": r.id_number,
                        "flag_reason": reason,
                        "source": getattr(r, "source", "") or derived or "Watchlist",
                    }
                )
            return DBWatchlistProvider(entries, is_mocked=is_mocked)
    except Exception as e:

        print(f"[watchlist] DB load failed, using empty provider: {type(e).__name__}: {e}")
        return DBWatchlistProvider([], is_mocked=is_mocked)
