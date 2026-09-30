#
# PartCAD, 2026
#
# Author: PartCAD (support@partcad.org)
#
# Licensed under Apache License, Version 2.0.
#

"""
Turn the repository's extension recommendations into an install plan.

The plan is what `build.sh` installs into the IDE, and what
`verify_bundle.py` checks afterwards, so the two cannot drift: there is one
description of "which extensions ship" and both read it.

Inputs:
  - `<repo>/.vscode/extensions.json` - the recommendations, the source of truth
    for *what* ships. It is the same list contributors are prompted with, so an
    extension added there reaches the IDE without anything else being edited.
  - `<component>/extensions.json` - what to do about the entries that cannot be
    installed from the gallery, plus the extras an end user needs.
  - `--local <id>=<path>` - extensions built from this repository (the PartCAD
    extension and the IDE bootstrap), installed from their `.vsix` files.
"""

import argparse
import json
import pathlib
import sys
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import jsonc  # noqa: E402  (the path has to be set up first)

# Where an extension comes from.
SOURCE_GALLERY = "gallery"  # an id resolved by the IDE against Open VSX
SOURCE_VSIX = "vsix"  # a .vsix downloaded from an explicit URL
SOURCE_LOCAL = "local"  # a .vsix built from this repository

ACTIONS = ("install", "skip")
SOURCES = (SOURCE_GALLERY, SOURCE_VSIX, SOURCE_LOCAL)


class PolicyError(Exception):
    """The policy file says something that cannot be acted on."""


def _entry(identifier: str, origin: str, override: dict[str, Any] | None) -> dict[str, Any]:
    override = dict(override or {})

    action = override.pop("action", "install")
    if action not in ACTIONS:
        raise PolicyError(f"{identifier}: unknown action {action!r}, expected one of {', '.join(ACTIONS)}")

    source = override.pop("source", SOURCE_GALLERY)
    if source not in SOURCES:
        raise PolicyError(f"{identifier}: unknown source {source!r}, expected one of {', '.join(SOURCES)}")

    url = override.pop("url", None)
    if source == SOURCE_VSIX and not url:
        raise PolicyError(f'{identifier}: source {SOURCE_VSIX!r} needs a "url"')
    if source != SOURCE_VSIX and url:
        raise PolicyError(f'{identifier}: "url" only applies to source {SOURCE_VSIX!r}')

    required = bool(override.pop("required", False))
    reason = override.pop("reason", None)

    # A skipped extension without a reason is how a shipped IDE quietly loses a
    # recommendation, so the reason is not optional.
    if action == "skip" and not reason:
        raise PolicyError(f'{identifier}: "skip" needs a "reason" saying why it cannot ship')

    if override:
        raise PolicyError(f"{identifier}: unknown key(s) {', '.join(sorted(override))}")

    return {
        "id": identifier,
        "origin": origin,
        "action": action,
        "source": source,
        "url": url,
        "required": required,
        "reason": reason,
    }


def build_plan(
    recommendations: list[str],
    policy: dict[str, Any],
    local: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Return the install plan for the given recommendations and policy."""
    overrides = policy.get("extensions", {}) or {}
    extra = policy.get("extra", {}) or {}
    local = local or {}

    unknown_keys = set(policy) - {"extensions", "extra"}
    if unknown_keys:
        raise PolicyError(f"unknown top-level key(s) in the policy: {', '.join(sorted(unknown_keys))}")

    # An override for something that is no longer recommended is dead weight
    # that reads as if it were still in force; say so instead of ignoring it.
    stale = [identifier for identifier in overrides if identifier not in recommendations]
    if stale:
        raise PolicyError(
            "the policy overrides extensions that .vscode/extensions.json no longer recommends: "
            + ", ".join(sorted(stale))
        )

    overlap = sorted(set(extra) & set(recommendations))
    if overlap:
        raise PolicyError(
            'these are recommended already, so they belong under "extensions", not "extra": ' + ", ".join(overlap)
        )

    entries: list[dict[str, Any]] = []
    seen: set[str] = set()

    for identifier in recommendations:
        entries.append(_entry(identifier, "recommended", overrides.get(identifier)))
        seen.add(identifier.lower())

    for identifier, override in extra.items():
        if identifier.lower() in seen:
            raise PolicyError(f"{identifier}: listed twice")
        entries.append(_entry(identifier, "extra", override))
        seen.add(identifier.lower())

    for identifier, path in local.items():
        if identifier.lower() in seen:
            raise PolicyError(f"{identifier}: listed twice")
        entry = _entry(identifier, "local", {"source": SOURCE_LOCAL, "required": True})
        entry["path"] = path
        entries.append(entry)
        seen.add(identifier.lower())

    return {
        "install": [entry for entry in entries if entry["action"] == "install"],
        "skip": [entry for entry in entries if entry["action"] == "skip"],
    }


def load_plan(repo_root: pathlib.Path, policy_path: pathlib.Path, local: dict[str, str]) -> dict[str, Any]:
    recommended_path = repo_root / ".vscode" / "extensions.json"
    recommendations = jsonc.load(recommended_path).get("recommendations", [])
    if not recommendations:
        raise PolicyError(f"{recommended_path} recommends nothing; the IDE would ship with no extensions")
    return build_plan(recommendations, jsonc.load(policy_path), local)


def explain(plan: dict[str, Any]) -> str:
    lines = []
    for entry in plan["install"]:
        source = entry["source"]
        if source == SOURCE_VSIX:
            source = f"vsix {entry['url']}"
        elif source == SOURCE_LOCAL:
            source = f"local {entry['path']}"
        flag = "required" if entry["required"] else "optional"
        lines.append(f"  install  {entry['id']:<45} {source}, {flag}")
    for entry in plan["skip"]:
        lines.append(f"  skip     {entry['id']:<45} {entry['reason']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo-root", type=pathlib.Path, required=True, help="the repository root")
    parser.add_argument("--policy", type=pathlib.Path, required=True, help="this component's extensions.json")
    parser.add_argument(
        "--local",
        action="append",
        default=[],
        metavar="ID=PATH",
        help="an extension built from this repository, as <publisher.name>=<path to .vsix>",
    )
    parser.add_argument("--output", type=pathlib.Path, help="write the plan here instead of to stdout")
    parser.add_argument(
        "--explain",
        action="store_true",
        help="print the plan for a human rather than as JSON; combines with --output",
    )
    args = parser.parse_args(argv)

    local: dict[str, str] = {}
    for item in args.local:
        identifier, separator, path = item.partition("=")
        if not separator or not identifier or not path:
            parser.error(f"--local expects <id>=<path>, got {item!r}")
        local[identifier] = path

    try:
        plan = load_plan(args.repo_root, args.policy, local)
    except PolicyError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    text = json.dumps(plan, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")

    if args.explain:
        print(explain(plan))
    elif not args.output:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
