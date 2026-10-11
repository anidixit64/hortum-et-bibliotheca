# Hand fixes

`answers.jsonl` holds answer names you fixed in the review window
(`uv run hortum-pipeline review-answers`). One line per distinct answer line, matched by
`line_key`, so a single fix covers every identical copy across sets.

The `parse-answers` stage applies these on every run, so they survive rebuilding
`corpus.db`. Commit this file.

`links.jsonl` holds answer groups that were linked to the wrong topic: "rings" (rings in
general) under *The Lord of the Rings*, "Vienna" (the city) under *Vienna Secession*. One
line per group, matched by its answer key, category and topic; `action: unlink` makes the
`link` stage's topic building leave the group out of that topic (its questions get a local
topic of their own answer instead).

The content service's clue cleanup finds these when a topic is first opened; collect them
with `uv run hortum-content export-overrides` (it keeps entries already here, so hand-added
lines are safe), then rebuild from the link stage (`hortum-pipeline all --from link --gui`).
Commit this file.
