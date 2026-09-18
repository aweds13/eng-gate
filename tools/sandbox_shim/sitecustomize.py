"""Sandbox-only shim: this DSH sandbox denies access to directories created with mode 0o700.

`tempfile.mkdtemp` / pytest `tmp_path` create directories as 0o700, which the sandbox turns into
"access denied" immediately. Relaxing 0o700 -> 0o755 keeps pytest usable.

This file is NOT part of the timeflow project and must not be imported by application code.
Usage:  $env:PYTHONPATH = "<repo>\\tools\\sandbox_shim"; python -m pytest ...
"""

from __future__ import annotations

import os

_orig_mkdir = os.mkdir


def _mkdir(path, mode=0o777, *args, **kwargs):  # type: ignore[no-untyped-def]
    if mode == 0o700:
        mode = 0o755
    return _orig_mkdir(path, mode, *args, **kwargs)


os.mkdir = _mkdir
