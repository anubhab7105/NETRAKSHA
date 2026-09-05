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
    source: str  # e.g. "Lookout Circular", "Interpol Red Notice"
    match_confidence: float  # 0.0 to 1.0


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


class MockWatchlistProvider(WatchlistProvider):
    """Mock watchlist with seeded high-risk test subjects.

    Seeded entries represent fictional individuals for demo/testing.
    All entries are clearly marked as mocked data.
    """

    def __init__(self) -> None:
        self._entries: List[dict] = [
            {
                "name": "Vikram Singh Chauhan",
                "id_number": "9876 5432 1098",
                "flag_reason": "Lookout Circular — Suspected fraudulent document ring",
                "source": "Lookout Circular",
            },
            {
                "name": "Abdul Karim Telgi",
                "id_number": "BFKPT4567R",
                "flag_reason": "Interpol Red Notice — Counterfeit stamp paper network",
                "source": "Interpol Red Notice",
            },
            {
                "name": "Priya Nair",
                "id_number": "KER4567890",
                "flag_reason": "Lookout Circular — Identity fraud, multiple aliases",
                "source": "Lookout Circular",
            },
            {
                "name": "Mohammad Reza Khan",
                "id_number": "L9876543",
                "flag_reason": "Interpol Blue Notice — Information gathering, travel document fraud",
                "source": "Interpol Blue Notice",
            },
            {
                "name": "Suresh Kalmadi",
                "id_number": "ALCPK3456Q",
                "flag_reason": "Lookout Circular — Financial irregularities, passport impoundment",
                "source": "Lookout Circular",
            },
        ]

    @property
    def is_mocked(self) -> bool:
        return True

    def _normalize(self, s: Optional[str]) -> str:
        if not s:
            return ""
        return re.sub(r"[\s\-]", "", s.strip().lower())

    def _fuzzy_name_match(self, query: str, target: str) -> float:
        """Simple token-overlap fuzzy match. Returns 0.0-1.0."""
        q_tokens = set(query.lower().split())
        t_tokens = set(target.lower().split())
        if not q_tokens or not t_tokens:
            return 0.0
        overlap = len(q_tokens & t_tokens)
        return overlap / max(len(q_tokens), len(t_tokens))

    def check(
        self,
        name: Optional[str] = None,
        id_number: Optional[str] = None,
    ) -> WatchlistResult:
        """Check against seeded mock watchlist entries.

        Matches by:
          - Exact ID number match (after normalization)
          - Fuzzy name match (token overlap >= 0.5)
        """
        hits: List[WatchlistHit] = []
        norm_id = self._normalize(id_number)
        norm_name = (name or "").strip().lower()

        for entry in self._entries:
            entry_norm_id = self._normalize(entry["id_number"])
            matched = False
            confidence = 0.0

            # Exact ID match
            if norm_id and entry_norm_id and norm_id == entry_norm_id:
                matched = True
                confidence = 1.0

            # Fuzzy name match
            if not matched and norm_name:
                name_score = self._fuzzy_name_match(norm_name, entry["name"])
                if name_score >= 0.5:
                    matched = True
                    confidence = max(confidence, name_score)

            if matched:
                hits.append(WatchlistHit(
                    name=entry["name"],
                    id_number=entry["id_number"],
                    flag_reason=entry["flag_reason"],
                    source=entry["source"],
                    match_confidence=round(confidence, 2),
                ))

        return WatchlistResult(
            is_hit=len(hits) > 0,
            hits=hits,
            is_mocked=True,
            checked_name=name,
            checked_id=id_number,
        )


# Module-level default provider instance
_default_provider: Optional[WatchlistProvider] = None


def get_watchlist_provider() -> WatchlistProvider:
    """Get the global watchlist provider (creates MockWatchlistProvider on first call)."""
    global _default_provider
    if _default_provider is None:
        _default_provider = MockWatchlistProvider()
    return _default_provider


def set_watchlist_provider(provider: WatchlistProvider) -> None:
    """Override the global watchlist provider (e.g. for production deployment).

    Production note (audit P2 §2): In a production deployment, call this at
    startup with a ``DBWatchlistProvider`` instance backed by the
    ``watchlist_entries`` table.  The backend/seed.py already inserts matching
    records, so switching from the in-process MockWatchlistProvider to a
    DB-backed provider only requires implementing the ``check()`` query
    against SQLAlchemy's ``WatchlistEntry`` model.
    """
    global _default_provider
    _default_provider = provider


def check_watchlist(
    name: Optional[str] = None,
    id_number: Optional[str] = None,
) -> WatchlistResult:
    """Convenience function: check against the current global watchlist provider."""
    return get_watchlist_provider().check(name=name, id_number=id_number)
