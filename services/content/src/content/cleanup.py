"""Clue cleanup: an AI pass over a topic's top clue candidates, run the first time the
topic is opened, stored, and reused until the candidates change.

The model only *edits*: for each candidate it may keep it, rename it (fix its edges, give
the full title), drop it (generic, the answer itself, about another answer, junk), merge
it into another candidate (same thing: alias, spelling, translation, short and full
form), or remove spellings that belong to something else. It never writes numbers. Code
checks every edit, applies the valid ones, and recounts each clue from the questions
behind its spellings, so the ranking stays purely "how many questions name it".

Named entities from spaCy's transformer model (when ``ner_python`` is set) are passed as
hints: the full title a fragment comes from, the name a descriptor sits in front of.
"""

import difflib
import json
import re
import subprocess
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROMPT_VERSION = 3  # 2: descriptors, pairs, case, misspellings; 3: off-topic answer groups
CANDIDATES = 25  # the cleanup sees this many; the page shows the top 10, then 5 at a time
EXAMPLES = 3
MAX_LABEL_WORDS = 9

SYSTEM = """You clean up lists of quiz bowl clues. A clue is a term (a name, title, quoted \
line or noun phrase) that quiz bowl questions about one answer mention; a player learns \
clues to recognize the answer early. Each candidate comes with how many questions name it, \
its spellings with their question counts, a few example sentences from the questions \
("this man", "these structures" etc. stand for the answer), and sometimes a named-entity \
hint. You return one edit per candidate. You never change counts or order: code recounts \
and ranks after your edits."""

INSTRUCTIONS = """Answer: {name} (category: {category})

For EVERY candidate, return one edit:
- "keep": it is a good, clean clue for this answer.
- "rename": the clue is right but its label isn't. Give a better "label". Fix every one \
of these you see:
  * a fragment of a longer title or name -> the full one ("Pillar" -> "The City and the \
Pillar", "Daggers" -> "Plot of the Three Daggers", "Heinz" -> "Heinz dilemma")
  * descriptor words around a name that aren't part of it -> the bare name ("Newfoundland \
dog Seaman" -> "Seaman", "Siemens-Schuckert company" -> "Siemens-Schuckert", "Peter \
Sargeant novels" -> "Peter Sargeant", "Romanesque Rotunda di San Lorenzo" -> "Rotunda di San \
Lorenzo", "Lucius Lamar of Mississippi" -> "Lucius Lamar"); a title that is part of how the \
person is known stays ("King Mark", "Dr. Bledsoe")
  * a stray verb or noun stuck on ("Ufa lies" -> "Ufa", "Lamachus's death" -> "Lamachus")
  * two separate names joined by "and" -> the one the sentences are mostly about, unless \
the pair is itself one well-known name ("Barnum and Bailey", "Rosencrantz and Guildenstern")
  * a needless plural -> singular; wrong capitalization -> the usual form ("fock state" -> \
"Fock state", "Ijk" -> "ijk", a person's or work's name capitalized)
  * a misspelling copied from a question -> the correct spelling ("Vincente de Valverde" -> \
"Vicente de Valverde", "Stetter reation" -> "Stetter reaction")
Use the words of its spellings, example sentences or hint (fixing their spelling is fine). \
Keep it short (a name, title, or 1-5 word phrase; a famous quotation may be longer).
- "drop" with a "reason": "generic" (a common word or phrase that teaches nothing about \
this answer: "judgment", "Egypt" for a war Egypt fought in, "TV appearance"), \
"answer_itself" (the answer's own name or a stand-in for it), "other_answer" (its \
sentences are about a different thing than {name}, e.g. a different work or person of the \
same name), "junk" (a pronunciation guide, notation, an answer-line note, a broken fragment).
- "merge": it is the same thing as another candidate; give "into" (that candidate's id). \
Same thing means: spellings or transliterations (Simurgh / Simorgh), translations or \
aliases (lodgers / boarders / tenants; Robin / Dick Grayson), a short and a full form \
(Heinz / Heinz dilemma), or two pieces of one title or quotation. Two different things that \
appear together (a character and the book) are NOT the same: keep both. Merge into the one \
whose label is the better name; rename that one if needed.

Also, for any edit except drop, you may list "remove_spellings": spellings of the candidate \
that refer to something else (e.g. a "Willy" spelling under "Willy Wonka" whose sentences \
are about a different Willy).

Candidates (JSON):
{candidates}"""

GROUP_SYSTEM = """You check how quiz bowl questions were filed. Each question has an \
answer line; questions were grouped by answer and linked to a topic. You find answer groups \
that were linked to the wrong topic."""

GROUPS = """Topic: {name} (category: {category})

The questions were filed under {name} by their answer lines, in these answer groups. Some \
groups may be a DIFFERENT answer that got filed here by mistake: a generic word ("rings" \
meaning rings in general, under The Lord of the Rings), a place or thing the topic is only \
named after ("Vienna" the city, under Vienna Secession), a whole set under one member ("piano \
concertos by Beethoven" under Piano Concerto No. 5), a larger subject ("Lewis and Clark \
expedition" under Meriwether Lewis), or a different person, work or sense of the same name \
(Ajax the Lesser under Ajax the Great; "translation" in physics under translation between \
languages). Return their ids in "off_topic_groups" ([] if all are about {name}). Variants \
of the name, plurals and fuller forms of the same thing are NOT off-topic.

Answer groups (JSON):
{group_json}"""

GROUP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"off_topic_groups": {"type": "array", "items": {"type": "integer"}}},
    "required": ["off_topic_groups"],
}

MAX_EXCLUDED_SHARE = 0.5  # never drop more than half a topic's questions

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "edits": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "action": {"type": "string", "enum": ["keep", "rename", "drop", "merge"]},
                    "label": {"type": "string"},
                    "into": {"type": "integer"},
                    "reason": {"type": "string"},
                    "remove_spellings": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id", "action"],
            },
        },
    },
    "required": ["edits"],
}

_WORD = re.compile(r"\w+(?:['’-]\w+)*")
_STOP = frozenset(
    [
        "a",
        "an",
        "the",
        "of",
        "and",
        "or",
        "in",
        "on",
        "at",
        "to",
        "for",
        "by",
        "with",
        "from",
        "as",
        "is",
        "was",
        "this",
        "these",
        "that",
    ]
)
_HINT_LABELS = {"PERSON", "WORK_OF_ART", "ORG", "GPE", "LOC", "EVENT", "FAC", "LAW", "PRODUCT"}
_WHOLE = {"WORK_OF_ART", "EVENT", "LAW", "ORG", "FAC", "PRODUCT"}


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return text.lower()


def words(text: str) -> set[str]:
    return {w for w in _WORD.findall(_fold(text)) if w not in _STOP}


def known_word(word: str, source: set[str]) -> bool:
    """A label word must come from the clue's own text, or be a corrected spelling of one
    of its words ("vicente" for "vincente", "reaction" for "reation")."""
    if word in source:
        return True
    if len(word) < 5:
        return False
    return any(
        abs(len(w) - len(word)) <= 2 and difflib.SequenceMatcher(None, w, word).ratio() >= 0.8
        for w in source
        if len(w) >= 4
    )


# --- named-entity hints --------------------------------------------------------------


class Ner:
    """The NER helper as a long-running process (the model takes ~20 s to load): started
    on first use, restarted once if it dies. Off when ``python`` is empty."""

    def __init__(self, python: str) -> None:
        self.python = python
        self.process: subprocess.Popen[str] | None = None

    def _start(self) -> subprocess.Popen[str]:
        helper = Path(__file__).with_name("ner_helper.py")
        process = subprocess.Popen(
            [self.python, "-P", str(helper)],  # -P: its folder's http.py mustn't shadow http
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        assert process.stdout is not None
        json.loads(process.stdout.readline())  # {"ready": true} once the model is loaded
        return process

    def entities(self, sentences: list[str]) -> list[list[list[str]]]:
        """Entities per sentence, or [] when NER is off or fails."""
        if not self.python or not sentences:
            return []
        for _ in range(2):
            try:
                if self.process is None or self.process.poll() is not None:
                    self.process = self._start()
                assert self.process.stdin is not None and self.process.stdout is not None
                self.process.stdin.write(json.dumps({"sentences": sentences}) + "\n")
                self.process.stdin.flush()
                ents: list[list[list[str]]] = json.loads(self.process.stdout.readline())["ents"]
                return ents
            except (OSError, ValueError, KeyError, AssertionError):
                self.close()
        return []

    def close(self) -> None:
        if self.process is not None:
            self.process.kill()
            self.process = None


def ner_hint(label: str, ents: list[list[list[str]]]) -> str | None:
    """The entity a label is cut from or sits at the end of, in most of its sentences:
    "Pillar" -> "The City and the Pillar", "Newfoundland dog Seaman" -> "Seaman"."""
    votes: dict[str, int] = {}
    low = _fold(label)
    for sentence in ents:
        for text, kind in sentence:
            if kind not in _HINT_LABELS:
                continue
            name = re.sub(r"['’]s$", "", text).strip()
            name = re.sub(r"^(?:the|a|an) ", "", name)  # "the U.S. Military Academy"
            folded = _fold(name)
            if folded == low:
                continue
            grows = kind in _WHOLE and re.search(rf"(?<!\w){re.escape(low)}(?!\w)", folded)
            trims = low.endswith(" " + folded) and " of " not in low[: -len(folded)]
            if (grows and len(name.split()) <= MAX_LABEL_WORDS) or trims:
                votes[name] = votes.get(name, 0) + 1
    if not votes:
        return None
    best, count = max(votes.items(), key=lambda kv: kv[1])
    return best if count * 2 >= len([s for s in ents if s]) or count >= 2 else None


# --- the request -----------------------------------------------------------------------


def group_prompt(found: dict[str, Any]) -> str:
    groups = found.get("groups") or []
    return GROUPS.format(
            name=found["name"],
            category=found.get("category") or "unknown",
            group_json=json.dumps(
                [
                    {
                        "id": g["id"],
                        "answer": g["answer"],
                        "category": g["category"],
                        "questions": len(g["tossups"]),
                        "example": g["example"][:200],
                    }
                    for g in groups
                ],
                ensure_ascii=False,
                indent=1,
            ),
        )  # fmt: skip


def prompt(found: dict[str, Any], hints: dict[int, str]) -> str:
    candidates = [
        {
            "id": c["id"],
            "label": c["label"],
            "questions": c["n_questions"],
            "spellings": {s: len(t) for s, t in c["spellings"].items()},
            "examples": c["sentences"][:EXAMPLES],
            **({"hint": hints[c["id"]]} if c["id"] in hints else {}),
        }
        for c in found["candidates"]
    ]
    return INSTRUCTIONS.format(
        name=found["name"],
        category=found.get("category") or "unknown",
        candidates=json.dumps(candidates, ensure_ascii=False, indent=1),
    )


@dataclass
class Checked:
    """The model's edits that passed, and the ones that didn't (with why)."""

    renames: dict[int, str] = field(default_factory=dict)
    drops: dict[int, str] = field(default_factory=dict)
    merges: dict[int, int] = field(default_factory=dict)
    removed: dict[int, set[str]] = field(default_factory=dict)
    excluded_groups: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)


def check(
    found: dict[str, Any],
    data: dict[str, Any],
    hints: dict[int, str],
    off_topic_ids: list[Any] | None = None,
) -> Checked:
    """Keep only edits that can't invent anything: known ids, renames whose words come
    from the clue's own spellings, sentences or hint, merges into kept candidates."""
    by_id = {c["id"]: c for c in found["candidates"]}
    out = Checked()
    for edit in data.get("edits", []):
        cid, action = edit.get("id"), edit.get("action")
        if cid not in by_id:
            out.rejected.append(f"unknown id {cid}")
            continue
        clue = by_id[cid]
        removed = {s for s in edit.get("remove_spellings") or [] if s in clue["spellings"]}
        if removed and len(removed) < len(clue["spellings"]):
            out.removed[cid] = removed
        if action == "drop":
            out.drops[cid] = str(edit.get("reason") or "")
        elif action == "merge":
            into = edit.get("into")
            if into in by_id and into != cid:
                out.merges[cid] = into
            else:
                out.rejected.append(f"merge {cid} into unknown {into}")
        elif action == "rename":
            label = str(edit.get("label") or "").strip()
            source = " ".join([*clue["spellings"], *clue["sentences"], hints.get(cid, "")])
            if not label or len(label.split()) > MAX_LABEL_WORDS * 3:
                out.rejected.append(f"rename {cid}: empty or too long")
            elif not all(known_word(w, words(source) | words(clue["label"])) for w in words(label)):
                out.rejected.append(f"rename {cid}: {label!r} uses words not in its sentences")
            else:
                out.renames[cid] = label
    out.excluded_groups, notes = off_topic(found, off_topic_ids or [])
    out.rejected += notes
    # A merge into something dropped or merged onward follows the chain; cycles are undone.
    for cid in list(out.merges):
        seen = {cid}
        target = out.merges[cid]
        while target in out.merges and target not in seen:
            seen.add(target)
            target = out.merges[target]
        if target in seen or target in out.drops:
            out.rejected.append(f"merge {cid}: target dropped or circular")
            del out.merges[cid]
        else:
            out.merges[cid] = target
    return out


def _stem(word: str) -> str:
    return word[:-1] if len(word) > 3 and word.endswith("s") else word


def names_topic(answer: str, title: str) -> bool:
    """Does an answer line name the topic ("Piano Concerto No. 5 by Beethoven" for "Piano
    Concerto No. 5 (Beethoven)", "Patterns" for "Pattern")?"""
    want = {_stem(w) for w in words(re.sub(r"\s*\(.*\)$", "", title))}
    also = {_stem(w) for w in words(" ".join(re.findall(r"\((.*)\)", title)))}
    have = {_stem(w) for w in words(answer)}
    # A name with several more words is a bigger subject: "Meriwether Lewis and William
    # Clark expedition" isn't Meriwether Lewis.
    return bool(want) and want <= have and len(have - want - also) <= 2


def off_topic(found: dict[str, Any], ids: list[Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """The answer groups to leave out, within guardrails: a group naming the topic in the
    topic's own subject stays ("translation" in physics may go from the linguistic topic),
    and a group naming the topic must remain; failing that, at most half the questions go."""
    groups = {g["id"]: g for g in found.get("groups") or []}
    if not groups:
        return [], []
    title, category = found["name"], found.get("category")
    total = sum(len(g["tossups"]) for g in groups.values())
    chosen: list[dict[str, Any]] = []
    notes = []
    for gid in dict.fromkeys(ids):
        group = groups.get(gid)
        if group is None:
            notes.append(f"off-topic group {gid}: unknown")
        elif names_topic(group["answer"], title) and group["category"] == category:
            notes.append(f"off-topic group {gid}: names the topic in its own subject")
        else:
            chosen.append(group)
    left = [g for g in groups.values() if g not in chosen]
    if not any(names_topic(g["answer"], title) for g in left):
        while chosen and sum(len(g["tossups"]) for g in chosen) > MAX_EXCLUDED_SHARE * total:
            dropped = max(chosen, key=lambda g: len(g["tossups"]))
            chosen.remove(dropped)
            notes.append(f"off-topic group {dropped['id']}: would leave under half the questions")
    return chosen, notes


def problem(found: dict[str, Any], data: dict[str, Any]) -> str | None:
    """Why a reply can't be used at all (asked again once), or None."""
    edits = data.get("edits")
    if not isinstance(edits, list) or not edits:
        return "no edits"
    known = {c["id"] for c in found["candidates"]}
    covered = {e.get("id") for e in edits if isinstance(e, dict)}
    if len(covered & known) < len(known) * 0.8:
        return f"edits cover only {len(covered & known)} of {len(known)} candidates"
    return None


def apply(found: dict[str, Any], checked: Checked) -> list[dict[str, Any]]:
    """The cleaned clues, recounted from their questions (less any off-topic answer
    groups') and ranked by them."""
    outside = {t for g in checked.excluded_groups for t in g["tossups"]}
    groups: dict[int, dict[str, Any]] = {}
    for clue in found["candidates"]:
        cid = clue["id"]
        if cid in checked.drops:
            continue
        home = checked.merges.get(cid, cid)
        questions = set()
        spellings = []
        for spelling, tossups in clue["spellings"].items():
            if spelling in checked.removed.get(cid, set()):
                continue
            mine = set(tossups) - outside
            if mine:
                questions |= mine
                spellings.append(spelling)
        group = groups.setdefault(home, {"ids": [], "questions": set(), "spellings": []})
        group["ids"].append(cid)
        group["questions"] |= questions
        group["spellings"] += spellings
    by_id = {c["id"]: c for c in found["candidates"]}
    cleaned = []
    for home, group in groups.items():
        if not group["questions"] or home not in by_id:
            continue
        ids = [home] + [i for i in group["ids"] if i != home]
        cleaned.append(
            {
                "label": checked.renames.get(home, by_id[home]["label"]),
                "n_questions": len(group["questions"]),
                "clue_ids": ids,  # the corpus clues it's made of, the first its home
                "spellings": group["spellings"],
                "rank_before": by_id[home]["rank"],
            }
        )
    cleaned.sort(key=lambda c: (-c["n_questions"], c["rank_before"]))
    for rank, clue in enumerate(cleaned, start=1):
        clue["rank"] = rank
    return cleaned
