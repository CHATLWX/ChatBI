from pathlib import Path


HTML = Path(__file__).parents[1] / "static" / "index.html"


def test_lesson_11_sse_event_contract_is_consumed_by_frontend():
    source = HTML.read_text(encoding="utf-8")

    assert "type === 'sql_chunk'" in source
    assert "type === 'sql_done'" in source
    assert "buffer.split('\\n\\n')" in source
    assert "if (!payload.content) continue" in source


def test_lesson_12_experience_closure_is_present():
    source = HTML.read_text(encoding="utf-8")

    assert 'id="chatHistory"' in source
    assert 'id="clearHistory"' in source
    assert "navigator.clipboard.writeText" in source
    assert "function createQueryCard" in source
    assert "function renderTable" in source
    assert "查询成功，但未找到匹配的数据" in source
    assert "formatTime" in source
