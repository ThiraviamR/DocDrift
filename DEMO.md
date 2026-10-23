# DocDrift: Demo Day runbook

Live Demo Day: **Oct 24**. Deck and PPT due: **Oct 22**. Talk limit: **under 10 minutes** (timing below adds to about 9:45, so keep the demo tight).

## 1. Before the day (do these once)

- [ ] `pip install -r requirements.txt` on your Mac (Python 3.10 or later)
- [ ] `cp .env.example .env` and add `ANTHROPIC_API_KEY`
- [ ] `python -m docdrift demo` with Claude and confirm 7 fixed, 0 need human. If the model ID is rejected, set `DOCDRIFT_MODEL` to a current Claude model
- [ ] Note the live-Claude run time and the number of LLM calls (both are in the report footer). Add them to the Results slide if you want
- [ ] Note anything that broke in the live run and add it to the "What broke" slide notes
- [ ] `python -m pytest -q` shows 16 passed
- [ ] Make https://github.com/ThiraviamR/DocDrift public (Settings → Danger Zone → Change visibility) so reviewers can open it
- [ ] Optional wow moment: on a test GitHub repo, run `--mode pr` once and screenshot the PR
- [ ] Record the 3-minute video (script in section 5)
- [ ] Share the deck from its Share menu if reviewers need the link

## 2. On the day: setup (5 minutes before)

```bash
cd ~/Documents/GitHub/JoinLoop/DocDrift
rm -rf demo_repo            # clean slate
clear
```

- Use a large terminal font (about 20 pt) on a dark background
- Have two tabs ready: tab 1 for running the demo, tab 2 already `cd`'d into the folder with `--mock` typed but not run (your fallback)
- Turn off notifications

## 3. Talk timing (about 9:45 in total)

| Slide | Time | Key line |
|---|---|---|
| 1 Cover | 0:20 | "Docs that fix themselves when code changes." |
| 2 Problem | 0:45 | "Tools help you write docs. Nothing notices when a code change breaks one." |
| 3 By hand | 0:40 | "30 to 90 minutes per change. Each step became an agent." |
| 4 What it does | 0:20 | "A human still merges." |
| 5 Architecture | 1:00 | "Code analysis is the source of truth. The AI can't invent changes." |
| 6 Handoffs | 0:40 | "Typed forms, not chat. Claude answers through a schema." |
| 7 **Live demo** | 2:20 | Section 4 below |
| 8 Results | 0:40 | "7 of 7 fixed. Nine scenarios, five of them unhappy paths, all pass." |
| 9 Memory | 0:40 | "Memory lives in the repo, so it's versioned and reviewable." |
| 10 Guardrails | 0:50 | "The rules hold whatever the model says." |
| 11 What broke | 0:45 | "The checker shared the fixer's blind spot." |
| 12 Retro | 0:30 | One honest point |
| 13 Close | 0:15 | Questions |

## 4. The live demo (2 minutes 20 seconds)

**Set the scene (20 seconds):**
"This is an Inventory API with a README, API guide and runbook. A developer just merged a change: `/v1/stock` is now `/v1/inventory`, `limit` is now `page_size` with a default of 50, `ttl_minutes` is now `hold_minutes`, and the database environment variable was renamed. Nobody touched the docs."

**Run it:**

```bash
python -m docdrift demo
```

**Narrate the coloured lines as they appear:**

1. **Cyan, ChangeAnalyst:** "8 changes found by reading the code itself."
2. **Purple, ImpactFinder:** "7 sections stale." Point at the `skip` line: "This is the runbook's 'rate limit' sentence. It contains the word 'limit', but it's not about the parameter, so it's left alone."
3. **Yellow, DocFixer:** "Each section patched, with citations."
4. **Green, Verifier:** "Every fix checked against the new code: all PASS."

**Show the proof:**

```bash
cd demo_repo && git --no-pager diff README.md docs/api.md
cat .docdrift/out/docdrift_report.md | head -40      # the PR body
cat .docdrift/memory.json | head -15                 # long-term memory
```

**If something fails:** go to tab 2 and run `python -m docdrift demo --mock`. Say: "Same pipeline, using the deterministic fallback. This is the guardrail that means nobody has to step in mid-demo." Then continue as above.

## 5. Three-minute video script

| Time | On screen | Say |
|---|---|---|
| 0:00–0:20 | Problem slide | "When code changes, docs go out of date without anyone noticing. DocDrift fixes that." |
| 0:20–0:50 | Architecture slide | "Four agents in LangGraph: the Change Analyst reads the diff, the Impact Finder finds stale sections, the Doc Fixer rewrites them with code citations, and the Verifier checks each fix and sends failures back, up to twice." |
| 0:50–2:00 | Terminal: `python -m docdrift demo`, then `git diff` | Narrate as in section 4 |
| 2:00–2:30 | Guardrails slide | "It only edits docs, must cite real code, can't invent names, ignores instructions planted in docs, and never merges." |
| 2:30–2:50 | Memory slide | "Short-term memory is the graph state. Long-term memory is a file in the repo that learns from every run." |
| 2:50–3:00 | Close slide | "DocDrift: docs that stay true, with a human in charge." |

## 6. Likely questions

- **Why not just ask the LLM to update the docs?** It would invent things and change too much. The code analysis is the source of truth, every fix must cite code, and the Verifier rejects names that don't exist in the code.
- **Why a JSON file and not a vector database for memory?** It's small, versioned with the code, reviewable in the PR, and works in CI with no extra infrastructure. BM25 handles fuzzy matching.
- **What about other languages?** The code reader is the only Python-specific part, and adding a TypeScript or Java one is a plug-in. Docs are any markdown.
- **What stops it looping on its own PRs?** DocDrift's PRs change only docs, so the next run finds no code changes and stops. The Action also skips commits tagged `[docdrift]`.
- **What does a run cost?** At most 40 Claude calls per run, enforced. [Fill in the actual count from your live run: it's in the report footer.]
- **What happens with a wrong fix?** The Verifier sends it back with the reasons. After 2 retries it's flagged "needs human" and left out of the PR's edits, while the rest still ships.
- **Is it safe on private code?** It only reads git, it writes only markdown, and the GitHub token is used only for opening the PR.
- **Where's the MCP part?** `python -m docdrift.mcp_server` exposes `check_docs`, `apply_doc_fixes` and `ignore_section` to Claude Desktop or Claude Code.
