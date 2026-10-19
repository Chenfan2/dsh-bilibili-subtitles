"""Windows sandbox compatibility helpers.

Python's ``tempfile.mkdtemp`` creates a directory and then applies mode 0700.
In the DSH Windows sandbox, the resulting directory can lose the inherited
sandbox ACE, so subsequent writes fail with ``PermissionError``.  Third-party
libraries (huggingface_hub, pip, ...) use temp directories internally, which
breaks model downloads.

We replace ``mkdtemp``/``TemporaryDirectory`` with a version that creates a
normal inherited-ACL directory.  This is only installed on Windows and is a
no-op elsewhere.
"""

from __future__ import annotations

import os
import secrets
import shutil
import tempfile
from pathlib import Path


def _unique_name(prefix: str | None, suffix: str | None) -> str:
    return f"{prefix or 'tmp'}{secrets.token_hex(6)}{suffix or ''}"


def safe_mkdtemp(suffix: str | None = None, prefix: str | None = None, dir: str | None = None) -> str:
    base = Path(dir or tempfile.gettempdir())
    base.mkdir(parents=True, exist_ok=True)
    for _ in range(50):
        path = base / _unique_name(prefix, suffix)
        try:
            path.mkdir(parents=False, exist_ok=False)
            return str(path)
        except FileExistsError:
            continue
    raise FileExistsError(f"无法在 {base} 创建唯一临时目录")


class SafeTemporaryDirectory:
    def __init__(
        self,
        suffix: str | None = None,
        prefix: str | None = None,
        dir: str | None = None,
        ignore_cleanup_errors: bool = False,
        *,
        delete: bool = True,
    ):
        self.name = safe_mkdtemp(suffix=suffix, prefix=prefix, dir=dir)
        self._ignore_cleanup_errors = ignore_cleanup_errors
        self._delete = delete

    def __enter__(self) -> str:
        return self.name

    def __exit__(self, exc_type, exc, tb) -> None:
        self.cleanup()

    def cleanup(self) -> None:
        if self._delete:
            shutil.rmtree(self.name, ignore_errors=self._ignore_cleanup_errors or True)

    def __del__(self):  # pragma: no cover - best effort
        try:
            self.cleanup()
        except Exception:
            pass


_installed = False


def install_safe_tempdir(base: str | Path | None = None) -> None:
    global _installed
    if os.name != "nt":
        return
    if base:
        path = Path(base)
        path.mkdir(parents=True, exist_ok=True)
        tempfile.tempdir = str(path)
    if _installed:
        return
    tempfile.mkdtemp = safe_mkdtemp  # type: ignore[assignment]
    tempfile.TemporaryDirectory = SafeTemporaryDirectory  # type: ignore[assignment,misc]
    _installed = True
