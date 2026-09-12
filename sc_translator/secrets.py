"""API Key 的本地加密存储。

使用 Windows DPAPI（CryptProtectData / CryptUnprotectData）将密钥加密后落盘，
只有当前 Windows 用户在本机可解密，与参考项目的做法一致。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt

CRYPTPROTECT_UI_FORBIDDEN = 0x1
LOCAL_MACHINE = 0x4  # 不用；保持用户级


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _make_blob(data: bytes) -> DATA_BLOB:
    buf = (ctypes.c_ubyte * len(data))(*data) if data else (ctypes.c_ubyte * 1)(0)
    return DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))


def _blob_bytes(blob: DATA_BLOB) -> bytes:
    n = blob.cbData
    if n == 0:
        return b""
    addr = ctypes.cast(blob.pbData, ctypes.c_void_p).value
    arr = (ctypes.c_ubyte * n).from_address(addr)
    return bytes(arr)


def _free_blob(blob: DATA_BLOB) -> None:
    if blob.pbData:
        ctypes.windll.kernel32.LocalFree(blob.pbData)  # type: ignore[attr-defined]


def dpapi_available() -> bool:
    try:
        return hasattr(ctypes, "windll") and hasattr(ctypes.windll, "crypt32")
    except Exception:
        return False


def protect(data: bytes) -> bytes:
    """加密 bytes -> bytes（进程外可持久化）。"""
    if not dpapi_available():
        raise RuntimeError("Windows DPAPI 不可用")
    pin = _make_blob(data)  # 输入引用 Python 内存，绝不能 LocalFree
    pout = DATA_BLOB()
    ok = ctypes.windll.crypt32.CryptProtectData(  # type: ignore[attr-defined]
        ctypes.byref(pin),
        ctypes.c_wchar_p("SCTranslator api key"),
        None, None, None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(pout),
    )
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return _blob_bytes(pout)
    finally:
        _free_blob(pout)   # 只有输出 blob 由 crypt32 LocalAlloc 分配


def unprotect(data: bytes) -> bytes:
    if not dpapi_available():
        raise RuntimeError("Windows DPAPI 不可用")
    pin = _make_blob(data)
    pout = DATA_BLOB()
    ok = ctypes.windll.crypt32.CryptUnprotectData(  # type: ignore[attr-defined]
        ctypes.byref(pin),
        None, None, None, None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(pout),
    )
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return _blob_bytes(pout)
    finally:
        _free_blob(pout)
