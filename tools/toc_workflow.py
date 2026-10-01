#!/usr/bin/env python
"""One entry point for human-reviewed EPUB TOC production and acceptance."""

from __future__ import annotations

import argparse
import datetime as dt
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SPEC = ROOT / "toc-workflow" / "specs" / "reviewed-psychology-77-20260911.json"


def run(*args: object) -> None:
    command = [sys.executable, *(str(arg) for arg in args)]
    print("+", " ".join(command))
    try:
        subprocess.run(command, cwd=ROOT, check=True)
    except subprocess.CalledProcessError as error:
        # Gate tools fail by design; propagate their exit code without a traceback.
        raise SystemExit(error.returncode) from None


def review(epub_dir: Path, work_dir: Path) -> None:
    run(
        ROOT / "tools" / "build_toc_review_packets.py",
        epub_dir,
        "--output-dir", work_dir / "review-packets",
        "--summary-csv", work_dir / "review-summary.csv",
    )


def validate(epub_dir: Path, spec: Path, work_dir: Path) -> None:
    run(
        ROOT / "tools" / "apply_epub_toc_coordinates.py",
        epub_dir,
        spec,
        "--evidence-dir", work_dir / "dry-run-evidence",
    )


def acceptance(epub_dir: Path, spec: Path | None, work_dir: Path) -> None:
    command: list[object] = [
        ROOT / "tools" / "validate_epub_toc_acceptance.py",
        epub_dir,
        "--csv-output", work_dir / "acceptance.csv",
    ]
    if spec is not None:
        command.extend(["--spec", spec])
    run(*command)


def resolve(epub_dir: Path, search_spec: Path, output_spec: Path) -> None:
    run(
        ROOT / "tools" / "resolve_toc_search_specs.py",
        epub_dir,
        search_spec,
        output_spec,
    )


def coverage(epub_dir: Path, spec: Path, work_dir: Path, strict_additions: bool) -> None:
    command: list[object] = [
        ROOT / "tools" / "measure_printed_toc_coverage.py",
        epub_dir,
        "--spec", spec,
        "--csv-output", work_dir / "coverage.csv",
    ]
    if strict_additions:
        command.append("--strict-additions")
    run(*command)


def freeze(epub_dir: Path, output_spec: Path) -> None:
    run(ROOT / "tools" / "export_epub_toc_coordinates.py", epub_dir, output_spec)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=["review", "resolve", "coverage", "validate", "apply", "audit", "accept", "freeze"],
    )
    parser.add_argument("epub_dir", type=Path)
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--work-dir", type=Path, default=ROOT / "work" / "toc-workflow")
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--search-spec", type=Path)
    parser.add_argument("--output-spec", type=Path)
    parser.add_argument("--strict-additions", action="store_true")
    args = parser.parse_args()

    epub_dir = args.epub_dir.resolve()
    spec = args.spec.resolve()
    work_dir = args.work_dir.resolve()
    if args.command in {"validate", "apply", "accept", "coverage"} and not spec.is_file():
        parser.error(f"accepted spec not found: {spec}")
    if args.command == "resolve" and (args.search_spec is None or args.output_spec is None):
        parser.error("resolve requires --search-spec and --output-spec")
    if args.command == "freeze" and args.output_spec is None:
        parser.error("freeze requires --output-spec")

    if args.command == "review":
        review(epub_dir, work_dir)
    elif args.command == "resolve":
        resolve(epub_dir, args.search_spec.resolve(), args.output_spec.resolve())
    elif args.command == "coverage":
        coverage(epub_dir, spec, work_dir, args.strict_additions)
    elif args.command == "freeze":
        freeze(epub_dir, args.output_spec.resolve())
    elif args.command == "validate":
        validate(epub_dir, spec, work_dir)
    elif args.command == "audit":
        acceptance(epub_dir, None, work_dir)
    elif args.command == "accept":
        review(epub_dir, work_dir)
        acceptance(epub_dir, spec, work_dir)
    else:
        validate(epub_dir, spec, work_dir)
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_dir = (args.backup_dir or (work_dir / "backups" / stamp)).resolve()
        run(
            ROOT / "tools" / "apply_epub_toc_coordinates.py",
            epub_dir,
            spec,
            "--evidence-dir", work_dir / "applied-evidence",
            "--backup-dir", backup_dir,
            "--apply",
        )
        acceptance(epub_dir, spec, work_dir)
        print(f"Backup: {backup_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
