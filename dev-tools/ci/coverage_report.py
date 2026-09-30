#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""One coverage report out of every job's coverage data, and the gate that reads it.

CI measures coverage in five jobs -- `Pytest`, `Behave`, both example sweeps and
`Repo //pub` -- each fanned out over operating systems and interpreters, and each
covering a different part of the same source. No one of those numbers means
anything on its own: the pytest job never runs a CAD sandbox, the behave job
drives the installed `pc` and never imports a unit-test helper, and the example
sweeps walk success paths and nothing else. What a reader wants is the union,
which is what Codecov used to compute after every job posted to it.

This script is that union, computed in the repository instead of a third-party
service, in three steps that the "Coverage" job in `test.yml` runs as three
steps of its own:

  `merge`   Combine every `.coverage` data file the run produced into one, and
            write the HTML, Cobertura and JSON reports from it. The union is
            `coverage combine`'s, not this script's: line numbers are unioned
            per file, so a line executed by behave on Windows and missed by
            pytest on Linux counts as covered once. `[paths]` in
            `dev-tools/coverage.rc` is what lets it recognise the same file
            recorded under three different roots -- see the comment there.

  `render`  Turn the merged JSON into the markdown that goes into the job
            summary and into the pull request comment. Kept separate from
            `merge` because the comment carries a link to the uploaded HTML
            report, and that URL does not exist until the artifact is uploaded,
            which cannot happen until `merge` has produced the report.

  `check`   Apply the coverage requirement and exit non-zero if it is not met.
            Separate again so that the pull request is updated first: a red gate
            with no comment explaining it is a gate nobody can act on.

The requirement is a floor under *patch* coverage -- the statements this pull
request added or changed -- and the floor is the project's own statement
coverage in the same run. Nothing is stored between runs and nothing is compared
with history: the bar is "cover what you write at least as well as this
repository is already covered", which is self-calibrating and cannot go red on
the day it lands. `--min-patch` takes an absolute percentage instead, and
`--patch-tolerance` allows a slack in percentage points, for when that is the
policy somebody wants.

Two rates are reported and they are not interchangeable, which is why both are
in the table rather than one blended number. coverage.py's headline rate counts
branches as well as statements (`branch = True` in `coverage.rc`), and a diff
cannot say which arcs of a partially-taken branch are "new". So the requirement
is stated in statements at both ends -- patch against project -- and the branch
and overall rates are reported beside them for the reader.
"""

import argparse
import configparser
import fnmatch
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from coverage.sqldata import CoverageData

# What marks this script's comment on a pull request as this script's, so that
# the next run edits it rather than adding a second one. `pr_comment.py` matches
# on it; it is invisible in rendered markdown.
COMMENT_MARKER = "<!-- partcad-coverage-report -->"

# The packages the report groups files by, in the order they are listed. Each is
# a path prefix in the merged data, which `[paths]` in `dev-tools/coverage.rc`
# has already rewritten every recording of that file into. The list is written
# out rather than derived from the tree for the reason `coverage.rc` writes its
# `include` list out: a package nobody named is a package nobody notices the
# absence of, and `tests/dev_tools/test_coverage_report.py` fails when this and
# `src/` disagree.
PACKAGES = [
    "src/partcad",
    "src/partcad_cli",
    "src/partcad_client",
    "src/partcad_ide_client",
    "src/partcad_service_json_rpc",
    "src/partcad_utils",
    "cad/freecad",
]

# `+++ b/path/to/file.py`, and `@@ -12,3 +14,5 @@` with either count omitted
# when it is 1. `--unified=0` is what makes the second one exact: with no
# context lines a hunk's `+` range is precisely the lines the diff adds.
DIFF_FILE_RE = re.compile(r"^\+\+\+ (?:b/)?(.*)$")
DIFF_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def run(command, **kwargs):
    """Run a command, echo it, and hand back the completed process."""
    print("+ " + " ".join(str(part) for part in command), flush=True)
    return subprocess.run(command, **kwargs)


def coverage(subcommand, *arguments, rcfile, data_file, check=True):
    """Run one coverage.py subcommand against the merged data file.

    Through `sys.executable -m` rather than the `coverage` script: the "Coverage"
    job installs coverage.py into whatever interpreter `setup-python` selected,
    and that is the one interpreter certain to have it.

    The two options go in front of everything else because `coverage combine`
    reads its positional arguments as paths and does not stop doing so when one
    of them starts with a dash: with the options last it announces "Couldn't
    combine from non-existent path '--rcfile=...'" and exits 1.
    """
    command = [sys.executable, "-m", "coverage", subcommand, f"--rcfile={rcfile}", f"--data-file={data_file}"]
    return run([*command, *arguments], check=check)


def find_data_files(data_dir):
    """Every coverage.py data file under `data_dir`, in a stable order.

    `actions/download-artifact` unpacks each artifact into a directory of its
    own, so what arrives is a tree of identically named `.coverage` files. The
    name is the only thing they have in common -- a job writes `.coverage`,
    `coverage combine` in a job writes `.coverage` too -- so this matches the
    prefix rather than the whole name.
    """
    if not data_dir.is_dir():
        return []
    found = [path for path in sorted(data_dir.rglob(".coverage*")) if path.is_file()]
    # A `.coverage` is SQLite, and coverage.py leaves `-journal`/`-wal` files
    # beside it if a process died mid-write. Handing one to `combine` is an
    # error, and it carries nothing the data file does not.
    return [path for path in found if not path.name.endswith(("-journal", "-wal", "-shm"))]


def omit_patterns(rcfile):
    """The `[run] omit` list, read from the same file the jobs measured with.

    Read rather than repeated: a second copy of those patterns here would be a
    second answer to "what is not PartCAD's code", and the two would drift the
    day somebody adds a third.
    """
    parser = configparser.ConfigParser()
    parser.read(rcfile)
    raw = parser.get("run", "omit", fallback="")
    return [line.strip() for line in raw.splitlines() if line.strip()]


def in_scope_files(root, rcfile):
    """Every file the report should have an opinion about, measured or not.

    `PACKAGES` is the scope, and it is the same scope `[run] include` in
    `coverage.rc` traces -- the test above this module's `PACKAGES` list keeps
    the two honest. `fnmatch` is a shade more permissive than coverage.py's own
    globbing (its `*` crosses a directory separator), which for the two patterns
    in that `omit` list only means they exclude what they were written to
    exclude.
    """
    patterns = omit_patterns(rcfile)
    for package in PACKAGES:
        base = root / package
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            relative = path.relative_to(root).as_posix()
            if any(fnmatch.fnmatch("/" + relative, pattern) for pattern in patterns):
                continue
            yield path


def touch_unmeasured(merged, root, rcfile):
    """Put the in-scope files nothing imported into the data, at nought percent.

    coverage.py reports the files it *saw*: `[run] include` filters what gets
    traced, and a module no test ever imports is therefore absent from the
    merged data altogether -- not zero, absent. That is a hole under the gate
    rather than a cosmetic gap, and it is the shape of hole that swallows
    exactly the change worth catching: add a new module with no test at all and
    every statement in it is missing from `coverage.json`, so `patch_summary`
    finds nothing to count, `evaluate` reports "nothing to measure", and the
    requirement passes a pull request whose new code has never been executed.

    `CoverageData.touch_files` is coverage.py's own answer to this: it records
    the file as measured with no lines executed, so every report from here on
    counts its statements as missing. The project rate drops when this first
    runs, and that is the point -- it was never that high.

    Returns how many files were added, for the log.
    """
    data = CoverageData(str(merged))
    data.read()
    measured = set(data.measured_files())
    absent = [str(path) for path in in_scope_files(root, rcfile) if str(path) not in measured]
    if absent:
        data.touch_files(absent)
        data.write()
    return len(absent)


def added_lines(base, head):
    """The line numbers each file gained between `base` and `head`.

    Returns a `{path: {line, ...}}` mapping, or `None` when git cannot answer --
    a shallow checkout that does not contain `base` is the usual reason, and a
    patch-coverage figure computed from half a diff would be worse than none.
    """
    completed = run(
        # `core.quotepath=false` so a non-ASCII path arrives as itself rather
        # than as octal escapes; `--diff-filter=d` drops deletions, which have no
        # added lines and whose `+++` is `/dev/null`; `--no-renames` so a moved
        # file is an add plus a delete rather than a rename whose body never
        # appears -- moved code that nothing covers should still count.
        [
            "git",
            "-c",
            "core.quotepath=false",
            "diff",
            "--unified=0",
            "--no-color",
            "--no-renames",
            "--diff-filter=d",
            base,
            head,
            "--",
            "*.py",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        print(f"::warning title=Coverage::could not diff {base}..{head}: {completed.stderr.strip()}")
        return None

    lines_by_file = {}
    current = None
    for line in completed.stdout.splitlines():
        file_match = DIFF_FILE_RE.match(line)
        if file_match:
            path = file_match.group(1)
            current = None if path == "/dev/null" else path
            continue
        hunk_match = DIFF_HUNK_RE.match(line)
        if hunk_match and current is not None:
            start = int(hunk_match.group(1))
            count = 1 if hunk_match.group(2) is None else int(hunk_match.group(2))
            if count:
                lines_by_file.setdefault(current, set()).update(range(start, start + count))
    return lines_by_file


def patch_summary(report, lines_by_file):
    """How much of what this pull request touched is covered.

    Only statements coverage.py measured count. A line the diff adds that is not
    a statement -- a blank line, a comment, a file the `include` list in
    `coverage.rc` does not name, a test -- appears in neither `executed_lines`
    nor `missing_lines` and so is in neither half of the fraction. That is the
    point: the figure answers "is the new code tested", not "did you write
    comments".
    """
    covered, missing, files = 0, 0, {}
    for path, changed in sorted(lines_by_file.items()):
        measured = report["files"].get(path)
        if measured is None:
            continue
        file_covered = sorted(changed.intersection(measured["executed_lines"]))
        file_missing = sorted(changed.intersection(measured["missing_lines"]))
        if not file_covered and not file_missing:
            continue
        covered += len(file_covered)
        missing += len(file_missing)
        files[path] = {
            "covered": len(file_covered),
            "missing": len(file_missing),
            "missing_lines": file_missing,
        }
    total = covered + missing
    return {
        "statements": total,
        "covered": covered,
        "missing": missing,
        "rate": percentage(covered, total),
        "files": files,
    }


def percentage(covered, total):
    """A rate in percent, or `None` when there is nothing to take a rate of."""
    return None if not total else 100.0 * covered / total


def package_of(path):
    """Which entry of `PACKAGES` a file belongs to, or `None`."""
    for package in PACKAGES:
        if path == package or path.startswith(package + "/"):
            return package
    return None


def package_summaries(report):
    """Per-package statement totals, in the order `PACKAGES` lists them."""
    totals = {package: {"covered": 0, "statements": 0} for package in PACKAGES}
    other = {"covered": 0, "statements": 0}
    for path, measured in report["files"].items():
        bucket = totals.get(package_of(path), other)
        bucket["covered"] += measured["summary"]["covered_lines"]
        bucket["statements"] += measured["summary"]["num_statements"]

    summaries = []
    for name, bucket in list(totals.items()) + [("(elsewhere)", other)]:
        if bucket["statements"]:
            summaries.append({"name": name, **bucket, "rate": percentage(bucket["covered"], bucket["statements"])})
    return summaries


def normalised(report):
    """The JSON report with every file named the way the rest of this script is.

    coverage.py names files with the platform's separator, so on Windows the keys
    arrive as `src\\partcad\\shape.py`. Everything that reads them afterwards
    matches against forward slashes -- `git diff` emits those on every platform,
    and `PACKAGES` is written with them -- so a backslash key matches neither:
    patch coverage comes out empty and every file lands in `(elsewhere)`. Neither
    says anything; they are just quietly zero.

    The "Coverage" job runs on Linux, where this is a no-op. It is the developer
    reproducing the merge locally on Windows -- which
    `docs/source/contributing.rst` invites -- who would otherwise be handed a
    patch figure of nothing at all.
    """
    report["files"] = {path.replace("\\", "/"): data for path, data in report["files"].items()}
    return report


def merge(args):
    """Combine every data file the run produced and write the reports."""
    report_dir, work_dir = Path(args.report_dir), Path(args.work_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    data_files = find_data_files(Path(args.data_dir))
    print(f"Found {len(data_files)} coverage data file(s) under {args.data_dir}")

    summary = {"data_files": len(data_files), "sources": [str(path) for path in data_files]}
    if not data_files:
        # Not a failure. A documentation-only pull request runs no job that
        # measures anything, and a run whose test jobs all failed early has
        # nothing to report either -- in both cases the tests' own verdict is
        # the one that matters, and a red "Coverage" job on top of it would
        # only point away from it.
        print("::notice title=Coverage::this run produced no coverage data; nothing to merge")
        write_summary(report_dir / "summary.json", summary)
        return 0

    merged = work_dir / "merged.coverage"
    merged.unlink(missing_ok=True)
    # Every file by name, rather than the directory they are in. Handed a
    # directory, `coverage combine` globs it for `<basename of --data-file>.*` --
    # so with the merged file called anything other than `.coverage` it would
    # find nothing and say "No data to combine", and with it called `.coverage`
    # it would still skip a file named exactly `.coverage`, which is what every
    # artifact holds. `--keep` leaves the downloaded files alone: combine deletes
    # what it read otherwise, and they are what a debug run wants to re-read.
    coverage("combine", "--keep", *[str(path) for path in data_files], rcfile=args.rcfile, data_file=merged)

    # Before any report is written, because every one of them reads this data.
    touched = touch_unmeasured(merged, Path.cwd(), args.rcfile)
    print(f"Added {touched} in-scope file(s) that no job imported, at nought percent")
    summary["untouched_files"] = touched

    coverage("html", "-d", str(report_dir / "htmlcov"), "--title", args.title, rcfile=args.rcfile, data_file=merged)
    coverage("xml", "-o", str(report_dir / "coverage.xml"), rcfile=args.rcfile, data_file=merged)
    # Out of the uploaded directory: the JSON report carries a per-function and
    # per-class breakdown of every file, which is tens of megabytes here and
    # which nothing downstream reads. What is uploaded is the HTML, the
    # Cobertura XML and the summary below.
    json_report = work_dir / "coverage.json"
    coverage("json", "-o", str(json_report), rcfile=args.rcfile, data_file=merged)
    # The text report, last, because its output in the log is what somebody
    # debugging a surprising rate reads first.
    coverage("report", "--skip-covered", "--skip-empty", rcfile=args.rcfile, data_file=merged, check=False)

    report = normalised(json.loads(json_report.read_text(encoding="utf-8")))
    totals = report["totals"]
    summary["totals"] = {
        "statements": totals["num_statements"],
        "covered_statements": totals["covered_lines"],
        "missing_statements": totals["missing_lines"],
        "statement_rate": totals.get("percent_statements_covered", totals["percent_covered"]),
        "branches": totals.get("num_branches", 0),
        "covered_branches": totals.get("covered_branches", 0),
        "partial_branches": totals.get("num_partial_branches", 0),
        "rate": totals["percent_covered"],
    }
    summary["packages"] = package_summaries(report)

    if args.diff_base:
        lines_by_file = added_lines(args.diff_base, args.diff_head)
        summary["patch"] = None if lines_by_file is None else patch_summary(report, lines_by_file)
    else:
        summary["patch"] = None

    write_summary(report_dir / "summary.json", summary)
    return 0


def write_summary(path, summary):
    """The one file `render` and `check` read, so that neither re-derives a rate."""
    path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {path}")


def rate(value):
    """A percentage for a human, or "n/a" where there was nothing to take one of."""
    return "n/a" if value is None else f"{value:.2f}%"


def render(args):
    """Write the markdown that goes into the job summary and the PR comment."""
    summary = json.loads(Path(args.summary).read_text(encoding="utf-8"))
    body = [COMMENT_MARKER, "## Coverage", ""]

    if not summary["data_files"]:
        body += ["This run produced no coverage data, so there is nothing to report.", ""]
    else:
        totals, patch = summary["totals"], summary["patch"]
        body += [
            "| Scope | Statements | Missed | Rate |",
            "| --- | ---: | ---: | ---: |",
            "| Project (statements) | {} | {} | {} |".format(
                totals["statements"], totals["missing_statements"], rate(totals["statement_rate"])
            ),
        ]
        if totals["branches"]:
            body.append(
                "| Project (branches) | {} | {} | {} |".format(
                    totals["branches"],
                    totals["branches"] - totals["covered_branches"],
                    rate(percentage(totals["covered_branches"], totals["branches"])),
                )
            )
        body.append(f"| **Project (overall)** | | | **{rate(totals['rate'])}** |")
        if patch and patch["statements"]:
            body.append(
                "| **This pull request** | {} | {} | **{}** |".format(
                    patch["statements"], patch["missing"], rate(patch["rate"])
                )
            )
        body.append("")
        body.append(
            "Merged from {} coverage data file(s) produced by this run. "
            "The overall rate counts branches as well as statements; "
            "the requirement below is stated in statements at both ends, "
            "because a diff cannot say which arcs of a branch are new.".format(summary["data_files"])
        )
        body.append("")

        body += verdict_lines(summary, args)
        body += package_lines(summary)
        body += uncovered_lines(summary)

    if args.html_url:
        body += [
            "",
            f"📊 [Download the full HTML report]({args.html_url}) "
            "(artifact `coverage-html-report`; unpack it and open `htmlcov/index.html`).",
        ]
    if args.run_url:
        body += ["", f"<sub>Produced by [this CI run]({args.run_url}).</sub>"]

    text = "\n".join(body) + "\n"
    # The job summary gets written whatever happened; the comment body only when
    # there is something in it worth replacing the last one with. A run that
    # measured nothing -- every suite cancelled, most often, because somebody
    # pushed again while this one was in flight -- would otherwise edit a real
    # coverage report on the pull request into "this run produced no coverage
    # data", which is worse than saying nothing at all.
    if args.out and summary["data_files"]:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"Wrote {args.out}")
    elif args.out:
        print(f"No coverage data, so {args.out} is not written and the comment is left as it is")
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as handle:
            handle.write(text)
    else:
        print(text)
    return 0


def verdict_lines(summary, args):
    """The one line that says whether the requirement is met, and by how much."""
    met, floor, patch, reason = evaluate(summary, args)
    if met is None:
        return [f"ℹ️ {reason}", ""]
    mark = "✅" if met else "❌"
    return [
        f"{mark} Patch coverage {rate(patch['rate'])} against a required {rate(floor)} "
        f"({patch['covered']} of {patch['statements']} changed statements covered).",
        "",
    ]


def package_lines(summary):
    """The per-package breakdown, folded away: it is reference, not the headline."""
    rows = [
        "<details><summary>Per package</summary>",
        "",
        "| Package | Statements | Missed | Rate |",
        "| --- | ---: | ---: | ---: |",
    ]
    for package in summary.get("packages", []):
        rows.append(
            "| `{}` | {} | {} | {} |".format(
                package["name"],
                package["statements"],
                package["statements"] - package["covered"],
                rate(package["rate"]),
            )
        )
    rows += ["", "</details>", ""]
    return rows


def uncovered_lines(summary, limit=20):
    """The files this pull request left uncovered, which is the actionable half."""
    patch = summary.get("patch")
    if not patch or not patch["missing"]:
        return []
    rows = ["<details><summary>Changed statements with no coverage</summary>", "", "| File | Lines |", "| --- | --- |"]
    uncovered = sorted(
        ((path, data) for path, data in patch["files"].items() if data["missing"]),
        key=lambda item: -item[1]["missing"],
    )
    for path, data in uncovered[:limit]:
        rows.append(f"| `{path}` | {compress(data['missing_lines'])} |")
    if len(uncovered) > limit:
        rows.append(f"| … and {len(uncovered) - limit} more file(s) | |")
    rows += ["", "</details>", ""]
    return rows


def compress(numbers):
    """`[1, 2, 3, 7]` as `1-3, 7`, the way coverage.py's own reports read."""
    ranges, start, previous = [], None, None
    for number in numbers:
        if start is None:
            start = previous = number
        elif number == previous + 1:
            previous = number
        else:
            ranges.append((start, previous))
            start = previous = number
    if start is not None:
        ranges.append((start, previous))
    return ", ".join(str(low) if low == high else f"{low}-{high}" for low, high in ranges)


def evaluate(summary, args):
    """Decide the requirement. Returns `(met, floor, patch, reason)`.

    `met` is `None` when there is nothing to decide, which is not the same as a
    pass: a pull request that changes no measured statement has no patch to hold
    to a floor, and saying so is more use than a green tick.
    """
    if not summary["data_files"]:
        return None, None, None, "No coverage data in this run, so there is nothing to require."
    patch = summary.get("patch")
    if patch is None:
        return None, None, None, "No diff to measure patch coverage against."
    if not patch["statements"]:
        return None, None, None, "This change touches no statement that coverage measures."

    totals = summary["totals"]
    if args.min_patch == "project":
        floor = totals["statement_rate"]
    else:
        floor = float(args.min_patch)
    floor = max(0.0, floor - args.patch_tolerance)
    return patch["rate"] >= floor, floor, patch, ""


def check(args):
    """Apply the requirement, and be the step that goes red when it is not met."""
    summary = json.loads(Path(args.summary).read_text(encoding="utf-8"))
    met, floor, patch, reason = evaluate(summary, args)
    if met is None:
        print(f"::notice title=Coverage::{reason}")
        return 0
    if met:
        print(f"::notice title=Coverage::patch coverage {rate(patch['rate'])} meets the required {rate(floor)}")
        return 0
    print(
        f"::error title=Coverage::patch coverage {rate(patch['rate'])} is below the required {rate(floor)} -- "
        f"{patch['missing']} of {patch['statements']} statements this change touched are not covered by any test. "
        "The pull request comment lists them."
    )
    return 1


def main(argv=None):
    """The three subcommands, which are the "Coverage" job's three steps."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    merge_parser = sub.add_parser("merge", help="combine every job's data and write the reports")
    merge_parser.add_argument(
        "--data-dir", default="coverage-data", help="where the downloaded artifacts were unpacked"
    )
    merge_parser.add_argument("--report-dir", default="coverage-report", help="where the uploaded report is written")
    merge_parser.add_argument("--work-dir", default="coverage-work", help="scratch space, not uploaded")
    merge_parser.add_argument("--rcfile", default="dev-tools/coverage.rc", help="coverage.py configuration")
    merge_parser.add_argument("--title", default="PartCAD coverage", help="title of the HTML report")
    merge_parser.add_argument("--diff-base", default="", help="git ref the pull request is measured against")
    merge_parser.add_argument("--diff-head", default="HEAD", help="git ref holding the change")
    merge_parser.set_defaults(func=merge)

    render_parser = sub.add_parser("render", help="write the markdown for the job summary and the PR comment")
    render_parser.add_argument("--summary", default="coverage-report/summary.json")
    render_parser.add_argument("--out", default="", help="file to write the comment body to")
    render_parser.add_argument("--html-url", default="", help="URL of the uploaded HTML report artifact")
    render_parser.add_argument("--run-url", default="", help="URL of the CI run")
    add_requirement_arguments(render_parser)
    render_parser.set_defaults(func=render)

    check_parser = sub.add_parser("check", help="apply the coverage requirement")
    check_parser.add_argument("--summary", default="coverage-report/summary.json")
    add_requirement_arguments(check_parser)
    check_parser.set_defaults(func=check)

    args = parser.parse_args(argv)
    return args.func(args)


def add_requirement_arguments(parser):
    """The requirement, spelled the same way for `render` and for `check`.

    Both need it -- one to state it, the other to enforce it -- and two spellings
    of one policy is how a comment comes to promise what the gate does not do.
    """
    parser.add_argument(
        "--min-patch",
        default="project",
        help="floor under patch coverage: a percentage, or 'project' for the project's own statement rate",
    )
    parser.add_argument(
        "--patch-tolerance",
        type=float,
        default=0.0,
        help="percentage points of slack allowed below the floor",
    )


if __name__ == "__main__":
    sys.exit(main())
