# DocDrift

**Multi-agent system that keeps documentation in sync with code.**
When a code change merges, DocDrift finds every doc section it made wrong, rewrites only those
sections, verifies each fix against the new code, and opens a PR with code citations.

Capstone project, Joinloop Academy Agentic AI Cohort 3. Team 7 (Multi-Agent Mafia), author: Thiraviam.

## The problem

Docs rot silently. Someone renames a query param or an env var, and the README, API guide and
runbook keep describing the old behaviour. Engineers stop trusting docs, ask in Slack, and new
joiners lose days. Doc tools help you *write* docs; nothing reliably notices a code change has
*broken* them and fixes it.

## Architecture

```
            git diff (base..head)
                    │
          ┌─────────▼─────────┐  AST diff = source of truth
          │ 1. Change Analyst │  + Claude summary / extra changes (grounding-checked)
          └─────────┬─────────┘
                    │ ChangeSet (typed JSON)
          ┌─────────▼─────────┐  recall: exact symbols + long-term memory + BM25
          │ 2. Impact Finder  │  precision: Claude judges each candidate
          └─────────┬─────────┘
                    │ ImpactReport (stale sections + confidence)
          ┌─────────▼─────────┐
     ┌───►│ 3. Doc Fixer      │  minimal rewrite + code citations
     │    └─────────┬─────────┘
     │              │ DocPatch
     │    ┌─────────▼─────────┐  guardrails, stale refs, citations, hallucinated
     │    │ 4. Verifier       │  identifiers, snippet syntax, Claude semantic review
     │    └─────────┬─────────┘
     └── retry ─────┤ (max 2, with concrete feedback)  → else "needs human"
                    │
          ┌─────────▼─────────┐
          │ Publisher         │  dry-run | apply | branch | PR. Never merges.
          └───────────────────┘
```

Built with **LangGraph** (state graph + conditional retry edge) and **Claude** (forced tool-use
for validated structured output). Also exposed as an **MCP server**.

| Demo Day question | Answer |
|---|---|
| How do agents communicate? | Typed Pydantic contracts in LangGraph state: `ChangeSet` → `ImpactReport` → `DocPatch` → `Verdict`. Verifier feedback loops back to the Fixer via a conditional edge. |
| How is memory managed? | **Short-term:** LangGraph state for one run. **Long-term:** `.docdrift/memory.json` in the target repo: confirmed symbol→section links (boost recall next run), human-marked false positives (`docdrift ignore`), run log. Committed with the PR so CI learns too. |
| Guardrails | Writes only `*.md` (never code, CI or its own memory); heading must be preserved; max changed lines per section; every patch must cite real code lines; new identifiers must exist in code (anti-hallucination); secret scan; doc content treated as data, and sections with prompt-injection text are excluded; LLM call budget; max sections per run; never auto-merges. |
| Runs without babysitting? | Every LLM step has a deterministic fallback. No API key, rate limit or bad output → pipeline still completes. A bad key stops Claude calls after the first failure; each call has a 60 s timeout. |
| Error handling | Bounded everywhere: max 2 retries per section, 40 LLM calls and 25 sections per run, LangGraph `recursion_limit=25`. Bad repo path or commit → one-line `DocDrift error:` and exit 1 (MCP tools return the same text). A failed push or PR keeps the local branch and reports why. |

## Quickstart

```bash
pip install -r requirements.txt
cp .env.example .env          # add ANTHROPIC_API_KEY (optional: works without, in deterministic mode)

python -m docdrift demo       # builds demo_repo/, makes a breaking API change, fixes the docs
cd demo_repo && git diff      # see what DocDrift changed
cat .docdrift/out/docdrift_report.md
```

On your own repo:

```bash
python -m docdrift run --repo /path/to/repo --base HEAD~1 --head HEAD --mode dry-run
#   --mode apply    write fixes into the working tree
#   --mode branch   commit to docdrift/<sha> (via git worktree; your checkout untouched)
#   --mode pr       branch + push + open GitHub PR (needs GITHUB_TOKEN)
#   --mock          force deterministic mode

python -m docdrift ignore --repo . --section "docs/runbook.md#clients-report-429-errors" --symbol limit
```

CI: copy `ci/docdrift.yml` to `.github/workflows/docdrift.yml` in the guarded repo, add the `ANTHROPIC_API_KEY` secret.

MCP (Claude Desktop / Claude Code): `python -m docdrift.mcp_server`. Tools: `check_docs`,
`apply_doc_fixes`, `ignore_section`.

## The demo scenario

`sample_app/` is a small Inventory API with a README, API reference, runbook and onboarding doc.
`demo/make_change.sh` merges a realistic breaking change *without touching docs*:

| Change | Docs affected |
|---|---|
| `/v1/stock` → `/v1/inventory` | API reference, README curl |
| `limit` → `page_size`, default 20 → 50 | API table, Python snippet, README |
| `ttl_minutes` → `hold_minutes` | API reference, runbook |
| `INV_DB_URL` → `INVENTORY_DATABASE_URL` | README config, runbook kubectl step |

Planted trap: the runbook's "rate **limit** of 100 requests" must **not** be touched. DocDrift skips it.

## What broke (so far)

- **Port-number boundary bug:** `/v1/stock` wasn't matched in `localhost:8000/v1/stock` because the
  whole-word regex treated the `0` before `/` as part of a word. Fixed: boundaries only on word-character ends.
- **Memory pollution:** memory linked bare default values like `50` to sections. Fixed: only identifiers are linked.
- **mcp 2.x renamed `FastMCP` → `MCPServer`.** Server now supports both.

## Test scenarios

```bash
python -m pytest -q        # 16 tests
```

| # | Scenario | Expected | Test |
|---|---|---|---|
| 1 | Breaking API change merged, docs untouched | 7 stale sections fixed and verified | `test_end_to_end_deterministic` |
| 2 | "rate limit" prose next to a renamed `limit` param | Left alone (false positive skipped) | `test_end_to_end_deterministic` |
| 3 | Docs-only commit | No-op, nothing published | `test_docs_only_change_is_noop` |
| 4 | Claude invents an identifier | Verifier rejects it, Fixer retries, passes | `test_verifier_sends_hallucination_back_to_fixer` |
| 5 | A section can't be fixed | Escalated to "needs human" after 2 retries; rest still ships | `test_unfixable_section_goes_to_human` |
| 6 | Claude down (outage / bad key) | Deterministic fallback, all 7 still fixed | `test_llm_outage_falls_back_to_deterministic` |
| 7 | Doc contains "ignore previous instructions" | Section excluded from auto-fix, flagged for a human | `test_prompt_injection_section_is_never_auto_fixed` |
| 8 | Wrong repo path / unknown commit | Clear error, exit 1, no traceback (CLI and MCP) | `test_bad_input_gives_clear_error_not_traceback`, `test_mcp_tool_returns_error_text` |
| 9 | GitHub rejects the PR | Local branch kept, reason reported | `test_pr_failure_keeps_local_branch` |

Plus unit tests for AST change detection, regex boundaries, chunking and guardrails.

## Layout

```
docdrift/
  agents/change_analyst.py  impact_finder.py  doc_fixer.py  verifier.py
  graph.py        LangGraph wiring + memory update
  code_facts.py   AST extraction & diff (routes, params, defaults, env vars, constants)
  doc_index.py    markdown chunking, symbol hits, BM25
  guardrails.py   memory.py  llm.py  publisher.py  run.py  cli.py  mcp_server.py
sample_app/       demo service + docs
demo/             setup_demo.sh, make_change.sh, after/main.py
tests/
```
