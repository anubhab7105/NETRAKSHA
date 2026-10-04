"""Sign a master-registry authority import batch (HMAC-SHA256).

The issuing authority (or the operator acting for it) builds the exact JSON
body that will be POSTed to /api/citizens/import, signs the raw bytes with
REGISTRY_IMPORT_SECRET, and sends the hex digest as the X-Import-Signature
header. The server recomputes the HMAC over the received bytes — so sign the
exact bytes you send (no pretty-print drift: use the canonical output file).

Usage:
    python scripts/sign_registry_import.py batch.json [--secret ENV_OR_VALUE]

    # batch.json shape:
    # {"batch_ref": "UIDAI-2026-09-001",
    #  "records": [{"document_type": "aadhaar", "document_number": "...",
    #               "full_name": "...", ...}]}

    # 1) canonicalize + sign (writes batch.canonical.json + prints header):
    python scripts/sign_registry_import.py batch.json

    # 2) send (PowerShell):
    # $sig = python scripts/sign_registry_import.py batch.canonical.json --quiet
    # Invoke-RestMethod -Uri "$API/api/citizens/import" -Method Post `
    #   -Headers @{Authorization="Bearer $TOKEN"; "X-Import-Signature"=$sig} `
    #   -ContentType "application/json" -InFile batch.canonical.json

The secret is read from --secret, else the REGISTRY_IMPORT_SECRET env var,
else the root .env file. It is never printed except as the HMAC digest.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
from pathlib import Path


def _load_secret(explicit: str | None) -> str:
    if explicit and not explicit.startswith("@"):
        return explicit
    if explicit and explicit.startswith("@"):
        return Path(explicit[1:]).read_text().strip()
    env = os.environ.get("REGISTRY_IMPORT_SECRET", "").strip()
    if env:
        return env

    # Minimal .env parser (no dependency): KEY=VALUE, skips blanks/comments,
    # strips matching single/double quotes. For full dotenv semantics use
    # python-dotenv; this covers the generated root .env shape.
    dotenv = Path(__file__).resolve().parent.parent / ".env"
    if dotenv.is_file():
        for line in dotenv.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            if key.strip() != "REGISTRY_IMPORT_SECRET":
                continue
            val = val.strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
                val = val[1:-1]
            # tolerate `export KEY=...`
            return val.strip()
    raise SystemExit("REGISTRY_IMPORT_SECRET not found: pass --secret or set the env var.")


# Caps: the import endpoint pages in memory — refuse absurd batches early.
MAX_RECORDS = 5000
REQUIRED_RECORD_KEYS = ("document_type", "document_number", "full_name")


def _validate_batch(payload: dict) -> list:
    if not isinstance(payload, dict) or not payload.get("batch_ref") or not isinstance(payload.get("records"), list):
        raise SystemExit("Batch must be {batch_ref: str, records: [...]}")
    records = payload["records"]
    if len(records) > MAX_RECORDS:
        raise SystemExit(f"Batch too large: {len(records)} records (max {MAX_RECORDS}). Split it.")
    for i, rec in enumerate(records):
        if not isinstance(rec, dict):
            raise SystemExit(f"records[{i}]: must be an object")
        missing = [k for k in REQUIRED_RECORD_KEYS if not rec.get(k)]
        if missing:
            raise SystemExit(f"records[{i}]: missing required keys: {', '.join(missing)}")
    return records


def main() -> int:
    ap = argparse.ArgumentParser(description="Sign a registry authority-import batch.")
    ap.add_argument("batch_file", help="JSON file with {batch_ref, records}")
    ap.add_argument("--secret", default=None, help="HMAC secret or @file; default: env/.env")
    ap.add_argument("--quiet", action="store_true", help="Print only the hex signature")
    args = ap.parse_args()

    raw_in = Path(args.batch_file).read_bytes()
    try:
        payload = json.loads(raw_in.decode())
    except Exception as e:
        raise SystemExit(f"Invalid JSON in {args.batch_file}: {e}")
    records = _validate_batch(payload)


    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    secret = _load_secret(args.secret)
    sig = hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()

    if args.quiet:
        print(sig)
        return 0

    out = Path(args.batch_file).with_suffix(".canonical.json")
    out.write_bytes(canonical)
    print(f"canonical body : {out} ({len(canonical)} bytes)")
    print(f"records        : {len(records)}  batch: {payload['batch_ref']}")
    print(f"X-Import-Signature: {sig}")
    print("POST the canonical file bytes unchanged with that header.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
