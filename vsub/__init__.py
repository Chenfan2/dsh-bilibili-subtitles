"""Bilibili subtitle to document skill."""

from __future__ import annotations

import os

__version__ = "0.2.0"

# Must happen before optional libraries (huggingface_hub, faster-whisper) import
# ``tempfile`` symbols.  See compat.py for the Windows sandbox workaround.
if os.name == "nt":
    from .compat import install_safe_tempdir

    try:
        install_safe_tempdir()
    except Exception:
        pass

