"""Database seeding — test accounts and citizen registry records.

Seeds:
  * Officer accounts (bcrypt-hashed passwords):
    - officer1 / Officer@123     (role: officer)
    - supervisor1 / Supervisor@123 (role: supervisor)
    - auditor1 / Auditor@123     (role: auditor)

  * CitizenRegistry reference profiles for Aadhaar, PAN, Voter ID, Passport
  * WatchlistEntry mock records

All seed data is idempotent — re-running does not create duplicates.
"""

from __future__ import annotations

import asyncio
import os
import sys

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select

from backend.database import async_session, init_db
from backend.models import (
    AuditLog,
    CitizenRegistry,
    Officer,
    WatchlistEntry,
)


def _hash_password(plain: str) -> str:
    """Hash a password using bcrypt via passlib.

    The SHA-256 fallback has been removed per audit finding P3 §1.
    passlib[bcrypt] is listed in requirements.txt and must be installed.
    """
    from passlib.context import CryptContext
    ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
    return ctx.hash(plain)


# ---------------------------------------------------------------------------
# Seed data definitions
# ---------------------------------------------------------------------------

OFFICERS = [
    {"username": os.environ.get("SEED_OFFICER_USER", "officer1"), "password": os.environ.get("SEED_OFFICER_PASS", "Officer@123"), "role": "officer", "unit": "BORDER_UNIT_1"},
    {"username": os.environ.get("SEED_SUPERVISOR_USER", "supervisor1"), "password": os.environ.get("SEED_SUPERVISOR_PASS", "Supervisor@123"), "role": "supervisor", "unit": "BORDER_UNIT_1"},
    {"username": os.environ.get("SEED_AUDITOR_USER", "auditor1"), "password": os.environ.get("SEED_AUDITOR_PASS", "Auditor@123"), "role": "auditor", "unit": "HQ"},
    # Additional unit for scope testing
    {"username": "officer2", "password": "Officer@123", "role": "officer", "unit": "BORDER_UNIT_2"},
]

CITIZENS = [
    {
        "document_type": "aadhaar",
        "document_number": "234567890123",
        "full_name": "Rajesh Kumar",
        "date_of_birth": "1988-04-12",
        "gender": "M",
        "address": "Flat 402, Shanti Vihar, Sector 15, Noida, UP - 201301",
        "father_or_spouse_name": "Ramesh Kumar",
        "photo_uri": "samples/faces/person_a.png",
    },
    {
        "document_type": "pan",
        "document_number": "ABCPD1234E",
        "full_name": "Rajesh Kumar",
        "date_of_birth": "1988-04-12",
        "gender": "M",
        "address": None,
        "father_or_spouse_name": "Ramesh Kumar",
        "photo_uri": "samples/faces/person_a.png",
    },
    {
        "document_type": "voter_id",
        "document_number": "ABC1234567",
        "full_name": "Rajesh Kumar",
        "date_of_birth": "1988-04-12",
        "gender": "M",
        "address": "Ward 12, Block B, Shanti Vihar, New Delhi - 110001",
        "father_or_spouse_name": "Ramesh Kumar",
        "photo_uri": "samples/faces/person_a.png",
    },
    {
        "document_type": "passport",
        "document_number": "J8369854",
        "full_name": "Rajesh Kumar",
        "date_of_birth": "1988-04-12",
        "gender": "M",
        "address": "Flat 402, Shanti Vihar, New Delhi - 110001",
        "father_or_spouse_name": None,
        "photo_uri": "samples/faces/person_a.png",
    },
    # Second citizen for mismatch testing
    {
        "document_type": "aadhaar",
        "document_number": "987654321098",
        "full_name": "Priya Sharma",
        "date_of_birth": "1995-08-22",
        "gender": "F",
        "address": "House 15, MG Road, Bangalore, KA - 560001",
        "father_or_spouse_name": "Anil Sharma",
        "photo_uri": "samples/faces/person_b.png",
    },
    # Specimen traveler — matches the shipped sample documents
    # (samples/genuine_doc.png & samples/tampered_doc.png, ICAO MRZ L898902C3)
    # so the flagship "clean traveler / tampered" demos hit a DB record and
    # produce a real demographic cross-check instead of a dead-end.
    {
        "document_type": "passport",
        "document_number": "L898902C3",
        "full_name": "Jasmine Specimen",
        "date_of_birth": "1969-12-04",
        "gender": "F",
        "address": "221B Specimen Lane, Demo City, AP - 500001",
        "father_or_spouse_name": None,
        "photo_uri": "samples/faces/person_a.png",
    },
]

WATCHLIST = [
    {
        "name": "Vikram Singh Chauhan",
        "id_number": "9876 5432 1098",
        "flag_reason": "Lookout Circular — Suspected fraudulent document ring",
    },
    {
        "name": "Abdul Karim Telgi",
        "id_number": "BFKPT4567R",
        "flag_reason": "Interpol Red Notice — Counterfeit stamp paper network",
    },
    {
        "name": "Priya Nair",
        "id_number": "KER4567890",
        "flag_reason": "Lookout Circular — Identity fraud, multiple aliases",
    },
    {
        "name": "Mohammad Reza Khan",
        "id_number": "L9876543",
        "flag_reason": "Interpol Blue Notice — Travel document fraud",
    },
    {
        "name": "Suresh Kalmadi",
        "id_number": "ALCPK3456Q",
        "flag_reason": "Lookout Circular — Financial irregularities, passport impoundment",
    },
]


async def seed_all() -> dict:
    """Run all seed operations. Returns a summary of what was seeded."""
    await init_db()

    summary = {
        "officers_created": 0,
        "officers_existed": 0,
        "citizens_created": 0,
        "citizens_existed": 0,
        "watchlist_created": 0,
        "watchlist_existed": 0,
    }

    async with async_session() as session:
        # --- Officers ---
        for o in OFFICERS:
            existing = await session.execute(
                select(Officer).where(Officer.username == o["username"])
            )
            if existing.scalar_one_or_none() is None:
                session.add(Officer(
                    username=o["username"],
                    password_hash=_hash_password(o["password"]),
                    role=o["role"],
                ))
                summary["officers_created"] += 1
            else:
                summary["officers_existed"] += 1

        # --- Citizens Registry ---
        for c in CITIZENS:
            existing = await session.execute(
                select(CitizenRegistry).where(
                    CitizenRegistry.document_number == c["document_number"]
                )
            )
            if existing.scalar_one_or_none() is None:
                session.add(CitizenRegistry(**c))
                summary["citizens_created"] += 1
            else:
                summary["citizens_existed"] += 1

        # --- Watchlist ---
        for w in WATCHLIST:
            existing = await session.execute(
                select(WatchlistEntry).where(
                    WatchlistEntry.id_number == w["id_number"]
                )
            )
            if existing.scalar_one_or_none() is None:
                session.add(WatchlistEntry(**w))
                summary["watchlist_created"] += 1
            else:
                summary["watchlist_existed"] += 1

        # --- Audit log: seed event ---
        session.add(AuditLog(
            actor="system",
            action="database_seeded",
            entity="seed",
        ))

        await session.commit()

    return summary


async def reset_and_seed() -> dict:
    """Drop all tables, recreate, and re-seed. For testing only."""
    from backend.database import drop_db
    await drop_db()
    return await seed_all()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("[seed] Seeding database...")
    result = asyncio.run(seed_all())
    print(f"[seed] Done: {result}")
