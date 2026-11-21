"""Seal a secret for the current Windows user (DPAPI), so the config file never holds it in
the clear. Other platforms refuse rather than silently storing plaintext."""

from __future__ import annotations

import base64
import ctypes
import sys


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi(data: bytes, protect: bool) -> bytes:
    if sys.platform == "win32":  # spelled as a block so type checkers on Linux skip it
        buf = ctypes.create_string_buffer(data, len(data))
        src = _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        dst = _Blob()
        crypt = ctypes.windll.crypt32
        fn = crypt.CryptProtectData if protect else crypt.CryptUnprotectData
        if not fn(ctypes.byref(src), None, None, None, None, 0, ctypes.byref(dst)):
            raise OSError("DPAPI refused the data (sealed by another Windows user?)")
        try:
            return ctypes.string_at(dst.pbData, dst.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(dst.pbData)
    raise NotImplementedError("secret storage is only implemented on Windows (DPAPI)")


def seal(secret: str) -> str:
    return base64.b64encode(_dpapi(secret.encode(), True)).decode()


def unseal(sealed: str) -> str:
    return _dpapi(base64.b64decode(sealed), False).decode()
