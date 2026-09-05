# CLEARCUT

**Script clearance for film and television, run as a reviewed agent network.**

No carrier will bind Errors & Omissions coverage without a script clearance
report, and no distributor will release a picture without E&O. The report is a
line-by-line legal audit of the screenplay: every character name, business,
brand, phone number, address, licence plate, domain, song, artwork, film clip,
masthead and real-person reference is found, checked against trademark
registries and live sources, and ruled on.

Today that work is manual. It takes weeks, it costs accordingly, and it is
invalidated by every revision. Scripts revise constantly, through white, blue,
pink, yellow, green and goldenrod pages, and each colour means paying again.

CLEARCUT runs the same audit as a network of agents. A person approves every
step, and the result stays alive across revisions so the next draft only
re-checks what actually changed.

---

## The pipeline, and where you sit in it

Six agents, each stopping for a human before the next begins. A clearance
report is a legal instrument that somebody signs, so nothing advances on the
machine's own authority.

```
  screenplay (PDF, Fountain or text)
        │
        ▼
  ┌──────────────┐
  │  Breakdown   │  Gemini reads scene by scene and marks every element
  └──────────────┘  carrying exposure, cited to its page
        │           then a whole-script pass decides how the film treats it
        ▼
     ── you approve, and dismiss anything that is not a clearance subject ──
        │
        ▼
  ┌──────────────┐
  │   Triage     │  what an industry rule already settles is settled here,
  └──────────────┘  free and exactly. The rest gets a research question
        │           framed on the legal test for its category
        ▼
     ── you approve before it spends live lookups ──
        │
        ▼
  ┌──────────────┐
  │ Investigator │  an ADK agent holding Parallel's Search and Task APIs as
  └──────────────┘  tools, choosing per subject how hard to look
        │
        ▼
     ── you read the sources it came back with ──
        │
        ▼
  ┌──────────────┐
  │  Adjudicate  │  five verdicts, under the standard governing each category:
  └──────────────┘  tarnishment, defamation, public domain, sync and master
        │
        ▼
     ── you accept each ruling or overrule it. Yours is what prints ──
        │
        ▼
  ┌──────────────┐
  │  Substitute  │  proposes a replacement, then puts the replacement through
  └──────────────┘  the same checks the original just failed
        │
        ▼
     ── you take or leave each suggestion ──
        │
        ▼
  ┌──────────────┐
  │    Report    │  page-cited PDF, blocking items first, sources inline
  └──────────────┘
```

Your decisions are state, not annotations. A dismissed item never reaches
research. An overruled verdict is what the report prints. A rejected
replacement is not offered.

---

## Why the research step is load-bearing

No language model can produce a USPTO registration number from its weights. A
ruling a carrier relies on has to trace back to a live source, so every verdict
carries the citations behind it.

The Investigator is a real ADK agent rather than a fixed lookup. It is given
Parallel's capabilities as tools and decides per subject how much to spend.
Measured on three deliberately different items:

| Subject | Tools it chose | Sources |
|---|---|---|
| `Vandermeer`, a common surname, neutral | one search | 6 |
| `Sweet Child O' Mine`, a needle-drop | search, then deep research | 13 |
| `Northwestern Memorial`, shown falsifying records | search, then deep research | 20 |

It traced the song's sync rights to publisher and administrator on its own. A
common surname with a neutral depiction did not need that, and did not get it.

What the live web actually returned on the sample script:

| Item | Source retrieved |
|---|---|
| `Coca-Cola` | USPTO registration 0022406 via Justia |
| `Sweet Child O' Mine` | songwriter and publisher records |
| `Northwestern Memorial Hospital` | the hospital's own IP policy PDF |
| `Nighthawks` | Art Institute of Chicago copyright records |
| `Delaney Building` | a real building at 122 Stadium Way, Knoxville |

That last one is the point of the product. "Delaney Building" was invented as a
fictional Chicago address. It is a real building in Tennessee, and depicting it
as the site of a fraud is exactly the exposure clearance exists to catch.

---

## Depiction decides half of every ruling

Exposure takes two things: something real behind the name, and the way the
script treats it. A real company mentioned in passing is usually fine. The same
company shown committing fraud is not. Same name, opposite outcome.

Scene-parallel extraction is structurally blind to this. Read alone, one scene
shows a man holding a printout. Read against the whole script it is a forged
medical record, and the hospital named on it is being shown as the source.

So depiction is decided globally, in two steps. One call records what the film
actually depicts, act by act, naming every entity and the role it plays
(perpetrator, instrument, employer, venue, misused, victim, opposing). A second
judges subjects against that written finding rather than re-deriving the plot
for each one.

That structure was arrived at by measurement, not preference. A single call
judging every subject at once scored between 62% and 100% on the same script,
with the count of negatives swinging between 4 and 23. Neither majority nor
union of repeated passes fixed it. Splitting the work dropped the standard
deviation from 14.7 to 3.1, which is what made the remaining errors debuggable
at all.

---

## The revision ledger

Clearance today is a dead document. It describes one draft and goes stale the
moment pink pages ship, so productions either re-buy the whole report or shoot
uncleared pages and hope.

The ledger makes it state the production holds. On a new draft, only the delta
is re-checked.

The subtlety that makes this correct rather than merely fast: a verdict is a
function of the subject *and* how the script treats it. An entry only carries
forward when value, category **and depiction** are all unchanged. Reusing on
the name alone would silently pass a defamation claim through a revision, which
is the exact failure this exists to prevent.

The sample Blue draft is built to test that. It applies three fixes the White
report demanded, renames a street, and adds a scene where a named adjuster
approves eleven fraudulent files under a company banner. The company's name
never changes. Its exposure does.

---

## Measured results

Run it yourself:

```bash
PYTHONPATH=backend .venv/bin/python -m clearcut.evals.run the_long_odds_v1
```

Four things are scored, ranked by what they cost when wrong.

**Recall** comes first. A missed subject never reaches a reviewer, never
appears in the report, and surfaces later as an uninsurable film. A false
positive costs somebody thirty seconds, so extra flags are reported separately
as review load rather than as errors.

**Depiction** is next, because it decides half of every ruling.

**Verdict agreement** is last and deliberately not called accuracy. The
expected verdicts are one experienced reading of standard practice, not fact.
Where the system and the target disagree the target is sometimes the one that
is wrong: an earlier version of the fixture said `NIGHTHAWKS` needed a licence,
and the agent was right that it is public domain because copyright was never
renewed after the initial 28-year term.

Full numbers, method and caveats are in [docs/stability.md](docs/stability.md).

### An honest caveat

Re-running identical code across measurement rounds has moved depiction by
around ten points. That swing is larger than the gap between some of the
configurations that were chosen between, which means several tuning decisions
during development were made inside the noise. Recall is the only figure that
has held firm across every run.

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
PARALLEL_API_KEY=...          # platform.parallel.ai
GOOGLE_CLOUD_PROJECT=...      # your GCP project
GOOGLE_GENAI_USE_VERTEXAI=TRUE
GOOGLE_API_KEY=...            # only if not using Vertex
```

Start the app:

```bash
PYTHONPATH=backend .venv/bin/python -m uvicorn clearcut.api:app --port 8099
```

Then open <http://127.0.0.1:8099/>, upload a screenplay or pick a sample, and
work through the six steps.

Tests:

```bash
.venv/bin/python -m pytest backend/tests/ -q
```

### A note on model access

The Gemini free tier allows 20 requests per day per model, which will not
complete a single pass. Routing through **Vertex AI** on a billed GCP project
avoids that entirely and is the recommended path. Set
`GOOGLE_GENAI_USE_VERTEXAI=TRUE` with your project id.

Model availability differs between AI Studio and Vertex, so the fallback chain
is selected per backend. Calls walk that chain, run under a hard wall-clock
deadline (the SDK's own timeout is not honoured on this path), demote models
that fail repeatedly, and skip retries against per-day quota errors that cannot
succeed. Model and research results are cached content-addressed on disk, so a
repeat run is free and reproducible.

---

## Deploying to Cloud Run

Builds remotely with Cloud Build, so no local Docker daemon is needed. API keys
go into Secret Manager and are mounted at runtime rather than baked into the
image.

```bash
./deploy.sh YOUR_PROJECT_ID us-central1
```

Cloud Run's filesystem is read-only apart from `/tmp`, so `CLEARCUT_DATA_DIR`
points there. The ledger and caches therefore live for the life of an instance.
That is fine for a demo; production would back them with Firestore or Cloud
Storage, a change confined to `core/ledger.py` and `services/cache.py`.

---

## Runtime integrations

**Parallel Web Systems** in `services/parallel_research.py`, driven by
`agents/investigator.py`. Search API for every researched subject, Task API
when the agent decides a subject needs multi-hop verification. Called at
runtime for each clearance subject.

**Google Cloud** in `services/gemini_client.py`. Gemini via **Vertex AI** for
extraction, depiction, adjudication and replacement generation. Agents are
built on **Google ADK** (`google-adk`), which selects the research tools.
Deployment targets **Cloud Run** with keys in **Secret Manager**.

---

## Layout

```
backend/clearcut/
  core/
    models.py        domain model in the industry's vocabulary
    screenplay.py    scene and page coordinates, real PDF pagination
    rules.py         what is settled deterministically, and why
    naming.py        the four name normalisations, in one place
    coalesce.py      fold fragments, drop generic roles
    consistency.py   reconcile rulings that contradict each other
    buckets.py       how the review groups items for a production
    ledger.py        clearance state across drafts
  agents/
    breakdown.py  depiction.py  triage.py
    investigator.py  adjudicate.py  substitute.py  report.py
  services/
    gemini_client.py       fallback chain, deadlines, caching
    parallel_research.py   Parallel Search and Task
  session.py         the stage-gated run with human approval
  evals/             the measurement harness
frontend/            dependency-free; served by the same container
assets/screenplays/  White and Blue drafts plus ground truth
docs/stability.md    ten measured runs, method and caveats
```

## Licence

MIT, see [LICENSE](LICENSE).
