
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

    dotenv = Path(__file__).resolve().parent.parent / ".env"
    if dotenv.is_file():
        for line in dotenv.read_text().splitlines():
            line = line.strip()
            if line.startswith("REGISTRY_IMPORT_SECRET="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("REGISTRY_IMPORT_SECRET not found: pass --secret or set the env var.")


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
    if not isinstance(payload, dict) or not payload.get("batch_ref") or not isinstance(payload.get("records"), list):
        raise SystemExit("Batch must be {batch_ref: str, records: [...]}")


    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    secret = _load_secret(args.secret)
    sig = hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()

    if args.quiet:
        print(sig)
        return 0

    out = Path(args.batch_file).with_suffix(".canonical.json")
    out.write_bytes(canonical)
    print(f"canonical body : {out} ({len(canonical)} bytes)")
    print(f"records        : {len(payload['records'])}  batch: {payload['batch_ref']}")
    print(f"X-Import-Signature: {sig}")
    print("POST the canonical file bytes unchanged with that header.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
