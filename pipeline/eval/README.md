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

| Measure | Round 1 | Round 2 (after fixes) | 95% lower bound, round 2 |
|---|---|---|---|
| Top-5 clue correct (real, specific, labeled right, not a repeat) | 142 / 150 | 149 / 150 | 96.9% |
| Top-5 related topic correct (related, and the right topic for the name) | 135 / 144 | 135 / 144 | 89.3% |
| Confusion sensible | 8 / 8 | 8 / 8 | 68.8% |
| Page usable as a whole | 27 / 30 | 27 / 30 | 76.1% |

**Round 1** found eight clue misses. Five labels were pronunciation guides or fragments: "FAIN-boss", "Q-plus" and "RYE-zee" (guides without quotation marks), and "in China." and "and that" (fragments). Three picks repeated a higher pick under another label: "Snow Queen", Geiger and Marsden, and the Asch experiment.

**Branch `fix/audit-clue-labels` changed four things:**
- Square-bracketed pronunciations and unquoted ones with a capitalized syllable are stripped.
- Editorial insertions are kept inside quotations ("one must imagine [Sisyphus] happy").
- Quoted fragments that start with a function word are dropped.
- A pick whose label sits inside a higher pick's label, or contains it, is skipped.

**Round 2**, on the same 30 pages, leaves one clue miss: the Asch repeat. Its labels, "informational" and "Solomon Asch", share no words.

**Related topics are unchanged, and the 9 misses stay.** Each is a name pointing at the wrong topic of that name: Porter's Laura → Petrarch's, the Barabas of *The Jew of Malta* → the biblical Barabbas and a Hungarian village, the poem "Harlem" → the neighborhood.

Two fixes were tried and measured, and neither helped:
- **Gating weak names on clue similarity:** wrong links scored 0.54–0.80, inside the range of correct ones. The Barabbas topic's questions are themselves about Marlowe's Barabas, linked to the wrong article in Phase 1.
- **Demoting one-word names mentioned far more widely than their topic is asked:** all 9 errors stayed in the top 5, and correct rare names (Vayu, Cithaeron) were demoted instead.

These errors, and the two failing pages, come from Phase 1 topic identity: plant and polynomial "roots" are merged into one topic, and *Richard III* is linked to the 1995 film. They belong to a Phase 1 cleanup pass.

## Stage checks

`uv run hortum-pipeline verify` runs every stage's checks (they also run automatically
after each stage; a failure stops the pipeline). See `hortum_pipeline/verify.py`.

## Clue labels (Phase 2)

`labeled_clues.yaml` will list, for ~30 topics, the clues worth knowing.
