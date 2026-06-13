"""Nesne barındırma — GitHub Pages backend.

MP3 / kapak / feed.xml repo'nun `docs/` klasörüne yazılır; `push_site()` ile
GitHub'a commit+push edilir ve GitHub Pages herkese açık yayınlar.

Gerekli ortam değişkenleri:
    PAGES_BASE_URL   (örn. https://kullanici.github.io/repo)
    GITHUB_TOKEN     (push için PAT)
    GITHUB_USER
    GITHUB_REPO
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .config_loader import get_env, require_env
from .logging_utils import get_logger
from .paths import ROOT

log = get_logger("storage")

DOCS_DIR = ROOT / "docs"


def configured() -> bool:
    return bool(get_env("PAGES_BASE_URL"))


def _base() -> str:
    return require_env("PAGES_BASE_URL").rstrip("/")


def _public_url(key: str) -> str:
    return f"{_base()}/{key.lstrip('/')}"


def ensure_bucket(name: str | None = None) -> None:
    """docs/ klasörünü hazırlar (Pages kaynağı)."""
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    # Pages'in dosyaları Jekyll'siz aynen sunması için .nojekyll
    (DOCS_DIR / ".nojekyll").touch()


def upload(dest_path: str | None = None, local_path: Path | None = None,
           content_type: str = "") -> str:
    """Yerel dosyayı docs/<dest_path>'e kopyalar, public URL döndürür."""
    if dest_path is None or local_path is None:
        raise ValueError("dest_path ve local_path gerekli")
    dest = DOCS_DIR / dest_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(local_path, dest)
    return _public_url(dest_path)


def upload_bytes(dest_path: str, data: bytes, content_type: str = "") -> str:
    """Bellekteki içeriği docs/<dest_path>'e yazar, public URL döndürür."""
    dest = DOCS_DIR / dest_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return _public_url(dest_path)


def push_site(message: str) -> None:
    """docs/ + episodes.json'u GitHub'a commit+push eder (Pages yeniden yayınlar).

    Token .git/config'e yazılmaması için geçici remote URL ile push yapılır.
    """
    token = require_env("GITHUB_TOKEN")
    user = require_env("GITHUB_USER")
    repo = require_env("GITHUB_REPO")
    remote = f"https://x-access-token:{token}@github.com/{user}/{repo}.git"

    def git(*args, **kw):
        return subprocess.run(["git", "-C", str(ROOT), *args],
                              capture_output=True, text=True, **kw)

    git("add", "docs", "episodes.json")
    # Değişiklik yoksa commit hata vermesin
    status = git("status", "--porcelain")
    if not status.stdout.strip():
        log.info("Değişiklik yok, push atlanıyor.")
        return
    c = git("commit", "-m", message)
    if c.returncode != 0 and "nothing to commit" not in (c.stdout + c.stderr):
        log.warning("commit: %s", (c.stdout + c.stderr)[-300:])
    p = git("push", remote, "HEAD:main")
    if p.returncode != 0:
        raise RuntimeError(f"git push başarısız:\n{(p.stdout + p.stderr)[-500:]}")
    log.info("Site GitHub'a push edildi (Pages ~1 dk içinde güncellenir).")
