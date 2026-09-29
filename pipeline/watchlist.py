
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class WatchlistHit:
    name: str
    id_number: Optional[str]
    flag_reason: str
    source: str
    match_confidence: float


@dataclass
class WatchlistResult:
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

    @abstractmethod
    def check(
        self,
        name: Optional[str] = None,
        id_number: Optional[str] = None,
    ) -> WatchlistResult:
        ...

    @property
    @abstractmethod
    def is_mocked(self) -> bool:
        ...


class DBWatchlistProvider(WatchlistProvider):

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
                if name_score >= 0.5:
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
        self._entries = list(entries or [])


class MockWatchlistProvider(DBWatchlistProvider):

    def __init__(self) -> None:
        super().__init__([
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
        ], is_mocked=True)



_default_provider: Optional[WatchlistProvider] = None


def get_watchlist_provider() -> WatchlistProvider:
    global _default_provider
    if _default_provider is None:
        _default_provider = MockWatchlistProvider()
    return _default_provider


def set_watchlist_provider(provider: WatchlistProvider) -> None:
    global _default_provider
    _default_provider = provider


def check_watchlist(
    name: Optional[str] = None,
    id_number: Optional[str] = None,
) -> WatchlistResult:
    return get_watchlist_provider().check(name=name, id_number=id_number)


async def load_db_watchlist_provider(is_mocked: bool = False) -> DBWatchlistProvider:
    try:

        from backend.database import async_session as _async_session
        from backend.models import WatchlistEntry as _WatchlistEntry
        from sqlalchemy import select as _select
        async with _async_session() as session:
            res = await session.execute(_select(_WatchlistEntry))
            rows = res.scalars().all()
            entries = [
                {
                    "name": r.name,
                    "id_number": r.id_number,
                    "flag_reason": r.flag_reason,
                    "source": getattr(r, "flag_reason", "") or "Watchlist",
                }
                for r in rows
            ]
            return DBWatchlistProvider(entries, is_mocked=is_mocked)
    except Exception as e:

        print(f"[watchlist] DB load failed, using empty provider: {type(e).__name__}: {e}")
        return DBWatchlistProvider([], is_mocked=is_mocked)
