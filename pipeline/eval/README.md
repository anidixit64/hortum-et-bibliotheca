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

## Phase 2 acceptance audit (`phase2_audit.json`)

A fixed random sample of 30 topic pages (seed 20261008, drawn from the 4,094 topics asked
10+ times), read from the records the catalog serves and judged by hand.

```sh
uv run python pipeline/eval/audit_phase2.py sample   # reprint the pages
uv run python pipeline/eval/audit_phase2.py score    # recompute the bounds below
```

| Measure | Result | 95% lower bound |
|---|---|---|
| Top-5 clue correct (real, specific, labeled right, not a repeat) | 142 / 150 | 90.6% |
| Top-5 related topic correct (related, and the right topic for the name) | 135 / 144 | 89.3% |
| Confusion sensible | 8 / 8 | 68.8% |
| Page usable as a whole | 27 / 30 | 76.1% |

**Where the errors come from:**
- **Clues (8 misses):**
  - Four labels are pronunciation guides or fragments: "FAIN-boss", "Q-plus" and "RYE-zee" come from guides without quotation marks, and "in China." and "and that" are fragments.
  - Three picks repeat a higher pick under another label: "Snow Queen" twice, Geiger and Marsden twice, the Asch experiment twice.
- **Related topics (9 misses):** a name resolved to the wrong topic of that name. Examples: Porter's Laura links to Petrarch's, the Barabas of *The Jew of Malta* to the biblical Barabbas, and the poem "Harlem" to the neighborhood.
- **Pages (3 failures):** two come from Phase 1. Plant and polynomial "roots" were merged into one topic, and *Richard III* questions were linked to the 1995 film. The third is *The Jew of Malta*, with four wrong related topics.


`uv run hortum-pipeline verify` runs every stage's checks (they also run automatically
after each stage; a failure stops the pipeline). See `hortum_pipeline/verify.py`.

## Clue labels (Phase 2)

`labeled_clues.yaml` will list, for ~30 topics, the clues worth knowing.
