"""How busy is this machine right now? Free RAM and CPU load, read from Windows with the standard library only (ctypes).

Used by the OPTIONAL start-up warm-up to decide whether loading the language model is polite. On any other platform, or when a
reading fails, a function returns None and the caller must treat "unknown" as "do not warm up".
"""
from __future__ import annotations

import ctypes
import sys
import time


class _MemoryStatus(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong), ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]


class _FileTime(ctypes.Structure):
    _fields_ = [("low", ctypes.c_ulong), ("high", ctypes.c_ulong)]

    @property
    def value(self) -> int:
        return (self.high << 32) | self.low


def free_ram_mb() -> int | None:
    """Physical memory available to start programs, in MB (None when it cannot be read)."""
    if sys.platform != "win32":
        return None
    try:
        st = _MemoryStatus()
        st.dwLength = ctypes.sizeof(_MemoryStatus)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):  # type: ignore[attr-defined]
            return None
        return int(st.ullAvailPhys // (1024 * 1024))
    except Exception:
        return None


def cpu_busy_fraction(sample_s: float = 0.5) -> float | None:
    """System-wide CPU use over `sample_s` seconds, 0..1 (None when it cannot be read). Blocks for `sample_s`."""
    if sys.platform != "win32":
        return None
    try:
        idle, kernel, user = _FileTime(), _FileTime(), _FileTime()
        read = ctypes.windll.kernel32.GetSystemTimes  # type: ignore[attr-defined]
        if not read(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
            return None
        i0, k0, u0 = idle.value, kernel.value, user.value
        time.sleep(sample_s)
        if not read(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
            return None
        total = (kernel.value - k0) + (user.value - u0)  # kernel time includes idle time
        if total <= 0:
            return None
        return max(0.0, min(1.0, 1.0 - (idle.value - i0) / total))
    except Exception:
        return None
