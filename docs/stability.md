# Measured behaviour

Ten runs, five per draft, each from a cold cache so nothing is reused between
them. Run it yourself with `python -m clearcut.evals.run <fixture>`.

## Results

| | White draft | Blue draft |
|---|---|---|
| Recall | **100%** (sd 0.0) | **100%** (sd 0.0) |
| Depiction | 95% (81–100, sd 7.3) | 91% (78–100, sd 9.0) |
| Verdict agreement | 73% (67–78, sd 4.2) | 69% (59–77, sd 6.9) |

Recall is the number to trust. It did not move once across ten runs of two
drafts, and it is the one that matters most: a subject that is never flagged is
never reviewed, never appears in the report, and turns up later as a picture no
carrier will insure.

The other two carry real spread and should be quoted as ranges. Anyone
reporting a single depiction figure from a single run is quoting a sample, not
a measurement. That mistake was made repeatedly while building this.

## What the spread taught us

Averages hid the most useful finding. Two items failed on **every one of the
ten runs**, which is not variance but a defect:

- **`KJ-4471`, a vehicle plate.** Cleared ten times out of ten. The
  adjudication standard grouped plates with addresses and domains and allowed
  "nothing found" to support a clear ruling. That is sound for a domain, which
  anyone can look up, and wrong for a plate, because registration records are
  not public and a lookup returns nothing for every plate ever written. Silence
  was being read as safety. Plates are now settled by rule, and verdict
  agreement on the White draft went from 73% to 83%.

- **`DR. ALAN REINHOLT`, a doctor whose signature is forged.** The system rules
  must_change where the fixture says legal_review. This one is left alone. The
  system is being stricter than the target, which is the safe direction for
  clearance, and the fixture is arguably the thing that is wrong.

Roughly a quarter of the remaining verdict disagreement is `Coca-Cola` and
`MARTY OKONKWO`, each one category away from the target rather than opposed to
it.

## Reading the fixtures

`THE LONG ODDS` is a test screenplay with deliberately planted clearance
problems. **White** is the original draft and **Blue** the revision, following
the industry convention of printing revised pages on coloured stock. The Blue
draft applies three fixes the White report would have demanded, renames a
street, and adds a scene where a named insurance adjuster approves fraudulent
files on camera. That last change is the interesting one: the company name does
not change between drafts, so a diff on names alone carries the old verdict
forward and passes a defamation risk through a revision unnoticed.
