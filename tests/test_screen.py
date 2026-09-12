import json

from sc_translator.screen import (
    ScreenInfo,
    build_layouts,
    find_screen_for_point,
    logical_rect_to_physical,
    physical_rect_to_logical,
)


def test_single_scaled_monitor_roundtrip():
    screens = [ScreenInfo(0, (0, 0, 1920, 1080), 1.5)]  # 150% 缩放
    layouts = build_layouts(screens)
    assert layouts[0].phys_size == (2880, 1620)
    phys = logical_rect_to_physical(layouts, (100, 200, 640, 360))
    assert phys == {"left": 150, "top": 300, "width": 960, "height": 540}
    back = physical_rect_to_logical(layouts, phys)
    assert back["w"] == 640 and back["h"] == 360


def test_two_monitors_same_scale():
    screens = [
        ScreenInfo(0, (0, 0, 1920, 1080), 1.0),
        ScreenInfo(1, (1920, 0, 1920, 1080), 1.0),
    ]
    layouts = build_layouts(screens)
    by_index = {l.info.index: l for l in layouts}
    assert by_index[0].phys_origin == (0, 0)
    assert by_index[1].phys_origin == (1920, 0)
    # 逻辑坐标从第二块屏取区域
    phys = logical_rect_to_physical(layouts, (2000, 100, 100, 100))
    assert phys["left"] == 2000


def test_mixed_dpi_row_layout_offsets():
    # 主屏 150%，右侧副屏 100%：物理布局应为 0..2880，然后 2880..
    screens = [
        ScreenInfo(0, (0, 0, 1280, 720), 1.5),        # 逻辑宽 1280 -> 物理 1920
        ScreenInfo(1, (1280, 0, 1920, 1080), 1.0),    # Qt 逻辑起点 1280
    ]
    layouts = build_layouts(screens)
    by_index = {l.info.index: l for l in layouts}
    assert by_index[0].phys_origin == (0, 0)
    assert by_index[1].phys_origin == (1920, 0)       # 物理紧邻主屏物理宽
    phys = logical_rect_to_physical(layouts, (1280, 0, 100, 100))  # 副屏逻辑区域
    assert phys["left"] == 1920


def test_find_screen_for_point():
    screens = [ScreenInfo(0, (0, 0, 1920, 1080), 1.0), ScreenInfo(1, (1920, 0, 1920, 1080), 1.0)]
    assert find_screen_for_point(screens, 2000, 500).index == 1
    assert find_screen_for_point(screens, 100, 500).index == 0
    assert find_screen_for_point(screens, 5000, 500) is None
