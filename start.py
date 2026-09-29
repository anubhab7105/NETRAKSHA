"""Railway-safe launcher — reads $PORT in Python so no shell expansion is needed.
Even if the platform runs the start command in exec form (no shell), ${PORT:-8000}
would be passed literally and uvicorn crashes with 'Invalid value for --port'.
This script avoids that by reading os.environ directly."""
import os
import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("backend.app:app", host="0.0.0.0", port=port)
