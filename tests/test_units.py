from docdrift.code_facts import diff_facts, extract
from docdrift.doc_index import chunk, find_hits, term_regex
from docdrift.guardrails import check_patch, path_allowed
from docdrift.schemas import Citation, DocPatch, DocSection

from .conftest import ROOT


def test_code_facts_detects_all_breaking_changes():
    old = extract((ROOT / "sample_app/app/main.py").read_text())
    new = extract((ROOT / "demo/after/main.py").read_text())
    got = {(c.kind, c.old, c.new) for c in diff_facts(old, new, "app/main.py")}
    assert ("env_var", "INV_DB_URL", "INVENTORY_DATABASE_URL") in got
    assert ("endpoint", "/v1/stock", "/v1/inventory") in got
    assert ("parameter", "limit", "page_size") in got
    assert ("default", "20", "50") in got
    assert ("parameter", "ttl_minutes", "hold_minutes") in got


def test_term_regex_matches_after_port_number():
    assert term_regex("/v1/stock").search("curl http://localhost:8000/v1/stock?limit=1")
    assert not term_regex("/v1/stock").search("/v1/stocks")
    assert not term_regex("limit").search("rate_limit")


def test_chunk_ignores_headings_inside_code_fences():
    md = "# A\ntext\n```bash\n# not a heading\n```\n## B\nmore\n"
    secs = chunk("x.md", md)
    assert [s.heading for s in secs] == ["A", "B"]


def test_code_context_detection():
    s = chunk("x.md", "## S\nThe rate limit is 100.\nUse `limit` here.\n")[0]
    hits = find_hits(s, "limit")
    assert [h.in_code for h in hits] == [False, True]


def _section(text="## H\nold `x_y`\n", path="docs/a.md"):
    return DocSection(id=f"{path}#h", path=path, heading="H", start_line=1, end_line=2, text=text)


def test_guardrails():
    assert path_allowed("docs/api.md") and not path_allowed("app/main.py")
    assert not path_allowed(".github/workflows/x.md")
    cite = [Citation(file="app/main.py", line=1, symbol="x")]
    ok = DocPatch(section_id="s", updated="## H\nnew `x_z`", citations=cite, rationale="")
    assert check_patch(_section(), ok) == []
    heading = DocPatch(section_id="s", updated="## Other\nnew", citations=cite, rationale="")
    assert any("heading" in i for i in check_patch(_section(), heading))
    secret = DocPatch(section_id="s", updated="## H\nkey sk-ant-abcdefghijklmnop", citations=cite, rationale="")
    assert any("secret" in i for i in check_patch(_section(), secret))
    nocite = DocPatch(section_id="s", updated="## H\nnew", citations=[], rationale="")
    assert any("citations" in i for i in check_patch(_section(), nocite))
