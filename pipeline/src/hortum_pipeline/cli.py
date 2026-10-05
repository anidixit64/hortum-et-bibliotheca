import argparse
import sys
from collections.abc import Sequence

from hortum_pipeline.config import PipelineSettings
from hortum_pipeline.stages import STAGES, STAGES_BY_NAME, Stage

EXIT_NOT_IMPLEMENTED = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hortum-pipeline",
        description="Build data/build/corpus.db from the raw tossup dump.",
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="STAGE")
    all_cmd = sub.add_parser("all", help="Run every stage in order")
    all_cmd.add_argument(
        "--from", dest="start", choices=list(STAGES_BY_NAME), help="Resume from this stage"
    )
    for stage in STAGES:
        sub.add_parser(stage.name, help=stage.summary)
    return parser


def run_stage(stage: Stage, settings: PipelineSettings) -> int:
    if stage.run is None:
        print(
            f"stage '{stage.name}' is not implemented yet (build plan phase {stage.phase})",
            file=sys.stderr,
        )
        return EXIT_NOT_IMPLEMENTED
    print(f"==> {stage.name}: {stage.summary}")
    stage.run(settings)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = PipelineSettings()

    if args.command != "all":
        return run_stage(STAGES_BY_NAME[args.command], settings)

    names = [stage.name for stage in STAGES]
    start = names.index(args.start) if args.start else 0
    for stage in STAGES[start:]:
        if code := run_stage(stage, settings):
            return code
    return 0


if __name__ == "__main__":
    sys.exit(main())
