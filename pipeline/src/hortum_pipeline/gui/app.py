import tkinter as tk
from collections.abc import Callable, Sequence

from hortum_pipeline.config import PipelineSettings
from hortum_pipeline.gui.progress_window import ProgressWindow
from hortum_pipeline.gui.review_window import ReviewWindow
from hortum_pipeline.progress import Reporter
from hortum_pipeline.review import ReviewModel
from hortum_pipeline.stages import Stage

Runner = Callable[[Sequence[Stage], PipelineSettings, Reporter], int]


def run_with_window(
    stages: Sequence[Stage], settings: PipelineSettings, reviewable: bool, runner: Runner
) -> int:
    root = tk.Tk()
    review: ReviewWindow | None = None

    def open_review() -> None:
        nonlocal review
        if review is not None and review.win.winfo_exists():
            review.win.lift()
            return
        model = ReviewModel(settings.corpus_path, settings.answer_overrides_path)
        review = ReviewWindow(root, model, settings.review_threshold)

    title = "hortum-pipeline: " + (stages[0].name if len(stages) == 1 else "all stages")
    window = ProgressWindow(root, title, open_review if reviewable else None)
    return window.run(lambda reporter: runner(stages, settings, reporter))


def open_review(settings: PipelineSettings) -> None:
    root = tk.Tk()
    model = ReviewModel(settings.corpus_path, settings.answer_overrides_path)
    ReviewWindow(root, model, settings.review_threshold)
    root.mainloop()
