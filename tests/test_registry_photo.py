"""Tests for registry reference-photo resolution (backend.app._resolve_db_photo).

Citizen `photo_uri` values may be server-local paths (legacy seed rows) or
remote Supabase Storage signed URLs (real enrollments). The resolver must
turn both into a local file for the 3-way face matcher — and degrade with
an explicit reason, never raise.
"""

from __future__ import annotations

import functools
import pathlib
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

SAMPLES = pathlib.Path(__file__).resolve().parent.parent / "samples"
FACE_A = SAMPLES / "faces" / "person_a.png"


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture()
def file_server():
    """Serve samples/ over loopback HTTP (stands in for Supabase Storage)."""
    handler = functools.partial(_QuietHandler, directory=str(SAMPLES))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{srv.server_port}"
    finally:
        srv.shutdown()


def test_blank_uri_has_explicit_reason():
    from backend.app import _resolve_db_photo

    assert _resolve_db_photo(None) == (None, "no_registry_photo")
    assert _resolve_db_photo("   ") == (None, "no_registry_photo")


def test_local_path_passthrough():
    from backend.app import _resolve_db_photo

    path, reason = _resolve_db_photo(str(FACE_A), citizen_id=9001)
    assert reason is None
    assert path and pathlib.Path(path).is_file()


def test_missing_local_path_reports_server_reason():
    from backend.app import _resolve_db_photo

    path, reason = _resolve_db_photo("samples/faces/does_not_exist.png", citizen_id=9002)
    assert path is None
    assert reason == "registry_photo_missing_on_server"


def test_unreachable_url_degrades_with_reason():
    from backend.app import _resolve_db_photo


    path, reason = _resolve_db_photo("http://127.0.0.1:9/missing.jpg", citizen_id=9003)
    assert path is None
    assert reason == "registry_photo_download_failed"


def test_remote_url_downloads_and_caches(file_server):
    from backend.app import _resolve_db_photo

    url = f"{file_server}/faces/person_a.png"
    path, reason = _resolve_db_photo(url, citizen_id=9004)
    assert reason is None
    assert path and pathlib.Path(path).is_file()
    assert pathlib.Path(path).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"

    path2, reason2 = _resolve_db_photo(url, citizen_id=9004)
    assert (path2, reason2) == (path, None)


def test_remote_non_image_is_rejected(file_server):
    from backend.app import _resolve_db_photo

    url = f"{file_server}/../requirements.txt"
    path, reason = _resolve_db_photo(url, citizen_id=9005)
    assert path is None
    assert reason == "registry_photo_download_failed"


def test_registry_photo_rejects_path_traversal_and_symlinks(tmp_path):
    from backend.app import _resolve_db_photo, _safe_registry_photo_path

    dangerous = tmp_path / "escape" / "nested"
    dangerous.mkdir(parents=True)
    payload = dangerous / "secret.txt"
    payload.write_text("top-secret", encoding="utf-8")

    assert _safe_registry_photo_path("../requirements.txt") is None
    assert _safe_registry_photo_path("/etc/passwd") is None
    assert _resolve_db_photo("../requirements.txt", citizen_id=9006) == (None, "registry_photo_missing_on_server")

    link = tmp_path / "link_to_secret"
    try:
        link.symlink_to(payload)
    except (NotImplementedError, OSError):
        link = None
    if link is not None:
        assert _safe_registry_photo_path(str(link)) is None
