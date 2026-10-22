import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect

from alembic import command
from alembic.config import Config
from tests.conftest import become_creator, new_client, register

BACKEND = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_video_upload_produces_watermarked_preview_and_metadata(tmp_path):
    clip = tmp_path / "clip.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=1920x1080:rate=30",
                    "-t", "3", "-pix_fmt", "yuv420p", str(clip)], check=True)
    c = register(new_client(), "drone@example.com")
    become_creator(c, "drone-op")
    r = c.post("/api/v1/media", data={
        "title": "Aerial test pattern", "category": "aerial_drone", "rights_owner_name": "Drone Op",
        "is_original_author": "true", "accept_declaration": "true",
    }, files={"file": ("clip.mp4", clip.read_bytes(), "video/mp4")})
    assert r.status_code == 202, r.text
    d = c.get(f"/api/v1/media/{r.json()['id']}").json()
    assert d["status"] == "pending_review", d["processing_error"]
    assert d["media_type"] == "video" and d["resolution_label"] == "HD"
    assert round(d["duration_seconds"]) == 3 and d["frame_rate"] == 30
    kinds = {f["kind"]: f for f in d["files"]}
    assert set(kinds) == {"poster", "thumbnail", "preview"}
    assert kinds["preview"]["content_type"] == "video/mp4" and kinds["preview"]["width"] == 960
    assert c.get(kinds["preview"]["url"]).status_code == 200


def test_alembic_migrations_build_the_full_schema():
    db_path = Path(tempfile.mkdtemp()) / "migrate.db"
    url = f"sqlite:///{db_path}"
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    old = os.environ["DATABASE_URL"]
    os.environ["DATABASE_URL"] = url
    from app.core.config import get_settings

    get_settings.cache_clear()
    try:
        command.upgrade(cfg, "head")
        tables = set(inspect(create_engine(url)).get_table_names())
        assert {"users", "media_assets", "rights_grants", "revenue_share_rules", "audit_logs"} <= tables
        command.downgrade(cfg, "base")
        assert set(inspect(create_engine(url)).get_table_names()) <= {"alembic_version"}
    finally:
        os.environ["DATABASE_URL"] = old
        get_settings.cache_clear()
