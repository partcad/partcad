#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Lockwire as a PartCAD qualification test of the 'other' subtype.

Run by PartCAD's 'wrapper_qual.py' in a sandbox that has 'lockwire' installed
(see this package's 'partcad.yaml'), with 'request' and 'path' as its globals.
The object the test is declared on names its lockfile ('lockfile:', relative
to its package); this hands it to Lockwire's own API, 'lockwire.api.check()' --
what 'lockwire check --json' prints -- and turns the document that comes back
into what PartCAD reads of a qualification test:

    passed    GO -> True; GO with notes -> True, unless 'strict:'; NO-GO and a
              refused lockfile -> False; NOT SCORED -> None (nothing could be
              compared, which is neither a pass nor a failure)
    findings  every violation an error, every warning a warning, every quantity
              not scored a note, each in the sentence 'lockwire check' prints
    report    every finding as a row of a table, in Lockwire's own columns

Nothing about what a budget means is decided here: that is Lockwire's, and this
only carries its words across.
"""

import os

# The columns of the report, in the order 'lockwire check' says them.
COLUMNS = [
    {"key": "severity", "title": "Severity"},
    {"key": "quantity", "title": "Quantity"},
    {"key": "observed", "title": "Observed"},
    {"key": "expected", "title": "Expected"},
    {"key": "delta", "title": "Δ"},
    {"key": "dependent", "title": "Dependent"},
    {"key": "owner", "title": "Owner"},
    {"key": "action", "title": "Action"},
]

# Lockwire's exit codes, which say its verdict whatever word it is spelled with.
GO, NO_GO, REFUSED, NOT_SCORED = 0, 1, 2, 3

LEVELS = {"violation": "error", "warning": "warning", "not_scored": "info"}


def lockfile_of(request) -> str:
    """The lockfile the object names, as an absolute path."""
    name = request.get("lockfile") or "lockwire.yaml"
    base = request.get("package_dir") or os.getcwd()
    return name if os.path.isabs(name) else os.path.normpath(os.path.join(base, name))


def _flag(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def sentence(finding: dict) -> str:
    """One finding as 'lockwire check' prints it."""
    severity = str(finding.get("severity") or "").upper().replace("_", "-")
    text = "%s %s" % (severity or "FINDING", finding.get("quantity") or "")
    if finding.get("observed") or finding.get("expected"):
        text += " — observed %s, expected %s" % (finding.get("observed") or "?", finding.get("expected") or "?")
    if finding.get("delta"):
        text += " (Δ %s)" % finding["delta"]
    if finding.get("dependent"):
        text += "; dependent: %s" % finding["dependent"]
    if finding.get("action"):
        text += "; action: %s" % finding["action"]
    return text


def verdict_code(document: dict) -> int:
    """Lockwire's verdict as its exit code, from the code it says or the word it spells it with."""
    code = document.get("exit_code")
    if isinstance(code, int):
        if code == 0:
            return GO
        return code
    word = str(document.get("verdict") or "").upper().replace("-", "_").replace(" ", "_")
    return {"GO": GO, "GO_WITH_NOTES": GO, "NO_GO": NO_GO, "REFUSED": REFUSED, "NOT_SCORED": NOT_SCORED}.get(
        word, NO_GO
    )


def judge(document: dict, strict: bool = False) -> dict:
    """What PartCAD reads of a qualification test, from the document 'lockwire.api.check()' returns."""
    found = [finding for finding in document.get("findings") or [] if isinstance(finding, dict)]
    findings = [{"level": LEVELS.get(str(f.get("severity")), "info"), "text": sentence(f)} for f in found]
    word = str(document.get("verdict") or "")
    headline = document.get("headline")
    counts = document.get("counts") or {}
    summary = headline or ", ".join("%s %s" % (counts[key], key.replace("_", " ")) for key in sorted(counts))
    report = {
        "title": "Lockwire: %s" % (document.get("robot") or "the robot"),
        "verdict": word.replace("_", " "),
        "summary": summary,
        "columns": COLUMNS,
        "rows": [{column["key"]: finding.get(column["key"]) for column in COLUMNS} for finding in found],
    }
    answer = {"success": True, "findings": findings, "report": report}
    code = verdict_code(document)
    if code == NOT_SCORED:
        answer["passed"] = None
        answer["skipped"] = "Lockwire scored nothing: no comparison had both of its figures declared"
    elif code == GO:
        notes = word.upper().replace("-", "_").replace(" ", "_") == "GO_WITH_NOTES" or bool(counts.get("warning"))
        answer["passed"] = not (strict and notes)
        if strict and notes:
            findings.append({"level": "error", "text": "GO with notes, and 'strict' fails it"})
    else:
        answer["passed"] = False
        if not any(finding["level"] == "error" for finding in findings):
            findings.append({"level": "error", "text": "Lockwire says %s" % (word or "NO-GO")})
    return answer


def process(path, request):
    lockfile = lockfile_of(request)
    if not os.path.isfile(lockfile):
        return {
            "success": True,
            "passed": False,
            "findings": [
                {
                    "level": "error",
                    "text": "No Lockwire lockfile at %s. Create one with 'lockwire start <robot.urdf>' (or "
                    "'lockwire start --example rover'), or name another with 'lockfile:'" % lockfile,
                }
            ],
        }
    try:
        import lockwire.api as lw
    except ImportError as e:
        return {"success": True, "passed": None, "skipped": "Lockwire is not installed in this sandbox: %s" % e}
    try:
        document = lw.check(lockfile)
    except Exception as e:  # Lockwire refuses a lockfile it cannot read, saying why.
        return {
            "success": True,
            "passed": False,
            "findings": [{"level": "error", "text": "Lockwire refused %s: %s" % (lockfile, e)}],
        }
    return judge(document, strict=_flag(request.get("strict")))
