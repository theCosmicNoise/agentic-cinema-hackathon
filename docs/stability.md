# Stability run

Five independent trials per fixture, each with a cold cache, run against the
code at commit time. Numbers are percentages.

| Fixture | Trial | Recall | Depiction | Verdict |
|---|---|---|---|---|
| v1 | 1 | 100 | 88 | 72 |
| v1 | 2 | 94 | 87 | 76 |
| v1 | 3 | 100 | 88 | 72 |
| v1 | 4 | 100 | 88 | 72 |
| v1 | 5 | 100 | 94 | 67 |
| v2 | 1 | 100 | 94 | 59 |
| v2 | 2 | 95 | 41 | 62 |
| v2 | 3 | 100 | 83 | 71 |
| v2 | 4 | 95 | 94 | 69 |
| v2 | 5 | 80 | 93 | 86 |

## Summary

| Fixture | Measure | Mean | Range | Std dev |
|---|---|---|---|---|
| v1 | recall | 98.9 | 94.4–100.0 | 2.2 |
| v1 | depiction | 88.6 | 86.7–93.8 | 2.6 |
| v1 | verdict | 72.0 | 66.7–76.5 | 3.1 |
| v2 | recall | 94.0 | 80.0–100.0 | 7.3 |
| v2 | depiction | 81.2 | 41.2–94.4 | 20.4 |
| v2 | verdict | 69.3 | 58.8–85.7 | 9.2 |

## What this says

The White draft holds together. Standard deviation is 2.2 to 3.1 across all
three measures, which is tight enough to tell one configuration from another.

The Blue draft does not. Depiction ranges from 41.2 to 94.4 with a standard
deviation of 20.4, because one trial collapsed the way the single-call version
used to. Splitting the pass into findings and judgement made that failure rarer
but did not remove it.

Recall is not 100 percent. Earlier sessions reported it as flat 18/18 on samples
of one to three runs; over five it averages 98.9 on White and 94.0 on Blue, with
one Blue trial dropping to 80 and losing three planted subjects at once.

## Errors that recur rather than drift

| Item | Trials affected | Nature |
|---|---|---|
| KJ-4471 verdict | 10 of 10 | Ruled clear, target says must_change. Systematic, not noise. |
| DR. ALAN REINHOLT verdict | 10 of 10 | Ruled must_change, target says legal_review. Stricter than target, which is the safe direction. |
| Coca-Cola verdict | 6 of 10 | Ruled clear, target says clear_with_caution. One category apart. |
| MERIDIAN AUTO BODY recall | 4 of 10 | Extracted from a scene heading inconsistently. |
