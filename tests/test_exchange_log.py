"""交换日志：用户输入与模型输出记录测试。"""

from sc_translator import exchange_log


def test_record_writes_input_output(tmp_home):
    exchange_log.reset()
    exchange_log.record("reply", "deepseek-v4-flash", "有人在吗，谁来救救我", out="Is anyone here? Help me!")
    exchange_log.record("realtime", "deepseek-chat", "Quantum travel", error="HTTP 401: bad key")
    exchange_log.reset()
    logfile = tmp_home / "logs" / "exchange.log"
    content = logfile.read_text(encoding="utf-8")
    assert "[kind=reply model=deepseek-v4-flash style=normal cached=False ok=True]" in content
    assert "有人在吗，谁来救救我" in content
    assert "Is anyone here? Help me!" in content
    assert "[kind=realtime model=deepseek-chat" in content
    assert "HTTP 401" in content


def test_record_never_raises(tmp_home):
    exchange_log.reset()
    exchange_log.record("reply", None, "x", out=None)  # 异常参数也不应抛错
    exchange_log.reset()
