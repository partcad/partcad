#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The merged coverage report, and the three things about it that fail silently.

`dev-tools/ci/coverage_report.py` replaced Codecov: the "Coverage" job in
`test.yml` merges every job's raw `.coverage` data, publishes the HTML report as
an artifact, edits one comment on the pull request and holds patch coverage to a
floor. Almost all of that announces itself when it breaks -- a missing artifact,
a step that exits non-zero, a comment that does not appear.

Three parts do not, and they are what these tests are about:

  * **The `[paths]` mapping in `dev-tools/coverage.rc`.** It is what makes the
    merge a union rather than a pile: the same file is recorded under three
    roots (the checkout, `site-packages`, and either of those with Windows
    separators), and without the mapping `coverage combine` keeps all three as
    separate files. The report is then produced, uploaded and commented on, and
    every rate in it is wrong -- lower than the truth, by however much the
    suites overlap. Nothing errors.

  * **The requirement.** It is a floor under the statements the pull request
    touched, set to the project's own statement rate in the same run. Get the
    arithmetic or the "nothing to measure" cases wrong and the gate passes
    everything, which looks exactly like a repository whose patches are all well
    covered.

  * **The contract between a test job and the merge**, which is a string: a job
    uploads its data as `coverage-data-<name>` and the merge downloads
    `coverage-data-*`. A job that stops matching that prefix drops out of the
    merged report and the report still renders.
"""

import importlib.util
import io
import json
import os
import pathlib
import shutil
import subprocess
import types
import urllib.error

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "dev-tools" / "ci" / "coverage_report.py"
COMMENT_SCRIPT = REPO_ROOT / "dev-tools" / "ci" / "pr_comment.py"
COVERAGE_RC = REPO_ROOT / "dev-tools" / "coverage.rc"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
UPLOAD_ACTION = REPO_ROOT / ".github" / "actions" / "upload-test-results" / "action.yml"


def load(path, name):
    """A module out of a file whose directory is not importable."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def report_module():
    """The script under test, imported once for the whole file."""
    return load(SCRIPT, "partcad_coverage_report")


def options(**overrides):
    """The requirement's arguments, as `argparse` would hand them over."""
    values = {"min_patch": "project", "patch_tolerance": 0.0}
    values.update(overrides)
    return types.SimpleNamespace(**values)


def summary(project_rate, patch_rate, statements=100):
    """A merged summary with the two rates the requirement compares."""
    covered = round(statements * patch_rate / 100.0)
    return {
        "data_files": 3,
        "totals": {
            "statements": 1000,
            "covered_statements": int(10 * project_rate),
            "missing_statements": 1000 - int(10 * project_rate),
            "statement_rate": project_rate,
            "branches": 0,
            "covered_branches": 0,
            "partial_branches": 0,
            "rate": project_rate,
        },
        "packages": [],
        "patch": {
            "statements": statements,
            "covered": covered,
            "missing": statements - covered,
            "rate": patch_rate,
            "files": {},
        },
    }


# --- The `[paths]` mapping ------------------------------------------------


def test_one_file_recorded_three_ways_merges_into_one(report_module, tmp_path):
    """The whole point of the merge, and the part that fails without erroring.

    Three data files, holding the same two source files under the three roots CI
    actually records them under, with the covered lines split between them. What
    must come out is one entry per source file, covering the union -- not three
    entries each covering a third.
    """
    coverage_data = pytest.importorskip("coverage.sqldata").CoverageData

    relative = "src/partcad_utils/user_config.py"
    source = REPO_ROOT / relative
    assert source.is_file()
    # Real statement line numbers: a recorded line that is a comment or a blank
    # is not in the file's statement set, so coverage.py drops it from the
    # report and the assertion below would be about nothing.
    parser = pytest.importorskip("coverage.parser").PythonParser(filename=str(source))
    parser.parse_source()
    first, second, third, fourth = sorted(parser.statements)[:4]

    data_dir = tmp_path / "coverage-data"
    for index, (root, lines) in enumerate(
        [
            (f"/home/runner/work/partcad/partcad/{relative}", [first, second]),
            (f"/opt/hostedtoolcache/lib/python3.11/site-packages/{relative[len('src/'):]}", [third]),
            (r"D:\a\partcad\partcad" + "\\" + relative.replace("/", "\\"), [second, fourth]),
        ]
    ):
        artifact = data_dir / f"coverage-data-job-{index}"
        artifact.mkdir(parents=True)
        written = coverage_data(str(artifact / ".coverage"))
        written.add_lines({root: lines})
        written.write()

    args = types.SimpleNamespace(
        data_dir=str(data_dir),
        report_dir=str(tmp_path / "report"),
        work_dir=str(tmp_path / "work"),
        rcfile=str(COVERAGE_RC),
        title="test",
        diff_base="",
        diff_head="HEAD",
    )
    # From the repository root: the `[paths]` result is relative, so it is
    # resolved against the working directory, and the HTML report needs the
    # source it names to be there.
    previous = os.getcwd()
    os.chdir(REPO_ROOT)
    try:
        assert report_module.merge(args) == 0
    finally:
        os.chdir(previous)

    merged = json.loads((pathlib.Path(args.report_dir) / "summary.json").read_text())
    assert merged["data_files"] == 3

    # Through the script's own `normalised`, because coverage.py writes these
    # keys with the platform's separator: on Windows the file on disk says
    # `src\\partcad_utils\\user_config.py`. That is what the merge normalises,
    # and asserting on the raw file made this the one test that failed on
    # Windows and nowhere else.
    report = report_module.normalised(json.loads((pathlib.Path(args.work_dir) / "coverage.json").read_text()))
    # One entry, under the checkout-relative name, covering every line the three
    # recordings mention between them.
    assert [name for name in report["files"] if "user_config" in name] == [relative]
    # The union of the three recordings, and not one third of it.
    assert set(report["files"][relative]["executed_lines"]) == {first, second, third, fourth}


def test_the_merged_report_names_files_with_forward_slashes(report_module, tmp_path, monkeypatch):
    """Whatever the platform, because everything downstream matches on `/`.

    coverage.py names files with the platform's separator, so on Windows the
    merged report's keys are `src\\partcad\\shape.py`. `git diff` emits forward
    slashes everywhere and `PACKAGES` is written with them, so a backslash key
    matches neither: patch coverage comes out empty and every file lands in
    `(elsewhere)`, both without a word. Windows is exactly where a separator
    written on Linux goes wrong, which is why this is pinned rather than left to
    the `Coverage` job happening to run on Linux.
    """
    windows = {
        "totals": {},
        "files": {r"src\partcad\shape.py": {"summary": {"covered_lines": 1, "num_statements": 1}}},
    }
    assert list(report_module.normalised(windows)["files"]) == ["src/partcad/shape.py"]
    # And the consumers then find it, which is the whole point.
    assert report_module.package_of("src/partcad/shape.py") == "src/partcad"
    assert report_module.package_of(r"src\partcad\shape.py") is None


def test_the_paths_section_covers_every_package_the_include_list_names(report_module):
    """`include` and `[paths]` have to agree, or a package is measured and lost.

    `include` decides what is traced; `[paths]` decides whether two recordings of
    it are the same file. A package in the first and not the second is traced on
    every runner and then reported once per runner.
    """
    text = COVERAGE_RC.read_text()
    assert "[paths]" in text
    for spelling in ["*/src/", "*/site-packages/", "*/cad/freecad/"]:
        assert spelling in text, spelling


def test_the_packages_the_report_groups_by_are_the_packages_that_exist(report_module):
    """The per-package table names every package the wheel ships, and no other.

    Same reason `coverage.rc` writes its `include` list out by hand: a package
    missing from the list is not an error, it is a row that quietly stops
    appearing -- its files land in `(elsewhere)` and nobody reads that row.
    """
    # A *package*, not a directory. An editable install puts `src/partcad.egg-info`
    # beside the six, and `__pycache__` appears the moment anything imports them
    # -- neither is code coverage has an opinion about. Written as `is_dir()` at
    # first, which passed on a clean checkout and failed on every CI runner,
    # because CI is where something has run `pip install -e .`.
    on_disk = {f"src/{path.name}" for path in (REPO_ROOT / "src").iterdir() if (path / "__init__.py").is_file()}
    listed = {package for package in report_module.PACKAGES if package.startswith("src/")}
    assert listed == on_disk
    assert "cad/freecad" in report_module.PACKAGES


def test_a_file_no_job_imported_is_nought_percent_rather_than_absent(report_module, tmp_path):
    """The hole this gate would otherwise have exactly the wrong shape of.

    coverage.py reports the files it saw. `[run] include` filters tracing; it
    does not discover. So a module no test imports is *absent* from the merged
    data rather than zero in it -- and absent means `patch_summary` counts none
    of its statements, `evaluate` says "nothing to measure", and a pull request
    whose new module has never been executed passes the requirement.
    """
    coverage_data = pytest.importorskip("coverage.sqldata").CoverageData

    root = tmp_path / "repo"
    (root / "src" / "partcad").mkdir(parents=True)
    (root / "src" / "partcad" / "seen.py").write_text("a = 1\n")
    (root / "src" / "partcad" / "never_imported.py").write_text("def f():\n    return 1\n")
    # Under an `omit` pattern, so it must stay out however new it is.
    (root / "src" / "partcad" / "sandbox").mkdir()
    (root / "src" / "partcad" / "sandbox" / "inner.py").write_text("b = 2\n")

    merged = tmp_path / "merged.coverage"
    written = coverage_data(str(merged))
    written.add_lines({str(root / "src" / "partcad" / "seen.py"): [1]})
    written.write()

    added_count = report_module.touch_unmeasured(merged, root, str(COVERAGE_RC))
    assert added_count == 1

    data = coverage_data(str(merged))
    data.read()
    measured = {pathlib.Path(name).name for name in data.measured_files()}
    assert measured == {"seen.py", "never_imported.py"}


def test_the_omit_list_is_read_from_the_config_rather_than_repeated(report_module):
    """Two copies of "what is not PartCAD's code" would drift on the third entry."""
    patterns = report_module.omit_patterns(str(COVERAGE_RC))
    assert patterns
    assert all(pattern.startswith("*") for pattern in patterns)


def test_every_producer_measures_with_the_same_config(report_module):
    """One config file, or `coverage combine` refuses the merge outright.

    `coverage.rc` sets `branch = True`, and coverage.py will not combine branch
    data with statement-only data -- it exits 1 with "Can't combine statement
    coverage data with branch data". The suites driving `coverage run` pass that
    file explicitly. The pytest job measures through pytest-cov, which finds no
    configuration on its own here (there is no `.coveragerc` and no
    `[tool.coverage]` table) and would default to `branch = False`.

    That is not a degraded report, it is no report: the first time the
    "Coverage" job ran with data from every suite at once, the merge died on
    exactly this. So `addopts` names the same file, and this is what keeps it
    named.
    """
    rcfile = "dev-tools/coverage.rc"
    assert "branch = True" in COVERAGE_RC.read_text()

    pyproject = (REPO_ROOT / "pyproject.toml").read_text()
    assert f"--cov-config={rcfile}" in pyproject, "pytest-cov must measure with the same config as `coverage run`"

    # And the workflows hand `coverage run` that same file rather than a copy.
    workflow_text = (WORKFLOWS / "test.yml").read_text()
    assert f"--rcfile=./{rcfile}" in workflow_text or f"--rcfile=../{rcfile}" in workflow_text


# --- Patch coverage -------------------------------------------------------


def test_patch_coverage_counts_only_statements_coverage_measured(report_module):
    """A diff is lines; coverage is statements. Only the overlap is the fraction.

    A blank line, a comment or a file nothing traces is in neither
    `executed_lines` nor `missing_lines`, and counting it either way would make
    the figure a property of how somebody formats code.
    """
    report = {
        "files": {
            "src/partcad/thing.py": {"executed_lines": [10, 11], "missing_lines": [12]},
            "tests/test_thing.py": {"executed_lines": [1], "missing_lines": []},
        }
    }
    patch = report_module.patch_summary(
        report,
        {
            # 13 and 14 are a comment and a blank line: in the diff, in neither list.
            "src/partcad/thing.py": {10, 12, 13, 14},
            # Not measured at all -- the `include` list does not name it.
            "docs/source/conf.py": {1, 2, 3},
        },
    )
    assert patch == {
        "statements": 2,
        "covered": 1,
        "missing": 1,
        "rate": 50.0,
        "files": {"src/partcad/thing.py": {"covered": 1, "missing": 1, "missing_lines": [12]}},
    }


def test_a_change_that_touches_no_measured_statement_has_no_patch(report_module):
    """A README-only change has no denominator, and `None` is not zero."""
    report = {"files": {"src/partcad/thing.py": {"executed_lines": [1], "missing_lines": []}}}
    patch = report_module.patch_summary(report, {"README.md": {1, 2}})
    assert patch["statements"] == 0
    assert patch["rate"] is None


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_added_lines_reads_the_lines_a_commit_added(report_module, tmp_path):
    """The diff parser, against a real `git diff` rather than a fixture of one.

    `--unified=0` is what makes a hunk's `+` range exactly the added lines, and a
    fixture would go on passing if that flag were dropped.
    """

    def git(*arguments):
        """One git command in the throwaway repository, failing loudly."""
        subprocess.run(["git", *arguments], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "ci@partcad.org")
    git("config", "user.name", "CI")
    (tmp_path / "module.py").write_text("a = 1\nb = 2\nc = 3\n")
    git("add", "module.py")
    git("commit", "-qm", "first")
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()
    # One line changed in place, two appended, and a non-Python file that must
    # not appear at all.
    (tmp_path / "module.py").write_text("a = 1\nb = 22\nc = 3\nd = 4\ne = 5\n")
    (tmp_path / "notes.md").write_text("hello\n")
    git("add", "module.py", "notes.md")
    git("commit", "-qm", "second")

    previous = os.getcwd()
    os.chdir(tmp_path)
    try:
        added = report_module.added_lines(base, "HEAD")
    finally:
        os.chdir(previous)
    assert added == {"module.py": {2, 4, 5}}


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_a_diff_git_cannot_take_is_no_patch_rather_than_an_empty_one(report_module, tmp_path):
    """A shallow checkout that does not hold the base is the case this is for.

    Reporting "0 lines changed, 100% covered" there would pass the requirement on
    every pull request, for as long as nobody noticed the figure was missing.
    """
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
    previous = os.getcwd()
    os.chdir(tmp_path)
    try:
        assert report_module.added_lines("0" * 40, "HEAD") is None
    finally:
        os.chdir(previous)


# --- The requirement ------------------------------------------------------


def test_the_floor_is_the_projects_own_statement_rate(report_module):
    """The requirement itself, in both directions."""
    met, floor, _, _ = report_module.evaluate(summary(project_rate=70.0, patch_rate=80.0), options())
    assert (met, floor) == (True, 70.0)

    met, floor, _, _ = report_module.evaluate(summary(project_rate=70.0, patch_rate=60.0), options())
    assert (met, floor) == (False, 70.0)


def test_a_patch_exactly_at_the_floor_passes(report_module):
    """The boundary is inclusive: matching the project is meeting the bar."""
    met, _, _, _ = report_module.evaluate(summary(project_rate=70.0, patch_rate=70.0), options())
    assert met is True


def test_an_absolute_floor_and_a_tolerance_are_both_honoured(report_module):
    """The two knobs that exist for a policy somebody else wants."""
    met, floor, _, _ = report_module.evaluate(summary(project_rate=99.0, patch_rate=80.0), options(min_patch="75"))
    assert (met, floor) == (True, 75.0)

    met, floor, _, _ = report_module.evaluate(summary(project_rate=70.0, patch_rate=68.0), options(patch_tolerance=5.0))
    assert (met, floor) == (True, 65.0)


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda data: data.update(data_files=0), id="no-data"),
        pytest.param(lambda data: data.update(patch=None), id="no-diff"),
        pytest.param(lambda data: data["patch"].update(statements=0), id="nothing-measured"),
    ],
)
def test_nothing_to_measure_is_a_notice_and_not_a_pass(report_module, mutate):
    """Three ways there is no patch, none of which may be reported as green.

    `evaluate` returns `None` rather than `True` for each, so the comment says
    what happened instead of showing a tick somebody would read as "covered".
    """
    data = summary(project_rate=70.0, patch_rate=10.0)
    mutate(data)
    met, _, _, reason = report_module.evaluate(data, options())
    assert met is None
    assert reason


def test_check_exits_non_zero_only_when_the_floor_is_missed(report_module, tmp_path, capsys):
    """The exit code is the gate, and the annotation is what names the blocker."""
    path = tmp_path / "summary.json"
    path.write_text(json.dumps(summary(project_rate=70.0, patch_rate=60.0)))
    assert report_module.check(types.SimpleNamespace(summary=str(path), **vars(options()))) == 1
    assert "::error" in capsys.readouterr().out

    path.write_text(json.dumps(summary(project_rate=70.0, patch_rate=90.0)))
    assert report_module.check(types.SimpleNamespace(summary=str(path), **vars(options()))) == 0


# --- The comment ----------------------------------------------------------


def test_the_rendered_comment_carries_the_marker_and_the_report_link(report_module, tmp_path, monkeypatch):
    """Without the marker every push adds a comment instead of editing one."""
    summary_path = tmp_path / "summary.json"
    summary_path.write_text(json.dumps(summary(project_rate=70.0, patch_rate=90.0)))
    out = tmp_path / "comment.md"
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    report_module.render(
        types.SimpleNamespace(
            summary=str(summary_path),
            out=str(out),
            html_url="https://example.invalid/artifact",
            run_url="https://example.invalid/run",
            **vars(options()),
        )
    )
    body = out.read_text()
    assert body.startswith(report_module.COMMENT_MARKER)
    assert "https://example.invalid/artifact" in body
    assert "90.00%" in body


def test_the_marker_the_workflow_passes_is_the_one_the_script_writes(report_module):
    """Three files have to agree on one string, and two of them are not Python.

    `coverage_report.py` writes it into the body, `test.yml` passes it to
    `pr_comment.py`, and `pr_comment.py` refuses a body without it. A drift
    between the first two ends in a fresh comment per push, which reads as the
    comment working.
    """
    marker = report_module.COMMENT_MARKER
    assert marker in (WORKFLOWS / "test.yml").read_text()
    # And the script that matches on it takes it as an argument rather than
    # carrying a second copy of the literal.
    assert marker not in COMMENT_SCRIPT.read_text()


def test_compress_reads_like_coverage_pys_own_missing_lines(report_module):
    """Runs of uncovered lines read as ranges, the way coverage.py prints them."""
    assert report_module.compress([1, 2, 3, 7, 9, 10]) == "1-3, 7, 9-10"
    assert report_module.compress([]) == ""


@pytest.fixture(scope="module")
def comment_module():
    """The comment poster, imported the same way as the report script."""
    return load(COMMENT_SCRIPT, "partcad_pr_comment")


def refusing(module, code, on=("POST", "PATCH")):
    """A `request` that answers one HTTP status, but only for the given methods.

    The lookup has to succeed for the write to be the thing under test. An
    earlier version of this raised on every call, so the first refusal landed on
    the GET -- which meant the parametrisation below was asserting that a
    *lookup* failure is survivable, the very behaviour it was meant to forbid.
    """

    def refuse(method, *_args, **_kwargs):
        if method in on:
            raise urllib.error.HTTPError("https://example.invalid", code, "refused", {}, io.BytesIO(b"{}"))
        return []  # the lookup, finding no existing comment

    module.request = refuse


@pytest.mark.parametrize(
    "code, expected",
    [
        # The fork case: an authenticated token refused the write. Survivable --
        # the job summary carries the same report and the gate still gates.
        pytest.param(403, 0, id="fork-is-survivable"),
        # A credential that does not work at all. Treating this as the fork case
        # would hide a broken token on every pull request, branches included,
        # for as long as nobody wondered where the comment went.
        pytest.param(401, 1, id="bad-token-is-a-failure"),
        pytest.param(500, 1, id="server-error-is-a-failure"),
    ],
)
def test_only_a_refused_write_is_survivable(comment_module, tmp_path, monkeypatch, code, expected):
    body = tmp_path / "comment.md"
    body.write_text("<!-- partcad-coverage-report -->\nhello\n")
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    monkeypatch.setattr(comment_module, "request", None)
    refusing(comment_module, code)
    argv = ["--body-file", str(body), "--marker", "<!-- partcad-coverage-report -->", "--repo", "o/r", "--pr", "1"]
    assert comment_module.main(argv) == expected


def test_a_refused_lookup_is_not_the_fork_case(comment_module, tmp_path, monkeypatch):
    """403 on the read is something else, and must not wear the fork's exemption.

    A fork's token is refused the *write*; it reads the repository perfectly
    well. So a 403 on the lookup is a rate limit or worse, and surviving it
    would lose the comment on an ordinary pull request with nothing said.
    """
    body = tmp_path / "comment.md"
    body.write_text("<!-- partcad-coverage-report -->\nhello\n")
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    monkeypatch.setattr(comment_module, "request", None)
    refusing(comment_module, 403, on=("GET",))
    argv = ["--body-file", str(body), "--marker", "<!-- partcad-coverage-report -->", "--repo", "o/r", "--pr", "1"]
    assert comment_module.main(argv) == 1


def test_a_body_without_the_marker_is_refused(comment_module, tmp_path, monkeypatch):
    """It would post, and then the next run would post another beside it."""
    body = tmp_path / "comment.md"
    body.write_text("no marker here\n")
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    argv = ["--body-file", str(body), "--marker", "<!-- partcad-coverage-report -->", "--pr", "1"]
    assert comment_module.main(argv) == 1


# --- The contract between the jobs and the merge --------------------------


def workflow(name):
    """One workflow file, parsed. `on:` comes back as the boolean `True` -- YAML 1.1
    reads the bare word as one, as it does in `test_ci_version_gate.py`.
    """
    loaded = yaml.safe_load((WORKFLOWS / name).read_text())
    loaded["on"] = loaded.pop(True, loaded.get("on"))
    return loaded


def test_nothing_reaches_for_codecov_any_more():
    """The service is gone. A leftover step would upload to nowhere, silently.

    The word itself is allowed -- the "Coverage" job's own comment says what it
    replaced, which is how somebody looking for the service finds out. What must
    not come back is a step that calls the action or reads the secret: the
    `CODECOV_TOKEN` no longer exists, and `codecov-action` treats an empty token
    on a public repository as "upload anonymously and hope", so a resurrected
    step would look like it was working.
    """
    for path in sorted(WORKFLOWS.glob("*.yml")) + sorted(REPO_ROOT.glob(".github/actions/*/action.yml")):
        text = path.read_text()
        offenders = [line.strip() for line in text.splitlines() if "codecov/" in line or "CODECOV_TOKEN" in line]
        assert not offenders, f"{path}: {offenders}"


def test_every_job_that_measures_coverage_hands_its_data_to_the_merge():
    """A job that stops uploading data drops out of the report without a word."""
    text = (WORKFLOWS / "test.yml").read_text()
    jobs = workflow("test.yml")["jobs"]
    measuring = []
    for name, job in jobs.items():
        for step in job.get("steps", []):
            if "coverage run" in str(step.get("run", "")) or "--cov" in str(step.get("run", "")):
                measuring.append(name)
                break
    # The five suites the "Coverage" job's `needs:` names.
    assert set(measuring) >= {"test-behave", "test-examples-partcad", "test-examples-all", "test-pub-repo"}

    for name in set(measuring) | {"test-pytest"}:
        uploads = [
            step
            for step in jobs[name]["steps"]
            if str(step.get("uses", "")).endswith("upload-test-results") and step.get("with", {}).get("coverage-data")
        ]
        assert uploads, f"{name} measures coverage and never uploads it"
    # And the prefix both ends agree on, which is the whole contract.
    assert "coverage-data-${{ inputs.name }}" in UPLOAD_ACTION.read_text()
    assert "pattern: coverage-data-*" in text


def test_every_producer_uploads_its_coverage_even_when_its_suite_failed():
    """A failed suite still measured what it ran, and that data is only additive.

    Two halves, and the first is useless without the second. `if: always()` is
    what gets the step to run at all; the glob is what it finds when it does --
    a job that died mid-suite never reached its own `coverage combine`, so what
    is on disk is the parallel-mode parts and no combined `.coverage`. Uploading
    a bare filename there uploads nothing, and the merge silently loses a whole
    job -- which moves the requirement's floor, not just the number on it.
    """
    jobs = workflow("test.yml")["jobs"]
    producers = 0
    for name, job in jobs.items():
        for step in job.get("steps", []):
            data = step.get("with", {}).get("coverage-data") if step.get("with") else None
            if not str(step.get("uses", "")).endswith("upload-test-results") or not data:
                continue
            producers += 1
            assert "always()" in str(step.get("if")), f"{name} skips its upload when the suite fails"
            assert data.endswith(".coverage*"), f"{name} uploads a filename rather than a glob: {data}"
    assert producers == 5


def test_the_coverage_job_runs_after_every_suite_and_survives_their_failure():
    """It has to be `always()`: a red run is when the report is worth reading."""
    job = workflow("test.yml")["jobs"]["coverage"]
    assert set(job["needs"]) == {
        "set-matrix",
        "test-pytest",
        "test-behave",
        "test-examples-partcad",
        "test-examples-all",
        "test-pub-repo",
    }
    # "!cancelled()", not "always()": see the note on the job. "always()" runs it
    # on a *cancelled* run too -- which is what a second push does to the first
    # push's run -- where it finds no data and would edit a real report on the
    # pull request into "nothing to report".
    assert "!cancelled()" in job["if"]
    assert "always()" not in job["if"]
    assert job["permissions"]["pull-requests"] == "write"
    # The full history, or patch coverage has nothing to measure against.
    checkout = next(step for step in job["steps"] if str(step.get("uses", "")).startswith("actions/checkout"))
    assert checkout["with"]["fetch-depth"] == 0


def test_the_comment_and_the_gate_state_the_same_requirement():
    """Two literals is how a comment comes to promise a bar nothing enforces.

    The rendered comment says what patch coverage had to reach and the gate
    decides whether it did. They read one job-level value, so the two cannot
    drift into disagreeing about the policy in public.
    """
    job = workflow("test.yml")["jobs"]["coverage"]
    assert job["env"]["COVERAGE_MIN_PATCH"]
    using = [step for step in job["steps"] if "--min-patch" in str(step.get("run", ""))]
    assert len(using) == 2
    for step in using:
        assert '--min-patch "${COVERAGE_MIN_PATCH}"' in step["run"]


def test_a_run_with_no_data_leaves_the_last_report_standing(report_module, tmp_path, monkeypatch):
    """Nothing to say is not the same as "there is nothing", and must not overwrite.

    Observed on this branch's own first two runs: each was cancelled by the next
    push, the job ran anyway, found no artifacts, and rewrote the pull request
    comment as "this run produced no coverage data". The job no longer runs on a
    cancelled run at all; this is the second half of that guard, for every other
    way a run can end up with nothing -- so `render` writes no comment body, and
    the workflow step that posts it is gated on that file existing.
    """
    summary_path = tmp_path / "summary.json"
    summary_path.write_text(json.dumps({"data_files": 0}))
    out = tmp_path / "comment.md"
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    report_module.render(
        types.SimpleNamespace(summary=str(summary_path), out=str(out), html_url="", run_url="", **vars(options()))
    )
    assert not out.exists()

    steps = workflow("test.yml")["jobs"]["coverage"]["steps"]
    posting = next(step for step in steps if step.get("name") == "Update the pull request")
    assert "hashFiles('coverage-comment.md')" in posting["if"]


def test_the_gate_is_the_last_step_so_the_comment_is_posted_first():
    """A red gate with no comment explaining it is a gate nobody can act on."""
    steps = workflow("test.yml")["jobs"]["coverage"]["steps"]
    names = [step.get("name", "") for step in steps]
    assert names[-1] == "The coverage requirement"
    assert names.index("Update the pull request") < len(names) - 1
    assert names.index("Upload the HTML report") < names.index("Update the pull request")
