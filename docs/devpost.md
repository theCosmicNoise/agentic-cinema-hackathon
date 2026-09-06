# Devpost submission text

Track: **Parallel**. Paste the sections below into the Devpost form.

---

## Inspiration

Every film and television production has to buy a script clearance report. No
carrier binds Errors & Omissions coverage without one, and no distributor
releases a picture without E&O. It is not optional and there is no way around it.

The report is a line-by-line legal audit of the screenplay. A researcher reads
every page and flags each character name, business, brand, phone number,
address, licence plate, domain, song, artwork, film clip and real-person
reference, then checks each against trademark registries and public records and
rules on it.

It is done by hand. It takes weeks, and every revision invalidates it. Scripts
revise constantly, through white, blue, pink, yellow, green and goldenrod pages,
and each colour means commissioning the work again. So productions either pay
repeatedly or shoot uncleared pages and hope. The report itself is a dead
document: it describes one draft and knows nothing about the next.

That last part is what made this worth building. The problem is not only that
clearance is slow. It is that the output has no memory.

## What it does

CLEARCUT runs the same audit as an agent network, with a person approving every
stage, and keeps the result as live state so the next draft only re-checks what
actually changed.

Six agents, each stopping for a human before the next begins:

1. **Breakdown** reads the screenplay scene by scene and marks every element
   carrying legal exposure, cited to its page. A second whole-script pass then
   decides how the film treats each subject.
2. **Triage** settles whatever an industry rule already answers, without a model
   call, and writes a research question for the rest framed on the legal test
   for that category.
3. **Investigator** verifies each remaining subject against live sources and
   returns citations you can open and read.
4. **Adjudicate** issues one of five verdicts under the standard governing each
   category, then reconciles rulings that contradict each other.
5. **Substitute** proposes a replacement for anything blocked and puts that
   replacement through the same checks the original just failed.
6. **Report** assembles the page-cited PDF and commits the rulings to the
   production's clearance ledger.

Reviewer decisions are state, not annotations. A dismissed subject never reaches
research. An overruled verdict is what the report prints. A rejected replacement
is not offered.

## How we built it

**Google Cloud.** Gemini through Vertex AI does screenplay extraction, depiction
assessment, adjudication and replacement generation. The Investigator is a
Google ADK `Agent` driven by an ADK `Runner`, holding three research tools it
selects between. Deployment targets Cloud Run with API keys in Secret Manager.

**Parallel.** The Search API verifies every researched subject. The Task API
handles multi-hop verification when the agent decides a subject needs it. Both
are called on every clearance run.

The Investigator is the part worth pointing at. Research depth is a judgement,
not a constant, so it belongs to the agent rather than a flag in the code.
Measured on three deliberately different subjects, it chose three different
paths: a common surname with a neutral depiction took one search; a needle-drop
escalated to deep research and traced the sync rights to publisher and
administrator unprompted; an organisation the script shows falsifying records
escalated to twenty sources.

Two design choices shaped everything else. **Rules run before models**: anything
knowable exactly is settled deterministically, so nobody spends a lookup asking
whether 555-0142 belongs to someone. And **depiction is decided globally**,
because exposure needs two things, something real behind the name and the way
the script treats it, and per-scene extraction is structurally blind to the
second.

## Data sources

- Live web verification through Parallel's Search and Task APIs. Actual sources
  returned on the sample script include the USPTO registration for Coca-Cola via
  Justia, songwriter and publisher records for a needle-drop, and one hospital's
  own intellectual property policy PDF.
- Screenplays supplied by the user, as Final Draft PDF exports, Fountain files
  or plain text. Scene numbers and pagination are read off the page.
- Two sample drafts of an original screenplay written for this project, with
  deliberately planted clearance problems and hand-written ground truth, used as
  the evaluation fixture.

No third-party datasets are bundled. Nothing about a user's screenplay leaves
the deployment except the names that need checking.

## Findings

We built an evaluation harness because early accuracy claims did not survive
contact with repetition, and it changed the project twice.

**It corrected the fixture, not the code.** The ground truth said Edward
Hopper's *Nighthawks* needed a licence. The agent ruled it public domain,
because copyright was never renewed after the initial 28-year term, citing Art
Institute of Chicago records. The agent was right and the target was wrong.

**It caught a recall regression nothing else would have.** The protagonist's own
garage was missing from four runs in five, because it appears only in scene
headings and the extraction prompt read "in a scene" as the action and dialogue.
Tests passed, the UI worked, the report rendered, and a business the film is
largely set in was simply absent from it.

**It killed an approach that looked good on a small sample.** Depiction was
badly unstable: repeated runs of the same script scored between 62% and 100%,
with the count of negatives swinging between 4 and 23. Neither majority nor
union of repeated passes fixed it. Majority was stable but wrong, because
shallow passes outvoted thorough ones; union inherited any single over-inclusive
pass and marked the protagonist's own garage as negative. The instability was in
the task shape, not the sampling. Splitting the work into "record what the film
depicts" and then "judge subjects against that record" dropped the standard
deviation from 14.7 to 3.1, which is what made the remaining errors debuggable
at all.

Current measured results, five trials per draft with a fresh cache each:

| | White draft | Blue draft |
|---|---|---|
| Recall | 100% (sd 0.0) | 100% (sd 0.0) |
| Depiction | 86.2% (sd 4.7) | 87.8% (sd 5.4) |
| Verdict agreement | 68.9% (sd 2.7) | 67.1% (sd 2.9) |

Recall is ranked first because a missed subject never reaches a reviewer and
surfaces later as an uninsurable film, while a false positive costs somebody
thirty seconds. Verdict agreement is deliberately not called accuracy: the
expected verdicts are one experienced reading of standard practice, not fact,
and the residual is concentrated in four subjects that fail in every trial,
which makes them standing disagreements that can be argued about rather than
noise. On one of them the system rules stricter than the fixture, which is the
safe direction for clearance.

An honest caveat we have kept in the repository: re-running identical code
across measurement rounds has moved depiction by about ten points, which is
larger than the gap between some configurations chosen during development. So
several tuning decisions were made inside the noise. Recall is the only figure
that has held across every run.

## Challenges

Model availability turned out to be the hardest infrastructure problem. Gemini
3.x extended thinking is on by default and stalled extraction indefinitely; the
same call with thinking disabled returned in three seconds. The SDK's own
timeout is not honoured on that path, so a hung request had to be bounded with a
wall-clock deadline enforced around it. Model ids differ between AI Studio and
Vertex, so the fallback chain is selected per backend, and calls walk that chain,
demote models that fail repeatedly, and skip retries against per-day quota
errors that cannot succeed.

## What's next

Backing the ledger with Firestore so it survives a Cloud Run cold start, widening
ground truth beyond two drafts of one screenplay, and closing the four standing
verdict disagreements, several of which look like fixture corrections rather
than code changes.
