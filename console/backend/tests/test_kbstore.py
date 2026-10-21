import pytest

from app import auth, kbstore as kb


@pytest.mark.parametrize("raw,expected", [("品牌人设定义", "品牌人设定义"), ("  广告法极限词表.md ", "广告法极限词表"), ("a b c", "a b c"), ("A.MD", "A")])
def test_clean_name_ok(raw, expected):
    assert kb.clean_name(raw) == expected


@pytest.mark.parametrize("bad", ["", "   ", ".hidden", "a/b", "a\b", "x" * 61, "a:b", "q?", ".md", "tab\there"])
def test_clean_name_rejects(bad):
    with pytest.raises(kb.KbError):
        kb.clean_name(bad)


def test_clean_content():
    assert kb.clean_content("a\r\nb") == "a\nb\n"
    for bad in ["", "  \n ", "x" * (kb.MAX_BYTES + 1)]:
        with pytest.raises(kb.KbError):
            kb.clean_content(bad)


def test_unknown_kb_is_rejected():
    with pytest.raises(kb.KbError):
        kb.kb_dept("kb-nope")
    assert kb.kb_dept("kb-brand") == "ops" and kb.kb_dept("kb-company") == "all"


def allowed(role, method, path):
    return any(method == m and rx.match(path) for m, rx in auth.ROLE_ALLOWED[role])


def test_manager_and_boss_kb_routes():
    reads = ["/api/knowledge-bases", "/api/knowledge-bases/kb-brand/documents", "/api/knowledge-bases/kb-brand/documents/品牌人设定义",
             "/api/knowledge-bases/kb-brand/deleted", "/api/kb-reviews"]
    writes = [("POST", "/api/knowledge-bases/kb-brand/documents"), ("PUT", "/api/knowledge-bases/kb-brand/documents/品牌人设定义"),
              ("DELETE", "/api/knowledge-bases/kb-brand/documents/品牌人设定义"), ("POST", "/api/knowledge-bases/kb-brand/documents/x/rollback"),
              ("POST", "/api/knowledge-bases/kb-brand/sync")]
    for role in ("manager", "boss"):
        assert all(allowed(role, "GET", p) for p in reads) and all(allowed(role, m, p) for m, p in writes)
    assert not allowed("manager", "POST", "/api/kb-reviews/kb-company/x/2") and allowed("boss", "POST", "/api/kb-reviews/kb-company/x/2")
    assert not allowed("manager", "DELETE", "/api/knowledge-bases/kb-brand") and not allowed("boss", "PATCH", "/api/knowledge-bases/kb-brand/documents/x")
