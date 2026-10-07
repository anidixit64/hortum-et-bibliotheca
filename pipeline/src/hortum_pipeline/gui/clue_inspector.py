"""Shows a question split into clues: colored spans, the power mark, giveaway and notes."""

import json
import random
import sqlite3
import tkinter as tk
from pathlib import Path
from tkinter import ttk

import yaml

_SHADES = ("#dbeafe", "#dcfce7", "#fef9c3", "#fce7f3", "#ede9fe", "#ffedd5")


class ClueInspector:
    def __init__(self, master: tk.Misc, corpus_path: Path, tracers_path: Path) -> None:
        self.conn = sqlite3.connect(f"file:{corpus_path}?mode=ro", uri=True)
        self.tracers: list[tuple[str, str]] = []
        if tracers_path.is_file():
            data = yaml.safe_load(tracers_path.read_text(encoding="utf-8"))
            self.tracers = [(t["id"], t["topic"]) for t in data["tracers"]]

        win = master if isinstance(master, tk.Tk) else tk.Toplevel(master)
        self.win = win
        win.title("Clue inspector")
        win.geometry("1000x680")

        top = ttk.Frame(win, padding=(12, 10))
        top.pack(fill="x")
        ttk.Label(top, text="Tracer").pack(side="left")
        self.tracer_var = tk.StringVar()
        names = [f"{topic}  ({tid[:8]})" for tid, topic in self.tracers]
        box = ttk.Combobox(
            top, textvariable=self.tracer_var, values=names, state="readonly", width=34
        )
        box.pack(side="left", padx=(4, 14))
        box.bind("<<ComboboxSelected>>", lambda _e: self.show(self.tracers[box.current()][0]))
        ttk.Label(top, text="Question ID or topic").pack(side="left")
        self.query = tk.StringVar()
        entry = ttk.Entry(top, textvariable=self.query, width=28)
        entry.pack(side="left", padx=(4, 6))
        entry.bind("<Return>", lambda _e: self.lookup())
        ttk.Button(top, text="Show", command=self.lookup).pack(side="left")
        ttk.Button(top, text="Random question", command=self.random_question).pack(
            side="left", padx=6
        )

        self.header = tk.StringVar()
        ttk.Label(
            win, textvariable=self.header, padding=(12, 0), font=("TkDefaultFont", 12, "bold")
        ).pack(anchor="w")
        self.text = tk.Text(
            win, wrap="word", height=12, relief="flat", padx=10, pady=8, font=("TkDefaultFont", 14)
        )
        self.text.pack(fill="both", expand=True, padx=12, pady=(4, 8))
        for i, shade in enumerate(_SHADES):
            self.text.tag_configure(f"c{i}", background=shade)
        self.text.tag_configure(
            "giveaway", foreground="#6b7280", font=("TkDefaultFont", 14, "italic")
        )
        self.text.tag_configure("note", foreground="#9ca3af", font=("TkDefaultFont", 11))
        self.text.tag_configure("power", foreground="#dc2626", font=("TkDefaultFont", 14, "bold"))
        self.text.tag_configure("selected", underline=True)

        columns = ("n", "kind", "pos", "power", "words", "terms")
        self.table = ttk.Treeview(win, columns=columns, show="headings", height=8)
        for col, label, width in (
            ("n", "#", 30),
            ("kind", "Kind", 70),
            ("pos", "Position", 70),
            ("power", "Before (*)", 80),
            ("words", "Words", 70),
            ("terms", "Key terms", 620),
        ):
            self.table.heading(col, text=label)
            self.table.column(col, width=width, anchor="w")
        self.table.pack(fill="x", padx=12, pady=(0, 6))
        self.table.bind("<<TreeviewSelect>>", lambda _e: self._select())
        self._spans: dict[str, tuple[str, str]] = {}
        self._clue_ids: dict[str, int] = {}

        self.cluster_title = tk.StringVar(
            value="Select a clue to see the same fact in other questions"
        )
        ttk.Label(win, textvariable=self.cluster_title, padding=(12, 0)).pack(anchor="w")
        self.cluster_list = tk.Listbox(win, height=7, activestyle="none")
        self.cluster_list.pack(fill="x", padx=12, pady=(2, 12))

        if self.tracers:
            box.current(0)
            self.show(self.tracers[0][0])

    def lookup(self) -> None:
        query = self.query.get().strip()
        if not query:
            return
        row = self.conn.execute("SELECT id FROM tossups WHERE id = ?", (query,)).fetchone()
        if row is None:
            row = self.conn.execute(
                "SELECT tt.tossup_id FROM topics t JOIN tossup_topics tt ON tt.topic_id = t.id "
                "WHERE t.display_name LIKE ? ORDER BY t.n_tossups DESC, random() LIMIT 1",
                (f"%{query}%",),
            ).fetchone()
        if row:
            self.show(row[0])
        else:
            self.header.set(f"Nothing found for {query!r}")

    def random_question(self) -> None:
        n = self.conn.execute("SELECT COUNT(*) FROM question_layout").fetchone()[0]
        row = self.conn.execute(
            "SELECT tossup_id FROM question_layout LIMIT 1 OFFSET ?", (random.randrange(n),)
        ).fetchone()
        self.show(row[0])

    def show(self, tossup_id: str) -> None:
        layout = self.conn.execute(
            "SELECT clean_text, power_char, n_words FROM question_layout WHERE tossup_id = ?",
            (tossup_id,),
        ).fetchone()
        if layout is None:
            self.header.set(f"{tossup_id}: not split yet (run the clues stage)")
            return
        clean, power_char, n_words = layout
        answer, topic = self.conn.execute(
            "SELECT a.main, t.display_name FROM answer_parses a "
            "LEFT JOIN tossup_topics tt ON tt.tossup_id = a.tossup_id "
            "LEFT JOIN topics t ON t.id = tt.topic_id WHERE a.tossup_id = ?",
            (tossup_id,),
        ).fetchone() or ("?", None)
        parts = [tossup_id, f"answer: {answer}", f"topic: {topic or '(none)'}", f"{n_words} words"]
        self.header.set("   ·   ".join(parts))

        clues = self.conn.execute(
            "SELECT ordinal, kind, char_start, char_end, position, in_power, word_start, "
            "word_end, key_terms, id FROM clues WHERE tossup_id = ? ORDER BY ordinal",
            (tossup_id,),
        ).fetchall()
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", clean)
        if power_char is not None:
            self.text.insert(f"1.0+{power_char}c", "★ ", ("power",))

        def shift(index: int) -> int:
            """Text positions after the inserted "★ " marker move right by two."""
            return index + (2 if power_char is not None and index >= power_char else 0)

        self.table.delete(*self.table.get_children())
        self._spans.clear()
        self._clue_ids.clear()
        for ordinal, kind, start, end, position, in_power, w0, w1, terms, clue_id in clues:
            tag = f"c{ordinal % len(_SHADES)}" if kind == "clue" else kind
            a, b = f"1.0+{shift(start)}c", f"1.0+{shift(end)}c"
            self.text.tag_add(tag, a, b)
            iid = str(ordinal)
            self._spans[iid] = (a, b)
            self._clue_ids[iid] = clue_id
            self.table.insert(
                "",
                "end",
                iid=iid,
                values=(
                    ordinal,
                    kind,
                    f"{position:.0%}",
                    "yes" if in_power else "",
                    f"{w0}–{w1}",
                    ", ".join(json.loads(terms)),
                ),
            )
        self.text.configure(state="disabled")

    def _select(self) -> None:
        self.text.tag_remove("selected", "1.0", "end")
        for iid in self.table.selection():
            a, b = self._spans[iid]
            self.text.tag_add("selected", a, b)
            self.text.see(a)
            self._show_cluster(self._clue_ids[iid])

    def _show_cluster(self, clue_id: int) -> None:
        """Lists how other questions state the same fact (the clue's cluster)."""
        self.cluster_list.delete(0, "end")
        try:
            row = self.conn.execute(
                "SELECT k.id, k.label, k.n_tossups, k.n_sets FROM clue_cluster_members m "
                "JOIN clue_clusters k ON k.id = m.cluster_id WHERE m.clue_id = ?",
                (clue_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            row = None  # the cluster stage hasn't run yet
        if row is None:
            self.cluster_title.set(
                "Not clustered (a giveaway, a note, or the cluster stage hasn't run)"
            )
            return
        cluster_id, label, n_tossups, n_sets = row
        self.cluster_title.set(
            f'Same fact elsewhere · cluster "{label}" · {n_tossups} questions in {n_sets} sets'
        )
        for (text,) in self.conn.execute(
            "SELECT c.text FROM clue_cluster_members m JOIN clues c ON c.id = m.clue_id "
            "WHERE m.cluster_id = ? AND c.id != ? LIMIT 50",
            (cluster_id, clue_id),
        ):
            self.cluster_list.insert("end", text)


def open_inspector(corpus_path: Path, tracers_path: Path) -> None:
    root = tk.Tk()
    ClueInspector(root, corpus_path, tracers_path)
    root.mainloop()
