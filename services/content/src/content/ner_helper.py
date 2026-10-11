"""Named entities for batches of sentences, run by the NER environment's Python.

Standalone on purpose (no imports from this package): the transformer model needs
PyTorch, whose Intel-Mac builds pin an older numpy than the rest of the project, so it
lives in its own environment (``make ner-env``). The worker starts this once and keeps
it: one JSON line in, one JSON line out, so the model loads only once.

    .venv-ner/bin/python -P ner_helper.py
    in:  {"sentences": [...]}
    out: {"ents": [[[text, label], ...], ...]}
"""

import json
import sys


def main() -> None:
    import spacy

    nlp = spacy.load("en_core_web_trf", disable=["lemmatizer"])
    print(json.dumps({"ready": True}), flush=True)
    for line in sys.stdin:
        sentences = json.loads(line)["sentences"]
        ents = [[[e.text, e.label_] for e in doc.ents] for doc in nlp.pipe(sentences)]
        print(json.dumps({"ents": ents}), flush=True)


if __name__ == "__main__":
    main()
