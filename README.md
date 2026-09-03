# CLEARCUT

**Autonomous script clearance and rights-risk agent network.**

Every film and television production must obtain a *script clearance report*
before an Errors & Omissions insurer will bind coverage — and without E&O, no
distributor will release the picture. The report is a line-by-line legal audit
of the screenplay: every character name, business, brand, phone number, address,
licence plate, domain, song, artwork, film clip, masthead and real-person
reference is identified, researched against trademark registries and the open
web, and ruled on.

Today that work is manual. It takes weeks, and it is invalidated by every script
revision — and scripts revise constantly, through white, blue, pink, yellow,
green and goldenrod pages.

CLEARCUT runs the same process as a network of agents, and then keeps the result
alive across revisions.

---

## What it does

```
  screenplay.pdf
        │
        ▼
  ┌─────────────┐
  │  Breakdown  │  Gemini · per-scene extraction of every clearable element,
  └─────────────┘  page- and scene-cited, verbatim quoted
        │
        ▼
  ┌─────────────┐
  │   Triage    │  deterministic · settle what is knowable by rule, and write
  └─────────────┘  a research objective framed on the governing legal theory
        │
        ▼
  ┌─────────────┐
  │  Research   │  PARALLEL SEARCH API · live web verification with citations,
  └─────────────┘  escalating to the Task API for high-stakes items
        │
        ▼
  ┌─────────────┐
  │ Adjudicate  │  Gemini · five-verdict ruling on the evidence, under
  └─────────────┘  category-specific standards
        │
        ▼
  ┌─────────────┐
  │ Substitute  │  propose a replacement, then re-clear the replacement
  └─────────────┘  through the same pipeline until one verifies
        │
        ▼
  ┌─────────────┐
  │   Report    │  E&O-ready PDF, blocking items first, sources inline
  └─────────────┘
```

A **clearance ledger** persists the result per production. On the next draft,
only the delta is re-cleared.

---

## Why the research step is load-bearing

A language model cannot produce a USPTO registration number from its weights.
A clearance ruling that an insurer's counsel will rely on has to be traceable to
a live source. On the demo screenplay, Parallel returned:

| Item | Source retrieved |
|---|---|
| `Coca-Cola` | USPTO registration 0022406 via Justia |
| `Sweet Child O' Mine` | songwriter and publisher copyright-holder records |
| `Northwestern Memorial Hospital` | the hospital's own IP policy PDF |
| `Nighthawks` | Art Institute of Chicago copyright-formalities records |
| `Delaney Building` | a real building at 122 Stadium Way, Knoxville TN |

That last one is the point of the product. "Delaney Building" was invented as a
fictional Chicago address. It is a real building in Tennessee, and depicting it
as the site of a fraud is exactly the exposure a clearance report exists to catch.

The `Nighthawks` ruling is worth reading in full: the adjudicator concluded the
1942 painting is public domain because **copyright was never renewed after the
initial 28-year term**, citing Art Institute records — overriding a cruder
date-based heuristic in its own instructions because the retrieved evidence said
otherwise.

---

## The revision ledger

A verdict is a function of the subject **and how the script treats it**.

`STATE FARM` mentioned in passing and `STATE FARM` shown approving fraudulent
claims are the same nine characters and completely different clearance outcomes.
So a ledger entry only carries forward when value, category **and depiction** are
all unchanged. Reusing on the name alone would silently pass a defamation claim
through a revision — the precise failure this product exists to prevent.

---

## Running it

Requires Python 3.11+.

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
cp .env.example .env     # then fill in your keys
```

`.env`:

```
PARALLEL_API_KEY=...       # platform.parallel.ai
GOOGLE_API_KEY=...         # aistudio.google.com/apikey
GOOGLE_CLOUD_PROJECT=...   # optional; set GOOGLE_GENAI_USE_VERTEXAI=TRUE to route via Vertex
```

Run a clearance pass:

```bash
.venv/bin/python -c "
import sys; sys.path.insert(0,'backend')
from clearcut.pipeline import run_clearance
r = run_clearance('assets/screenplays/the_long_odds_v1.txt',
                  project_id='long-odds',
                  emit=lambda e: print(f'[{e.agent}] {e.message}'),
                  pdf_path='data/reports/report.pdf')
print(r.counts_by_verdict())
"
```

Then run the revision and watch the ledger carry verdicts forward:

```bash
.venv/bin/python -c "
import sys; sys.path.insert(0,'backend')
from clearcut.pipeline import run_clearance
run_clearance('assets/screenplays/the_long_odds_v2.txt',
              project_id='long-odds',
              emit=lambda e: print(f'[{e.agent}] {e.message}'))
"
```

Tests:

```bash
.venv/bin/python -m pytest backend/tests/ -q
```

### A note on API quota

The Gemini free tier allows **20 requests per day per model**. A single 4-page
screenplay needs roughly 30 model calls, so a free key will not complete a full
pass. Enable billing on the key for pay-as-you-go, which costs cents for this
workload on flash models.

The client is built for this reality: calls walk a fallback chain across models,
run under a hard wall-clock deadline (the SDK's own timeout is not honoured on
this path), demote models that fail repeatedly, and skip retries against per-day
quota errors that cannot succeed. All model and research results are cached
content-addressed on disk, so a repeat run is free and reproducible.

---

## Deploying to Cloud Run

Builds remotely with Cloud Build, so no local Docker daemon is required. API
keys are stored in Secret Manager and mounted into the service at runtime
rather than baked into the image or passed as plain environment variables.

```bash
./deploy.sh YOUR_PROJECT_ID us-central1
```

The script enables the required APIs, writes both keys as secrets, grants the
runtime service account access, deploys, and prints the public URL.

Requires billing enabled on the GCP project.

**A note on persistence.** Cloud Run's filesystem is read-only apart from
`/tmp`, so `CLEARCUT_DATA_DIR` points there. The clearance ledger and the model
and research caches therefore live for the life of an instance and do not
survive a cold start or spread across instances. That is fine for a demo; a
production deployment should back the ledger with Firestore or Cloud Storage,
which is a change confined to `core/ledger.py` and `services/cache.py`.

---

## Runtime integrations

**Parallel Web Systems** — `backend/clearcut/services/parallel_research.py`
Search API for every researched item; Task API for escalated high-stakes
verification. Called at runtime for each clearance subject.

**Google Gemini** — `backend/clearcut/services/gemini_client.py`
Structured extraction in Breakdown, adjudication in Adjudicate, candidate
generation in Substitute. Supports Vertex AI routing via
`GOOGLE_GENAI_USE_VERTEXAI=TRUE`.

---

## Layout

```
backend/clearcut/
  core/
    models.py        domain model in the industry's vocabulary
    screenplay.py    scene/page coordinate system (55 lines per page)
    rules.py         deterministic clearance rules
    coalesce.py      fold name fragments, drop generic roles
    ledger.py        persistent clearance state across drafts
  agents/
    breakdown.py  triage.py  research.py
    adjudicate.py substitute.py report.py
  services/
    gemini_client.py       fallback chain, deadlines, caching
    parallel_research.py   Parallel Search + Task
    cache.py               content-addressed disk cache
  pipeline.py        the six-agent run
assets/screenplays/  demo fixtures (White and Blue drafts) + ground truth
```

## Licence

MIT — see [LICENSE](LICENSE).
