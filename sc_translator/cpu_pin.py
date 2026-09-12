"""CPU 亲和：把进程强制绑定到单个逻辑核，混合架构优先绑定小核(E-core/效率核)。

背景：OCR/采样属于后台负载，默认会散布到所有逻辑核（含大核），
在游戏机上会与大核上跑的游戏抢资源。这里把整个进程钉在一个核上：
- 优先挑选 EfficiencyClass 最小的核（小核/效率核，如 Intel E-core）；
- 只有单一效率等级（普通 CPU）时绑定任意一个核；
- 绑定范围取系统当前允许的掩码的交集，失败只记日志、不影响运行。

可用环境变量：
  SC_TRANSLATOR_CPU_PIN=0   关闭（配合设置开关）
"""

from __future__ import annotations

import ctypes
import logging
import os
from ctypes import wintypes

log = logging.getLogger(__name__)

RELATION_PROCESSOR_CORE = 0
ERROR_INSUFFICIENT_BUFFER = 122

_k32 = ctypes.windll.kernel32 if hasattr(ctypes, "windll") and hasattr(ctypes.windll, "kernel32") else None

_ULONG_PTR = ctypes.c_size_t
_glpiex = None  # GetLogicalProcessorInformationEx 函数对象(use_last_error=True)


def _prepare() -> bool:
    global _glpiex
    if _k32 is None:
        return False
    try:
        # 显式签名，避免 64 位指针截断；带 use_last_error 以便读取 ERROR_INSUFFICIENT_BUFFER
        proto = ctypes.WINFUNCTYPE(
            wintypes.BOOL,
            ctypes.c_uint,
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.DWORD),
            use_last_error=True,
        )
        _glpiex = proto(("GetLogicalProcessorInformationEx", _k32))
        _k32.GetProcessAffinityMask.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ULONG_PTR), ctypes.POINTER(_ULONG_PTR)]
        _k32.GetProcessAffinityMask.restype = wintypes.BOOL
        _k32.SetProcessAffinityMask.argtypes = [wintypes.HANDLE, _ULONG_PTR]
        _k32.SetProcessAffinityMask.restype = wintypes.BOOL
        return True
    except Exception:  # noqa: BLE001
        return False


_prepared = False


def _query_cores() -> list[tuple[int, int]]:
    """返回 [(efficiency_class, affinity_mask), ...]（仅 group 0 的逻辑核）。"""
    global _prepared
    kernel32 = _k32
    if kernel32 is None:
        return []
    if not _prepared:
        _prepared = _prepare()
    if not _prepared:
        return []
    needed = wintypes.DWORD()
    # 第一次：只取所需大小（期望返回 false + ERROR_INSUFFICIENT_BUFFER=122）
    _glpiex(RELATION_PROCESSOR_CORE, None, ctypes.byref(needed))
    if needed.value == 0:
        log.warning("GetLogicalProcessorInformationEx 未返回所需大小（err=%s）", ctypes.get_last_error())
        return []
    size = wintypes.DWORD(needed.value)
    data = ctypes.create_string_buffer(size.value)
    if not _glpiex(RELATION_PROCESSOR_CORE, data, ctypes.byref(size)):
        log.warning("GetLogicalProcessorInformationEx 查询失败 err=%s", ctypes.get_last_error())
        return []
    blob = data.raw
    cores: list[tuple[int, int]] = []
    off = 0
    while off + 8 <= len(blob):
        rel = int.from_bytes(blob[off:off + 4], "little")
        rec_size = int.from_bytes(blob[off + 4:off + 8], "little")
        if rel == RELATION_PROCESSOR_CORE and off + 9 < len(blob):
            efficiency = blob[off + 9]                       # Flags@+8, EfficiencyClass@+9
            grp_off = off + 8 + 1 + 20                       # PROCESSOR_RELATIONSHIP 后接 GROUP_AFFINITY
            if grp_off + 10 <= len(blob):
                mask = int.from_bytes(blob[grp_off:grp_off + 8], "little")
                group = int.from_bytes(blob[grp_off + 8:grp_off + 10], "little")
                if group == 0 and mask:
                    cores.append((efficiency, mask))
        if rec_size < 8:
            break
        off += rec_size
    return cores


def _system_allowed_mask() -> int:
    if _k32 is None or not _prepared and not _prepare():
        return 0
    proc = _ULONG_PTR(0)
    sysm = _ULONG_PTR(0)
    if not _k32.GetProcessAffinityMask(wintypes.HANDLE(-1), ctypes.byref(proc), ctypes.byref(sysm)):
        return 0
    return int(sysm.value)


def _lowest_bit_index(mask: int) -> int:
    m = mask & -mask
    return m.bit_length() - 1 if m else -1


def _choose_mask(prefer_efficient: bool) -> tuple[int, str]:
    """返回 (affinity_mask, 说明)。"""
    cores = _query_cores()
    allowed = _system_allowed_mask()
    if not cores:
        # 拿不到等级信息：绑系统允许掩码里编号最低的逻辑核
        m = allowed & -allowed
        return m, f"逻辑核 {_lowest_bit_index(m)}（无等级信息，按编号最低）"
    if prefer_efficient:
        classes = sorted({e for e, _ in cores})
        target_class = min(classes)  # 混合 CPU 中小核(E-core)的 EfficiencyClass 更低
    else:
        target_class = -1
    cands = [m for e, m in cores if e == target_class] if target_class >= 0 else [m for _, m in cores]
    # 在该等级里选掩码编号最低的一个核
    m = cands[0]
    for c in cands[1:]:
        if _lowest_bit_index(c) < _lowest_bit_index(m):
            m = c
    final = m & allowed
    if final == 0:
        final = allowed & -allowed
    # 即便核心含超线程两个逻辑处理器，也只绑编号最低的那一个逻辑核
    final = final & -final
    kind = "小核/效率核" if prefer_efficient and len({e for e, _ in cores}) > 1 else "普通核"
    return final, f"{kind}（EfficiencyClass={target_class}）逻辑核 {_lowest_bit_index(final)}"


def apply_pin(prefer_efficient: bool = True) -> str:
    """把当前进程绑定到单个核。返回描述信息；失败返回空字符串（不影响运行）。"""
    if os.environ.get("SC_TRANSLATOR_CPU_PIN", "") == "0":
        log.info("CPU 绑定已通过环境变量关闭")
        return ""
    if _k32 is None:
        return ""
    if not _prepared:
        _prepare()
    mask, desc = _choose_mask(prefer_efficient)
    if mask <= 0:
        log.warning("CPU 绑定失败：未取得有效掩码")
        return ""
    cur = wintypes.HANDLE(-1)  # GetCurrentProcess
    if not _k32.SetProcessAffinityMask(cur, _ULONG_PTR(mask)):
        log.warning("SetProcessAffinityMask 失败：%s", ctypes.get_last_error())
        return ""
    log.info("已把进程绑定到单个 %s", desc)
    return desc


def allow_current_thread() -> None:
    """把【当前线程】放宽到系统允许的全部核（绕过进程单核绑定）。

    用于翻译 worker：本地模型推理需要多核才快，而采样线程保持单小核低占用。
    """
    if _k32 is None:
        return
    try:
        if not _prepared:
            _prepare()
        sysm = _system_allowed_mask()
        if sysm:
            # GetCurrentThread 句柄为 (HANDLE)-2
            _k32.SetThreadAffinityMask(wintypes.HANDLE(-2), _ULONG_PTR(sysm))
    except Exception:  # noqa: BLE001
        pass


def apply_from_settings(pin_enabled: bool, prefer_efficient: bool = True) -> str:
    if not pin_enabled:
        log.info("CPU 绑定未开启")
        return ""
    return apply_pin(prefer_efficient=prefer_efficient)
