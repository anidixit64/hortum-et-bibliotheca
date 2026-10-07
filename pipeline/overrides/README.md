# Hand fixes

`answers.jsonl` holds answer names you fixed in the review window
(`uv run hortum-pipeline review-answers`). One line per distinct answer line, matched by
`line_key`, so a single fix covers every identical copy across sets.

The `parse-answers` stage applies these on every run, so they survive rebuilding
`corpus.db`. Commit this file.
