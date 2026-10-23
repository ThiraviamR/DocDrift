"""End-to-end tests: deterministic mode, and the Verifier->Fixer retry loop with a fake LLM."""
import re

from docdrift import context as ctx_mod
from docdrift.agents.doc_fixer import _LLMFix, _deterministic_fix
from docdrift.run import run
from docdrift.schemas import LLMChangeNotes, LLMImpactBatch, LLMImpactJudgement, LLMSemanticCheck


def test_end_to_end_deterministic(demo_repo):
    res = run(str(demo_repo), mode="apply", quiet=True)
    st = res["state"]
    assert len(st["impacts"]) == 7
    assert all(v.status == "pass" for v in st["verdicts"].values())
    assert any(s.section_id.endswith("clients-report-429-errors") for s in st["skipped"])
    docs = "".join(p.read_text() for p in demo_repo.rglob("*.md") if ".docdrift" not in str(p))
    for stale in ["INV_DB_URL", "/v1/stock", "ttl_minutes", "`limit`"]:
        assert stale not in docs, stale
    assert "rate limit" in docs  # false positive left alone
    assert (demo_repo / ".docdrift/memory.json").exists()


def test_docs_only_change_is_noop(demo_repo):
    (demo_repo / "docs/onboarding.md").write_text("# Onboarding\n\nHello\n")
    import subprocess
    subprocess.run(["git", "-C", str(demo_repo), "commit", "-qam", "docs only"], check=True)
    res = run(str(demo_repo), quiet=True)
    assert res["files"] == []


class FakeLLM:
    """Simulates Claude. First fix attempt for api.md#list-stock hallucinates an identifier."""

    def __init__(self, bad_forever=None):
        self.calls = 0
        self.ctx = None
        self.bad_forever = bad_forever or set()
        self.seen: dict[str, int] = {}

    available = True

    def structured(self, system, user, schema, max_tokens=4000):
        self.calls += 1
        if schema is LLMChangeNotes:
            return LLMChangeNotes(summary="Stock API renamed to inventory.")
        if schema is LLMImpactBatch:
            ids = re.findall(r'<doc id="([^"]+)">', user)
            return LLMImpactBatch(judgements=[
                LLMImpactJudgement(section_id=i, stale="429" not in i and "onboarding" not in i,
                                   confidence=0.9, change_ids=[1, 2, 3, 4, 5, 6, 7], reason="fake")
                for i in ids
            ])
        if schema is _LLMFix:
            sid = re.search(r"Section \(([^)]+)\)", user).group(1)
            self.seen[sid] = self.seen.get(sid, 0) + 1
            sec = self.ctx.index.by_id[sid]
            imp = next(i for i in self.ctx._state_impacts if i.section_id == sid)
            chs = [c for c in self.ctx._changes if c.id in imp.change_ids]
            good = _deterministic_fix(sec, chs, self.ctx._changes)
            if (sid.endswith("list-stock") and self.seen[sid] == 1) or sid in self.bad_forever:
                return _LLMFix(updated=good.updated + "\nAlso set `stock_limit_v2`.", citations=good.citations, rationale="bad")
            return _LLMFix(updated=good.updated, citations=good.citations, rationale="good")
        if schema is LLMSemanticCheck:
            return LLMSemanticCheck(accurate=True)
        raise AssertionError(schema)


def _patch_ctx(monkeypatch, fake):
    orig_init = ctx_mod.RunContext.__post_init__

    def post_init(self):
        orig_init(self)
        self.llm = fake
        fake.ctx = self

    monkeypatch.setattr(ctx_mod.RunContext, "__post_init__", post_init)
    # expose impacts/changes to the fake via the agents' outputs
    from docdrift.agents import change_analyst as ca, impact_finder as imf
    from docdrift import graph

    real_ca, real_if = ca.change_analyst, imf.impact_finder

    def ca_wrap(ctx, s):
        out = real_ca(ctx, s)
        ctx._changes = out["changeset"].changes
        return out

    def if_wrap(ctx, s):
        out = real_if(ctx, s)
        ctx._state_impacts = out["impacts"]
        return out

    monkeypatch.setattr(graph, "change_analyst", ca_wrap)
    monkeypatch.setattr(graph, "impact_finder", if_wrap)


def test_verifier_sends_hallucination_back_to_fixer(demo_repo, monkeypatch):
    fake = FakeLLM()
    _patch_ctx(monkeypatch, fake)
    res = run(str(demo_repo), quiet=True)
    st = res["state"]
    sid = "docs/api.md#list-stock"
    assert st["attempts"][sid] == 2
    assert st["verdicts"][sid].status == "pass"
    assert "stock_limit_v2" not in st["patches"][sid].updated


def test_unfixable_section_goes_to_human(demo_repo, monkeypatch):
    fake = FakeLLM(bad_forever={"docs/api.md#reserve-stock"})
    _patch_ctx(monkeypatch, fake)
    res = run(str(demo_repo), quiet=True)
    st = res["state"]
    sid = "docs/api.md#reserve-stock"
    assert st["attempts"][sid] == 3  # 1 + max_retries(2)
    assert st["verdicts"][sid].status == "needs_human"
    assert "docs/api.md" in res["files"]  # other api.md sections still published
    report = open(res["report"]).read()
    assert "Needs human review" in report and sid in report
