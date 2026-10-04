"""Railway-safe launcher — reads $PORT in Python so no shell expansion is needed.
Even if the platform runs the start command in exec form (no shell), ${PORT:-8000}
would be passed literally and uvicorn crashes with 'Invalid value for --port'.
This script avoids that by reading os.environ directly."""
import os
import uvicorn

if __name__ == "__main__":
    _raw_port = os.environ.get("PORT", "8000")
    try:
        # Platforms sometimes pass the literal "${PORT:-8000}" (exec form, no
        # shell expansion) — fall back to 8000 instead of crash-looping.
        port = int(str(_raw_port).strip().strip('"').strip("'"))
    except (TypeError, ValueError):
        port = 8000
    if not 1 <= port <= 65535:
        port = 8000
    # Audit C12: only trust X-Forwarded-For when behind a sanitising reverse
    # proxy (Railway/Render/Cloud Run set TRUST_PROXY=1). Otherwise the login
    # throttle and audit IP must use the direct socket peer so clients cannot
    # spoof IPs (see backend/auth_security.client_ip).
    trust_proxy = os.environ.get("TRUST_PROXY", "").lower() in ("1", "true", "yes")
    uvicorn.run(
        "backend.app:app",
        host="0.0.0.0",
        port=port,
        proxy_headers=trust_proxy,
        forwarded_allow_ips="*" if trust_proxy else "127.0.0.1",
    )
