import tkinter as tk
from tkinter import messagebox, ttk

from hortum_pipeline.review import ReviewItem, ReviewModel

_ALL = "All categories"


class ReviewWindow:
    """Lists low-confidence answer lines and lets you name each answer by hand."""

    def __init__(self, master: tk.Misc, model: ReviewModel, threshold: float) -> None:
        self.model = model
        self.items: dict[str, ReviewItem] = {}
        self.current: ReviewItem | None = None

        win = master if isinstance(master, tk.Tk) else tk.Toplevel(master)
        self.win = win
        win.title("Review answer parses")
        win.geometry("1180x720")
        win.minsize(900, 560)

        # Filters
        top = ttk.Frame(win, padding=(12, 10))
        top.pack(fill="x")
        ttk.Label(top, text="Confidence below").pack(side="left")
        self.threshold = tk.DoubleVar(value=threshold)
        ttk.Spinbox(
            top,
            from_=0.3,
            to=0.95,
            increment=0.05,
            width=5,
            textvariable=self.threshold,
            command=self.refresh,
        ).pack(side="left", padx=(4, 14))
        ttk.Label(top, text="Category").pack(side="left")
        self.category = tk.StringVar(value=_ALL)
        cat_box = ttk.Combobox(
            top,
            textvariable=self.category,
            values=[_ALL, *model.categories()],
            state="readonly",
            width=18,
        )
        cat_box.pack(side="left", padx=(4, 14))
        cat_box.bind("<<ComboboxSelected>>", lambda _e: self.refresh())
        ttk.Label(top, text="Search").pack(side="left")
        self.search = tk.StringVar()
        search_entry = ttk.Entry(top, textvariable=self.search, width=22)
        search_entry.pack(side="left", padx=(4, 14))
        search_entry.bind("<Return>", lambda _e: self.refresh())
        self.show_fixed = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            top, text="Show fixed", variable=self.show_fixed, command=self.refresh
        ).pack(side="left")
        self.summary = tk.StringVar()
        ttk.Label(top, textvariable=self.summary).pack(side="right")

        # List | detail
        panes = ttk.PanedWindow(win, orient="horizontal")
        panes.pack(fill="both", expand=True, padx=12)

        left = ttk.Frame(panes)
        columns = ("n", "conf", "guess", "line")
        self.tree = ttk.Treeview(left, columns=columns, show="headings", selectmode="browse")
        for col, label, width, anchor in (
            ("n", "Qs", 44, "e"),
            ("conf", "Conf", 50, "e"),
            ("guess", "Parser's guess", 190, "w"),
            ("line", "Answer line", 320, "w"),
        ):
            self.tree.heading(col, text=label)
            self.tree.column(col, width=width, anchor=anchor, stretch=col == "line")  # type: ignore[call-overload]
        self.tree.tag_configure("fixed", foreground="#2e7d32")
        scroll = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="left", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._show_selected())
        panes.add(left, weight=3)

        right = ttk.Frame(panes, padding=(12, 0, 0, 0))
        panes.add(right, weight=2)
        ttk.Label(right, text="Answer line", font=("TkDefaultFont", 12, "bold")).pack(anchor="w")
        self.line_text = tk.Text(right, height=5, wrap="word", relief="flat")
        self.line_text.pack(fill="x", pady=(2, 4))
        self.issues = tk.StringVar()
        ttk.Label(right, textvariable=self.issues, foreground="#b45309").pack(anchor="w")

        ttk.Label(right, text="End of the question(s)", font=("TkDefaultFont", 12, "bold")).pack(
            anchor="w", pady=(10, 0)
        )
        self.giveaway_text = tk.Text(right, height=6, wrap="word", relief="flat")
        self.giveaway_text.pack(fill="x", pady=(2, 8))

        ttk.Label(right, text="Answer name", font=("TkDefaultFont", 12, "bold")).pack(anchor="w")
        self.answer = tk.StringVar()
        self.answer_entry = ttk.Entry(right, textvariable=self.answer, font=("TkDefaultFont", 14))
        self.answer_entry.pack(fill="x", pady=(2, 4))
        self.answer_entry.bind("<Return>", lambda _e: self.save())
        self.answer_entry.bind("<KeyRelease>", lambda _e: self._schedule_suggestions())

        ttk.Label(right, text="Similar answers already in the data (double-click to use)").pack(
            anchor="w", pady=(6, 0)
        )
        self.suggest_list = tk.Listbox(right, height=8, activestyle="none")
        self.suggest_list.pack(fill="both", expand=True, pady=(2, 8))
        self.suggest_list.bind("<Double-Button-1>", lambda _e: self._use_suggestion())
        self._suggestion_names: list[str] = []
        self._suggest_job: str | None = None

        actions = ttk.Frame(right)
        actions.pack(fill="x")
        ttk.Button(actions, text="Save  ⏎", command=self.save).pack(side="left")
        ttk.Button(actions, text="Keep guess", command=self.keep_guess).pack(side="left", padx=6)
        ttk.Button(actions, text="Exclude", command=self.exclude).pack(side="left")
        ttk.Button(actions, text="Undo fix", command=self.undo).pack(side="right")

        # Bottom bar
        bottom = ttk.Frame(win, padding=(12, 10))
        bottom.pack(fill="x")
        self.status = tk.StringVar()
        ttk.Label(bottom, textvariable=self.status).pack(side="left")
        self.rerun_button = ttk.Button(bottom, text="Rerun corrected", command=self.rerun)
        self.rerun_button.pack(side="right")

        self.refresh()

    # -- list -------------------------------------------------------------------------

    def refresh(self) -> None:
        threshold = float(self.threshold.get())
        category = None if self.category.get() == _ALL else self.category.get()
        items = self.model.items(threshold, category, self.search.get(), self.show_fixed.get())
        self.items = {item.line_key: item for item in items}
        self.tree.delete(*self.tree.get_children())
        for item in items:
            line = " ".join(item.answer_text.split())
            self.tree.insert(
                "",
                "end",
                iid=item.line_key,
                values=(item.n_questions, f"{item.confidence:.2f}", item.guess, line),
                tags=("fixed",) if item.fixed else (),
            )
        counts = self.model.counts(threshold)
        self.summary.set(
            f"{counts['lines']:,} lines · {counts['questions']:,} questions below threshold · "
            f"{counts['fixed']:,} fixed"
        )
        self._update_status()
        children = self.tree.get_children()
        if children:
            self.tree.selection_set(children[0])
            self.tree.see(children[0])

    def _show_selected(self) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        item = self.items[selection[0]]
        self.current = item
        self._set_text(self.line_text, item.answer_text)
        issues = item.issues.strip("[]").replace('"', "").replace(",", ", ")
        status = " · fixed" if item.fixed else ""
        self.issues.set(f"Flagged: {issues or '—'} · {item.category}{status}")
        self._set_text(self.giveaway_text, "\n\n".join(self.model.giveaways(item.line_key)))
        fix = self.model.store.get(item.line_key)
        self.answer.set(fix.main if fix else item.guess)
        self._refresh_suggestions()
        self.answer_entry.focus_set()
        self.answer_entry.select_range(0, "end")

    # -- suggestions ------------------------------------------------------------------

    def _schedule_suggestions(self) -> None:
        if self._suggest_job:
            self.win.after_cancel(self._suggest_job)
        self._suggest_job = self.win.after(250, self._refresh_suggestions)

    def _refresh_suggestions(self) -> None:
        self._suggest_job = None
        self.suggest_list.delete(0, "end")
        self._suggestion_names = []
        for s in self.model.suggestions(self.answer.get()):
            self._suggestion_names.append(s.name)
            self.suggest_list.insert("end", f"{s.name}   ({s.n_questions:,} questions)")

    def _use_suggestion(self) -> None:
        selection = self.suggest_list.curselection()  # type: ignore[no-untyped-call]
        if selection:
            self.answer.set(self._suggestion_names[selection[0]])
            self.answer_entry.focus_set()

    # -- actions ----------------------------------------------------------------------

    def save(self) -> None:
        if self.current is None:
            return
        name = self.answer.get().strip()
        if not name:
            messagebox.showinfo("Answer name", "Type a name, or use Exclude.", parent=self.win)
            return
        self.model.save(self.current, name)
        self._advance()

    def keep_guess(self) -> None:
        if self.current is not None:
            self.model.save(self.current, self.current.guess)
            self._advance()

    def exclude(self) -> None:
        if self.current is not None:
            self.model.save(self.current, self.current.guess, exclude=True)
            self._advance()

    def undo(self) -> None:
        if self.current is not None:
            self.model.undo(self.current.line_key)
            self.refresh()

    def rerun(self) -> None:
        pending = len(self.model.pending())
        if not pending:
            self.status.set("Nothing to rerun: every saved fix is already in corpus.db.")
            return
        changed = self.model.rerun_pending()
        self.refresh()
        self.status.set(
            f"Updated {changed:,} questions from {pending:,} fixes. To rebuild topics with them, "
            "run: hortum-pipeline all --from group"
        )

    def _advance(self) -> None:
        """Marks the current row fixed and moves to the next one."""
        assert self.current is not None
        key = self.current.line_key
        next_key = self.tree.next(key)
        if self.show_fixed.get():
            self.tree.item(key, tags=("fixed",))
            self.items[key].fixed = True
        else:
            self.tree.delete(key)
            del self.items[key]
        if next_key:
            self.tree.selection_set(next_key)
            self.tree.see(next_key)
        self._update_status()

    def _update_status(self) -> None:
        pending = len(self.model.pending())
        self.rerun_button.configure(text=f"Rerun corrected ({pending:,})")
        self.status.set(
            f"{pending:,} saved fixes not yet in corpus.db. Fixes are saved to "
            f"{self.model.store.path} as you go."
            if pending
            else f"All saved fixes are applied. Fixes file: {self.model.store.path}"
        )

    @staticmethod
    def _set_text(widget: tk.Text, value: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.configure(state="disabled")
