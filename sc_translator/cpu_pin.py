"""CPU 亲和：把进程绑定到最不抢游戏资源的逻辑核上（OCR/后台负载）。

规则（按用户要求）：
- 有大小核之分时：**固定 1 个小核/效率核**（EfficiencyClass 最小者）；
- 没有小核（单一效率等级）时：**最多占 2 个逻辑处理器**，且必须来自**不同物理核**
  （绝不取同一物理核的两个超线程）；
- **严禁占用整个 CPU**：若选出的掩码等于系统允许的全部逻辑处理器（例如整机只有 1~2 个逻辑核），
  则放弃绑定，而不是独占整机；
- 取不到拓扑信息时退回"系统允许掩码里编号最低的单个逻辑核"；
- 绑定失败只记日志、不影响运行。

实测（本机 i5-14600KF，6P+8E / 20 逻辑核）：E-core 的 EfficiencyClass=0（8 个物理核、每核 1 逻辑核），
P-core 的 EfficiencyClass=1（6 个物理核、每核 2 逻辑核）——所以"取最小"就是固定小核。

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

# 没有小核时的上限：最多占几个逻辑处理器（用户要求 ≤2）
FALLBACK_MAX_LOGICAL = 2

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
        # PROCESSOR_RELATIONSHIP 布局（winnt.h，相对联合体起点 body = off+8）：
        #   Flags(1) + EfficiencyClass(1) + Reserved[20] + GroupCount(2) + GroupMask[0]{Mask(8), Group(2)}
        #   => GroupCount @ body+22、GroupMask[0].Mask @ body+24、GroupMask[0].Group @ body+32
        # 旧实现把 Mask 起点写成 off+29（早 3 字节），读出的值 = 真实掩码<<24 | GroupCount<<8，
        # 于是每个核都多出一个假 bit 8、真实掩码还丢高位 —— 结果是"固定小核"实际固定到了逻辑核 8
        # （本机逻辑核 8 属 P-core），正是要避开的大核。此处按真实布局修正。
        body = off + 8
        if rel == RELATION_PROCESSOR_CORE and body + 34 <= len(blob):
            efficiency = blob[body + 1]
            mask = int.from_bytes(blob[body + 24:body + 32], "little")
            group = int.from_bytes(blob[body + 32:body + 34], "little")
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


def _one_bit_per_core(cores: list[tuple[int, int]], allowed: int, limit: int) -> int:
    """每个物理核只取 1 个逻辑处理器（**绝不取同一物理核的两个超线程**），最多 limit 个。

    按各核掩码里最低逻辑核编号排序，结果稳定可预期。返回合并后的掩码（可能为 0）。
    """
    picked = 0
    taken = 0
    for _, m in sorted(cores, key=lambda c: _lowest_bit_index(c[1])):
        avail = m & allowed
        one = avail & -avail              # 该物理核里编号最低的那个逻辑处理器
        if not one or (one & picked):
            continue
        picked |= one
        taken += 1
        if taken >= max(1, limit):
            break
    return picked


def _choose_mask(prefer_efficient: bool) -> tuple[int, str]:
    """返回 (affinity_mask, 说明)。

    - 有大小核之分且 ``prefer_efficient``：**固定 1 个小核**（EfficiencyClass 最小者）；
    - 否则（无小核）：最多占 ``FALLBACK_MAX_LOGICAL`` 个逻辑处理器，且来自**不同物理核**；
    - 任何情况下都不返回"等于整机允许掩码"的结果（**严禁占用整个 CPU**）。
    """
    cores = _query_cores()
    allowed = _system_allowed_mask()
    if allowed == 0:
        return 0, ""
    if not cores:
        # 拿不到等级信息：绑系统允许掩码里编号最低的逻辑核
        m = allowed & -allowed
        return m, f"逻辑核 {_lowest_bit_index(m)}（无等级信息，按编号最低）"

    classes = sorted({e for e, _ in cores})
    hybrid = len(classes) > 1
    if prefer_efficient and hybrid:
        target_class = min(classes)       # 实测：小核(E-core) 的 EfficiencyClass 更小
        cands = [(e, m) for e, m in cores if e == target_class]
        kind = "小核/效率核"
        limit = 1                         # 固定小核：只占 1 个逻辑处理器
    else:
        target_class = -1
        cands = list(cores)
        kind = "普通核"
        limit = FALLBACK_MAX_LOGICAL      # 没有小核：最多 2 个，且来自不同物理核

    mask = _one_bit_per_core(cands, allowed, limit)
    if mask == 0:
        mask = allowed & -allowed
    if mask == allowed:
        # 严禁占用整个 CPU：整机逻辑处理器数不超过上面的限额时，宁可不绑定
        log.info("系统仅 %d 个逻辑处理器，放弃绑定以免独占整个 CPU", bin(allowed).count("1"))
        return 0, ""
    cpus = [i for i in range(64) if mask >> i & 1]
    return mask, f"{kind}（EfficiencyClass={target_class}）逻辑核 {cpus}"


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


def apply_from_settings(pin_enabled: bool, prefer_efficient: bool = True) -> str:
    if not pin_enabled:
        log.info("CPU 绑定未开启")
        return ""
    return apply_pin(prefer_efficient=prefer_efficient)


def clear_pin() -> bool:
    """解除绑定：把进程亲和性恢复到**系统允许的全部逻辑核**。

    进程/线程掩码一旦被收紧，只有显式放宽才能恢复（关掉界面开关时必须调用）。
    """
    if _k32 is None:
        return False
    if not _prepared and not _prepare():
        return False
    sysm = _system_allowed_mask()
    if not sysm:
        log.warning("解除 CPU 绑定失败：未取得系统允许掩码")
        return False
    if not _k32.SetProcessAffinityMask(wintypes.HANDLE(-1), _ULONG_PTR(sysm)):
        log.warning("SetProcessAffinityMask(解除) 失败：%s", ctypes.get_last_error())
        return False
    log.info("已解除 CPU 绑定：恢复为系统允许的 %d 个逻辑核", bin(sysm).count("1"))
    return True
