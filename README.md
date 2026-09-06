# CLEARCUT

Script clearance for film and television, run as a reviewed agent network.

| | |
|---|---|
| **Track** | Parallel |
| **Live** | <https://clearcut-3t7xps2s6q-uc.a.run.app> |
| **Demo** | _add video URL_ |
| **Stack** | Google ADK 2.8 · Gemini via Vertex AI · Parallel Search + Task API · FastAPI · Cloud Run |
| **Licence** | MIT |

---

## The problem

No carrier binds Errors & Omissions coverage without a script clearance report.
No distributor releases a picture without E&O. So every production buys one.

The report is a line-by-line legal audit of the screenplay. A researcher reads
every page and flags each character name, business, brand, phone number,
address, licence plate, domain, song, artwork, film clip, masthead and
real-person reference, then checks each against trademark registries and public
records and rules on it.

It is done by hand. It takes weeks, and it is invalidated by every revision.
Scripts revise constantly, through white, blue, pink, yellow, green and
goldenrod pages, and each colour means commissioning the work again.

Two things follow. Productions either pay repeatedly or shoot uncleared pages
and hope. And the report, once delivered, is a dead document: it describes one
draft and knows nothing about the next.

## What this does

Runs the same audit as an agent network, with a person approving every stage,
and keeps the result as live state so the next draft only re-checks what
actually changed.

---

## Architecture

```
                    ┌──────────────────────────────────────┐
  screenplay ──────▶│  screenplay.py                       │
  PDF / Fountain    │  scene + page coordinates            │
  / plain text      │  real PDF pagination, revision colour│
                    └──────────────────┬───────────────────┘
                                       │ scenes
                    ┌──────────────────▼───────────────────┐
   ①  BREAKDOWN     │  breakdown.py    per-scene, parallel  │──▶ Gemini
                    │  depiction.py    whole-script, 2-step │──▶ Gemini ×2
                    └──────────────────┬───────────────────┘
                                       │ subjects, page-cited
                        ══ human approves, dismisses noise ══
                                       │
                    ┌──────────────────▼───────────────────┐
   ②  TRIAGE        │  rules.py        settled by rule      │  no model call
                    │  triage.py       research objectives  │  no model call
                    └──────────────────┬───────────────────┘
                                       │ what still needs evidence
                        ══ human approves the lookup spend ══
                                       │
                    ┌──────────────────▼───────────────────┐
   ③  INVESTIGATE   │  investigator.py  ADK Agent + Runner  │──▶ Parallel
                    │  picks its own tools per subject      │    Search / Task
                    └──────────────────┬───────────────────┘
                                       │ evidence + citations
                        ══ human reads the sources ══
                                       │
                    ┌──────────────────▼───────────────────┐
   ④  ADJUDICATE    │  adjudicate.py    five verdicts       │──▶ Gemini
                    │  consistency.py   reconcile conflicts │  no model call
                    └──────────────────┬───────────────────┘
                                       │ rulings
                        ══ human accepts or overrules ══
                                       │
                    ┌──────────────────▼───────────────────┐
   ⑤  SUBSTITUTE    │  substitute.py    propose, then       │──▶ Gemini
                    │  re-clear the proposal (closed loop)  │  + Parallel
                    └──────────────────┬───────────────────┘
                                       │ verified replacements
                        ══ human takes or leaves each ══
                                       │
                    ┌──────────────────▼───────────────────┐
   ⑥  REPORT        │  report.py        page-cited PDF      │  no model call
                    │  ledger.py        commit to state     │
                    └──────────────────────────────────────┘
```

`session.py` owns the gates. A stage will not run until the one before it is
approved, and reviewer decisions are state rather than annotations: a dismissed
subject never reaches research, an overruled verdict is what the report prints,
a rejected replacement is not offered.

### Design decisions worth defending

**Rules before models.** Anything knowable exactly is settled in `rules.py`
without a model call. Nobody researches whether 555-0142 belongs to someone,
because that block is reserved for fiction. Licence plates are also settled by
rule, in the other direction: registration records are not public, a lookup
returns nothing for every plate ever written, and reading that silence as
clearance is how a real plate reaches the screen.

**Depiction is decided once, globally, in two steps.** Exposure needs two
things: something real behind the name, and the way the script treats it. A
real company mentioned in passing is usually fine; the same company shown
committing fraud is not. Per-scene extraction cannot see this, so one call
records what the film depicts act by act with the role each entity plays, and a
second judges subjects against that written finding.

**The investigator is an agent, not a lookup.** Research depth is a judgement,
so it belongs to the agent rather than a flag in the code.

**Verdicts are reconciled before a human sees them.** Rulings reached
independently can contradict each other. `consistency.py` settles those by
rule, and only ever upward.

---

## Runtime use of the required services

Both are imported and called on every clearance run. Exact locations:

### Parallel (partner track)

| | |
|---|---|
| Package | `parallel-web` 1.3.3 |
| Import | [`services/parallel_research.py:20`](backend/clearcut/services/parallel_research.py#L20) |
| Search API | [`services/parallel_research.py:77`](backend/clearcut/services/parallel_research.py#L77) `client.search(...)` |
| Task API | [`services/parallel_research.py:137`](backend/clearcut/services/parallel_research.py#L137) `client.task_run.create(...)` |
| Driven by | [`agents/investigator.py`](backend/clearcut/agents/investigator.py) |

Parallel is not decoration here. A ruling a carrier relies on has to trace to a
live source, and no language model produces a USPTO registration number from
its weights. Every verdict in the report carries the citations behind it.

The agent chooses which Parallel capability to use per subject. Measured:

| Subject | Tools it chose | Sources |
|---|---|---|
| `Vandermeer`, common surname, neutral depiction | Search | 6 |
| `Sweet Child O' Mine`, needle-drop | Search, then Task | 13 |
| `Northwestern Memorial`, shown falsifying records | Search, then Task | 20 |

It traced the song's sync rights to publisher and administrator unprompted. The
common surname did not need that and did not get it.

### Google Cloud

| | |
|---|---|
| Packages | `google-adk` 2.8.0, `google-genai` 2.21.0 |
| ADK import | [`agents/investigator.py:186`](backend/clearcut/agents/investigator.py#L186) `Agent`, `Runner` |
| ADK tools | [`agents/investigator.py:203`](backend/clearcut/agents/investigator.py#L203) three tools the agent selects between |
| Gemini client | [`services/gemini_client.py:36`](backend/clearcut/services/gemini_client.py#L36) |
| Vertex AI | [`services/gemini_client.py:63`](backend/clearcut/services/gemini_client.py#L63) `vertexai=True` |
| Inference call | [`services/gemini_client.py:211`](backend/clearcut/services/gemini_client.py#L211) |
| Callers | `breakdown.py`, `depiction.py`, `adjudicate.py`, `substitute.py` |
| Deployment | Cloud Run, keys in Secret Manager ([`deploy.sh`](deploy.sh)) |

---

## What the live web actually returned

From a run on the sample script:

| Subject | Source retrieved |
|---|---|
| `Coca-Cola` | USPTO registration 0022406 via Justia |
| `Sweet Child O' Mine` | songwriter and publisher records |
| `Northwestern Memorial Hospital` | the hospital's own IP policy PDF |
| `Nighthawks` | Art Institute of Chicago copyright records |
| `Delaney Building` | a real building at 122 Stadium Way, Knoxville TN |

The last one is the product in one line. "Delaney Building" was invented as a
fictional Chicago address. It is a real building in Tennessee, and showing it as
the site of a fraud is exactly the exposure clearance exists to catch.

---

## The revision ledger

On a new draft, only the delta is re-checked. An entry carries forward when
value, category **and depiction** are all unchanged.

That third condition is the one that makes it correct rather than merely fast.
Reusing on the name alone would pass a defamation claim through a revision
silently.

The sample Blue draft tests exactly this. It applies three fixes the White
report demanded, renames a street, and adds a scene where a named adjuster
approves eleven fraudulent files under a company banner. The company's name
never changes. Its exposure does.

---

## Measured results

```bash
PYTHONPATH=backend .venv/bin/python -m clearcut.evals.run the_long_odds_v1
```

Five trials per draft, fresh cache each, full pipeline.

| | White | Blue |
|---|---|---|
| **Recall** | **100%** (sd 0.0) | **100%** (sd 0.0) |
| Depiction | 86.2% (sd 4.7) | 87.8% (sd 5.4) |
| Verdict agreement | 68.9% (sd 2.7) | 67.1% (sd 2.9) |

Recall is ranked first because a missed subject never reaches a reviewer and
surfaces later as an uninsurable film. A false positive costs somebody thirty
seconds, so extra flags are counted as review load, not error.

Verdict agreement is deliberately not called accuracy. The expected verdicts are
one experienced reading of standard practice, not fact. The residual is
concentrated: four subjects fail in all five trials, which makes them standing
disagreements that can be argued about rather than noise. `DR. ALAN REINHOLT`
rules stricter than the fixture, which is the safe direction for clearance.

The harness has twice corrected the fixture rather than the code. It also caught
a recall regression nothing else would have: `MERIDIAN AUTO BODY`, the
protagonist's own garage, was missing from four runs in five because it appears
only in scene headings and the extraction prompt read "in a scene" as the action
and dialogue. Tests passed, the UI worked, the report rendered, and a business
the film is set in was absent from it.

Method and full history: [docs/stability.md](docs/stability.md).

**Caveat.** Re-running identical code across measurement rounds has moved
depiction by about ten points. That is larger than the gap between some
configurations chosen during development, so several tuning decisions were made
inside the noise. Recall is the only figure that has held across every run.

---

## Running it

Python 3.11+.

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
cp .env.example .env
```

`.env`:

```
PARALLEL_API_KEY=...            # platform.parallel.ai
GOOGLE_CLOUD_PROJECT=...        # a billed GCP project
GOOGLE_CLOUD_LOCATION=us-central1
GOOGLE_GENAI_USE_VERTEXAI=TRUE
```

```bash
PYTHONPATH=backend .venv/bin/python -m uvicorn clearcut.api:app --port 8099
```

Open <http://127.0.0.1:8099/>, upload a screenplay or pick a sample, and work
the six steps. Tests: `.venv/bin/python -m pytest backend/tests/ -q`.

### Model access

Use **Vertex AI**. The Gemini free tier allows 20 requests per day per model,
which will not complete one pass on a four-page script.

Model availability differs between AI Studio and Vertex, so the fallback chain
is chosen per backend. Calls walk that chain, run under a hard wall-clock
deadline (the SDK's own timeout is not honoured on this path), demote models
that fail repeatedly, and skip retries against per-day quota errors that cannot
succeed. Results are cached content-addressed on disk, so a repeat run is free
and reproducible.

## Deploying

```bash
./deploy.sh YOUR_PROJECT_ID us-central1
```

Builds through Cloud Build, so no local Docker daemon. Keys go to Secret Manager
and mount at runtime rather than being baked into the image.

Cloud Run's filesystem is read-only apart from `/tmp`, so `CLEARCUT_DATA_DIR`
points there and the ledger lives for the life of an instance. Fine for a demo;
production would back it with Firestore or Cloud Storage, a change confined to
`core/ledger.py` and `services/cache.py`.

---

## Layout

```
backend/clearcut/
  session.py              stage gates, approvals, reviewer decisions
  api.py                  18 routes, SSE for live agent traces
  pipeline.py             unattended run, same agents, no gates
  core/
    models.py             domain model in the industry's vocabulary
    screenplay.py         scene/page coordinates, real PDF pagination
    rules.py              what is settled without a model, and why
    naming.py             the four name normalisations, in one place
    coalesce.py           fold fragments, drop generic roles
    consistency.py        reconcile contradictory rulings, upward only
    buckets.py            how the review groups items for a production
    ledger.py             clearance state across drafts
  agents/                 breakdown depiction triage investigator
                          adjudicate substitute report
  services/
    gemini_client.py      fallback chain, deadlines, caching
    parallel_research.py  Parallel Search + Task
  evals/                  measurement harness and runner
frontend/                 dependency-free, served by the same container
assets/screenplays/       White and Blue drafts plus ground truth
docs/stability.md         measured runs, method, caveats
```

Roughly 7,000 lines across backend, frontend and evals.

## Known limitations

- Depiction sits near 87% and is the largest remaining source of error.
- Four verdict disagreements are standing rather than random; some are
  candidates for correcting the fixture rather than the code.
- The ledger does not survive a Cloud Run cold start (see Deploying).
- Ground truth covers two drafts of one screenplay. The numbers above describe
  this fixture, not screenplays in general.

## Licence

MIT, see [LICENSE](LICENSE).
