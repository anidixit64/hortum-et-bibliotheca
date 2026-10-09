import tkinter as tk
from collections.abc import Callable, Sequence

from hortum_pipeline.config import PipelineSettings
from hortum_pipeline.gui.clue_inspector import ClueInspector
from hortum_pipeline.gui.progress_window import ProgressWindow
from hortum_pipeline.gui.review_window import ReviewWindow
from hortum_pipeline.progress import Reporter
from hortum_pipeline.review import ReviewModel
from hortum_pipeline.stages import Stage

Runner = Callable[[Sequence[Stage], PipelineSettings, Reporter], int]


def run_with_window(stages: Sequence[Stage], settings: PipelineSettings, runner: Runner) -> int:
    root = tk.Tk()

    def open_review() -> None:
        model = ReviewModel(settings.corpus_path, settings.answer_overrides_path)
        ReviewWindow(root, model, settings.review_threshold)

    def open_clues() -> None:
        ClueInspector(root, settings.corpus_path, settings.tracers_path)

    names = {stage.name for stage in stages}
    actions = []
    if "parse-answers" in names:
        actions.append(("Review low-confidence answers", open_review))
    if names & {"clues", "cluster"}:
        actions.append(("Inspect clues", open_clues))
    title = "hortum-pipeline: " + (stages[0].name if len(stages) == 1 else "all stages")
    window = ProgressWindow(root, title, actions)
    return window.run(lambda reporter: runner(stages, settings, reporter))


def open_review(settings: PipelineSettings) -> None:
    root = tk.Tk()
    model = ReviewModel(settings.corpus_path, settings.answer_overrides_path)
    ReviewWindow(root, model, settings.review_threshold)
    root.mainloop()
