import argparse
import sys
from collections.abc import Sequence

from hortum_pipeline.config import PipelineSettings
from hortum_pipeline.progress import ConsoleReporter, Reporter
from hortum_pipeline.stages import STAGES, STAGES_BY_NAME, Stage

EXIT_NOT_IMPLEMENTED = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hortum-pipeline",
        description="Build data/build/corpus.db from the raw tossup dump.",
    )
    gui = argparse.ArgumentParser(add_help=False)
    gui.add_argument("--gui", action="store_true", help="Show a progress window")
    gui.add_argument(
        "--threshold", type=float, help="Review answers below this confidence (default 0.8)"
    )

    gui.add_argument(
        "--max-requests",
        type=int,
        help="Link/facts: stop after this many new web requests (cached ones are free)",
    )
    gui.add_argument(
        "--min-questions", type=int, help="Link: only search groups with this many questions"
    )

    sub = parser.add_subparsers(dest="command", required=True, metavar="STAGE")
    all_cmd = sub.add_parser("all", parents=[gui], help="Run every stage in order")
    all_cmd.add_argument(
        "--from", dest="start", choices=list(STAGES_BY_NAME), help="Resume from this stage"
    )
    for stage in STAGES:
        sub.add_parser(stage.name, parents=[gui], help=stage.summary)
    sub.add_parser(
        "review-answers", parents=[gui], help="Open the review window for low-confidence answers"
    )
    return parser


def run_stage(stage: Stage, settings: PipelineSettings, reporter: Reporter) -> int:
    if stage.run is None:
        reporter.log(
            f"stage '{stage.name}' is not implemented yet (build plan phase {stage.phase})"
        )
        return EXIT_NOT_IMPLEMENTED
    reporter.log(f"==> {stage.name}: {stage.summary}")
    stage.run(settings, reporter)
    return 0


def run_stages(stages: Sequence[Stage], settings: PipelineSettings, reporter: Reporter) -> int:
    for stage in stages:
        if code := run_stage(stage, settings, reporter):
            return code
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = PipelineSettings()
    updates: dict[str, object] = {}
    if args.threshold is not None:
        updates["review_threshold"] = args.threshold
    if args.max_requests is not None:
        updates["link_new_requests"] = args.max_requests
    if args.min_questions is not None:
        updates["link_min_tossups"] = args.min_questions
    settings = settings.model_copy(update=updates)

    if args.command == "review-answers":
        return _open_review(settings)

    if args.command == "all":
        names = [stage.name for stage in STAGES]
        stages = STAGES[names.index(args.start) if args.start else 0 :]
    else:
        stages = (STAGES_BY_NAME[args.command],)

    if not args.gui:
        return run_stages(stages, settings, ConsoleReporter())

    from hortum_pipeline.gui.app import run_with_window  # Tk is only needed with --gui

    reviewable = any(stage.name == "parse-answers" for stage in stages)
    return run_with_window(stages, settings, reviewable, run_stages)


def _open_review(settings: PipelineSettings) -> int:
    if not settings.corpus_path.is_file():
        print("corpus.db not found; run 'ingest' and 'parse-answers' first", file=sys.stderr)
        return 1
    from hortum_pipeline.gui.app import open_review

    open_review(settings)
    return 0


if __name__ == "__main__":
    sys.exit(main())
