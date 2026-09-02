# CLEARCUT

**Autonomous script clearance for film and television.**
Submitted to *Agentic Cinema: The Blockbuster Hackathon* — **Parallel track**.

---

## The problem

No film or television production gets distributed without **Errors & Omissions
insurance**. No E&O carrier binds coverage without a **script clearance report**.

That report is a line-by-line legal audit of the screenplay. A human researcher
reads every page and flags every character name, business name, brand, phone
number, address, license plate, URL, song cue, artwork, film clip, masthead,
real-person reference and potential defamation. Each one is then checked against
trademark registries, business registries, directories and the open web, and
ruled **CLEAR / CLEAR WITH CAUTION / MUST CHANGE / LICENSE REQUIRED**.

It takes **2–4 weeks** and costs **thousands of dollars per script**.

And it is invalidated by every revision. Scripts revise constantly — white, blue,
pink, yellow, green, goldenrod pages. Productions either pay again and wait
again, or they shoot uncleared pages and hope. That second option is how films
end up in litigation.

## What CLEARCUT does

A network of six agents that reads a screenplay, verifies every clearable
element against the **live web with citations**, rules on it, generates safe
replacements and **re-verifies the replacements**, then issues an E&O-ready
report — in minutes.

Then it stays alive. Upload the pink pages and it re-clears only what changed.

| | Human clearance house | CLEARCUT |
|---|---|---|
| Turnaround | 2–4 weeks | minutes |
| Re-clearance on revision | full re-review | delta only |
| Proposed replacements | none | generated **and re-verified** |
| Evidence | internal notes | live citations on every ruling |

## The agent network

| Agent | Role |
|---|---|
| **Breakdown** | Gemini multimodal parses the screenplay into scenes and extracts every clearable item with page, scene and verbatim quote |
| **Triage** | Classifies each item and writes a category-specific research plan — a trademark and a defamation risk need different strategies |
| **Research** | **Parallel Search API** verifies each item against the live web; high-stakes items escalate to the Task API for multi-hop verification |
| **Adjudication** | Applies industry clearance rules and issues a cited verdict |
| **Substitution** | Proposes replacements for blocked items, then runs them back through Research and Adjudication until provably clear |
| **Report** | Emits the annotated, page-cited clearance report and the machine-readable ledger |

### Why Parallel is load-bearing

A language model cannot know from its weights whether `Zenith Motors` is a live
registered mark *today*. It has to look. Every verdict CLEARCUT issues traces to
citations retrieved at runtime through Parallel's Search API — which is what
makes the output a legal instrument rather than a model opinion.

## Requirements coverage

- **Google Cloud at runtime** — Gemini via `google-genai`, agent orchestration via `google-adk`, deployed on Cloud Run
- **Parallel at runtime** — `parallel-web` SDK, `client.search()` called per clearable item, `client.task_run` for escalation
- **License** — MIT

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
cp .env.example .env   # then fill in PARALLEL_API_KEY and GOOGLE_API_KEY
```

## Repository layout

```
backend/clearcut/
  core/        domain model + config
  services/    Parallel research engine
  agents/      the six-agent network
assets/screenplays/
  the_long_odds_v1.txt              demo screenplay
  the_long_odds_v1.groundtruth.json 18 planted landmines — the eval target
```

## Evaluation

The demo screenplay carries **18 deliberately planted clearance landmines**
across 14 categories, with expected verdicts recorded in the ground-truth
manifest. The pipeline is scored on precision and recall against it.

## Disclaimer

CLEARCUT is decision support for clearance professionals. It is not legal advice
and does not replace production counsel or a licensed clearance house.
