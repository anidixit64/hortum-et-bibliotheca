# Evaluation

## Phase 1 acceptance audit (`phase1_audit.json`)

A fixed random sample of 100 questions (seed 20261007, drawn uniformly from `tossups`),
each judged by hand: is the parsed answer right, and is its topic the right Wikipedia
article (unlinked counts as right only when no single article fits)?

```sh
uv run python pipeline/eval/audit.py sample   # reprint the sample
uv run python pipeline/eval/audit.py score    # recompute the bounds below
```

| Measure | Result | 95% lower bound | P(≥ 90%) |
|---|---|---|---|
| Answer parsed correctly | 98 / 100 | 93.8% | 0.998 |
| Link correct, among linked questions (precision) | 90 / 93 | 91.9% | 0.988 |
| Question has the correct link (coverage) | 90 / 100 | 83.6% | 0.430 |

Lower bounds are one-sided Clopper–Pearson; P(≥ 90%) uses a uniform prior.

Phase 1 required parsing and link precision of about 90%; both hold with >95% probability.
Coverage is the weak spot: 7 of the 10 misses were left unlinked although an article
exists (e.g. "Horatio Herbert Kitchener, First Earl Kitchener", "Alfred Jules 'Freddie'
Ayer": the right article is a candidate but scores under the bar without a title match).
Two parse misses come from source HTML with no space between a tag and the next word
("MississippiRiver").

## Stage checks

`uv run hortum-pipeline verify` runs every stage's checks (they also run automatically
after each stage; a failure stops the pipeline). See `hortum_pipeline/verify.py`.

## Clue labels (Phase 2)

`labeled_clues.yaml` will list, for ~30 topics, the clues worth knowing.
