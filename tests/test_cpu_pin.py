"""CPU 亲和回归：拓扑解析偏移、固定小核、无小核时 ≤2 且不占整个 CPU。

全部用注入的假拓扑，不依赖本机真实 CPU 型号，也不真的改进程亲和性。
"""

from __future__ import annotations

import ctypes

import pytest

from sc_translator import cpu_pin

# PROCESSOR_RELATIONSHIP 记录大小（GroupCount=1 时）：8 字节头 + 1+1+20+2+8+2+6
_REC_SIZE = 48


def _rec(efficiency: int, mask: int, group: int = 0) -> bytes:
    """构造一条 SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX（RelationProcessorCore）。"""
    b = bytearray(_REC_SIZE)
    b[0:4] = (cpu_pin.RELATION_PROCESSOR_CORE).to_bytes(4, "little")   # Relationship
    b[4:8] = _REC_SIZE.to_bytes(4, "little")                          # Size
    b[8] = 0                                                          # Flags
    b[9] = efficiency                                                 # EfficiencyClass
    b[30:32] = (1).to_bytes(2, "little")                              # GroupCount
    b[32:40] = mask.to_bytes(8, "little")                             # GroupMask[0].Mask
    b[40:42] = group.to_bytes(2, "little")                            # GroupMask[0].Group
    return bytes(b)


def _fake_glpiex(blob: bytes):
    """替身：第一次调用回填所需字节数，第二次把 blob 拷进缓冲区。"""

    def fake(relation, buf, size_ptr):
        if buf is None:
            size_ptr._obj.value = len(blob)      # noqa: SLF001 (ctypes 惯用法)
            return 0
        ctypes.memmove(buf, blob, len(blob))
        return 1

    return fake


# ------------------------------------------------------------ 拓扑解析
def test_query_cores_parses_real_struct_offsets(monkeypatch):
    """回归：掩码必须按 PROCESSOR_RELATIONSHIP 真实偏移解析。

    旧实现把 GroupMask 起点算早 3 字节 => 掩码整体左移 24 位并混入 GroupCount（每核多一个 bit 8），
    真机上表现为"固定小核"却固定到逻辑核 8（P-core）。
    """
    blob = _rec(0, 0x001000) + _rec(0, 0x002000) + _rec(1, 0x000003) + _rec(1, 0x00000C)
    monkeypatch.setattr(cpu_pin, "_glpiex", _fake_glpiex(blob))
    monkeypatch.setattr(cpu_pin, "_prepared", True)
    cores = cpu_pin._query_cores()
    assert cores == [(0, 0x1000), (0, 0x2000), (1, 0x3), (1, 0xC)], cores
    # 关键反例：不得出现"每核都带 bit 8"的污染值
    assert all(m & 0x100 == 0 for _, m in cores), cores


def test_query_cores_skips_other_groups(monkeypatch):
    """只认 group 0（跨处理器组的掩码不能直接比较）。"""
    blob = _rec(0, 0x1000) + _rec(0, 0x2000, group=1)
    monkeypatch.setattr(cpu_pin, "_glpiex", _fake_glpiex(blob))
    monkeypatch.setattr(cpu_pin, "_prepared", True)
    assert cpu_pin._query_cores() == [(0, 0x1000)]


# ------------------------------------------------------------ 选择规则
HYBRID = [(0, 0x1000), (0, 0x2000), (1, 0x3), (1, 0xC)]   # 2 个小核(单逻辑) + 2 个大核(双逻辑)


def _patch(monkeypatch, cores, allowed):
    monkeypatch.setattr(cpu_pin, "_query_cores", lambda: list(cores))
    monkeypatch.setattr(cpu_pin, "_system_allowed_mask", lambda: allowed)


def test_pins_one_efficiency_core_when_hybrid(monkeypatch):
    """有大小核：固定 1 个 EfficiencyClass 最小的核，且只占它的 1 个逻辑处理器。"""
    _patch(monkeypatch, HYBRID, 0xF000 | 0x3 | 0xC)
    mask, desc = cpu_pin._choose_mask(prefer_efficient=True)
    assert mask == 0x1000, desc
    assert bin(mask).count("1") == 1
    assert "小核" in desc and "逻辑核 [12]" in desc


def test_no_small_core_takes_at_most_two_logical_from_distinct_cores(monkeypatch):
    """无小核（单一效率等级）：最多 2 个逻辑处理器，且来自**不同物理核**（不占整个物理核）。"""
    _patch(monkeypatch, [(5, 0x3), (5, 0xC), (5, 0x30)], 0x3F)
    mask, desc = cpu_pin._choose_mask(prefer_efficient=True)
    assert bin(mask).count("1") == 2, desc
    assert mask == 0x5, desc          # 核{0,1}取 0、核{2,3}取 2
    assert "普通核" in desc


def test_never_takes_the_whole_cpu(monkeypatch):
    """严禁占用整个 CPU：宁可取少，也不让掩码等于整机允许掩码。"""
    # 1 个物理核 / 2 个逻辑核：只取其中 1 个（不占满整机）
    _patch(monkeypatch, [(0, 0x3)], 0x3)
    mask, desc = cpu_pin._choose_mask(prefer_efficient=True)
    assert mask == 0x1 and mask != 0x3, desc

    # 整机只有 1 个逻辑核：任何绑定都等于独占 -> 放弃绑定
    _patch(monkeypatch, [(0, 0x1)], 0x1)
    mask2, _ = cpu_pin._choose_mask(prefer_efficient=True)
    assert mask2 == 0, "只有 1 个逻辑核时不应绑定"

    # 整机 4 个逻辑核、单一等级 -> 允许取 2 个（不等于整机）
    _patch(monkeypatch, [(5, 0x3), (5, 0xC)], 0xF)
    mask3, desc3 = cpu_pin._choose_mask(prefer_efficient=True)
    assert bin(mask3).count("1") == 2 and mask3 != 0xF, desc3


def test_single_logical_core_per_physical_core(monkeypatch):
    """即便某个物理核有 2 个超线程，也绝不把两个都选进掩码。"""
    _patch(monkeypatch, [(5, 0x3)], 0xFF)
    mask, desc = cpu_pin._choose_mask(prefer_efficient=True)
    assert bin(mask).count("1") == 1, desc
    assert mask in (0x1, 0x2), desc


def test_falls_back_when_no_topology(monkeypatch):
    """拿不到拓扑信息：退回系统允许掩码里编号最低的单个逻辑核。"""
    _patch(monkeypatch, [], 0x30)
    mask, desc = cpu_pin._choose_mask(prefer_efficient=True)
    assert mask == 0x10 and "无等级信息" in desc


def test_returns_zero_when_no_allowed_mask(monkeypatch):
    _patch(monkeypatch, HYBRID, 0)
    assert cpu_pin._choose_mask(prefer_efficient=True) == (0, "")


def test_apply_pin_honours_env_off(monkeypatch):
    """SC_TRANSLATOR_CPU_PIN=0 时不绑定。"""
    monkeypatch.setenv("SC_TRANSLATOR_CPU_PIN", "0")
    called = []
    monkeypatch.setattr(cpu_pin, "_choose_mask", lambda prefer: called.append(prefer) or (1, "x"))
    assert cpu_pin.apply_pin(True) == ""
    assert called == [], "关闭时不应再去选核"


def test_apply_from_settings_off(monkeypatch):
    assert cpu_pin.apply_from_settings(False) == ""


@pytest.mark.skipif(not hasattr(ctypes, "windll"), reason="仅 Windows 有 SetProcessAffinityMask")
def test_real_machine_choice_is_sane():
    """真机冒烟：选出的掩码非空、属于允许集合、且不等于整机掩码。"""
    allowed = cpu_pin._system_allowed_mask()
    if allowed == 0:                     # 非 Windows / 拿不到信息
        pytest.skip("拿不到系统允许掩码")
    mask, desc = cpu_pin._choose_mask(prefer_efficient=True)
    assert mask != 0 and desc
    assert mask & ~allowed == 0, desc     # 不得越出系统允许范围
    assert mask != allowed, desc          # 严禁占用整个 CPU
