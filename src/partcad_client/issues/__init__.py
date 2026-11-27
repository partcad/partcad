#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""PartCAD's issues on GitHub, for an agent that hit a defect in PartCAD: search, draft, record.

Reads only. Upvoting and filing are left to the agent's own GitHub access.
"""

import datetime
import hashlib
import json
import os
import platform
import re
import shutil
import string
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

from .. import __version__

_HERE = os.path.dirname(os.path.abspath(__file__))
API = "https://api.github.com"
TIMEOUT = 15
SEARCH_LIMIT = 5
TITLE_LIMIT = 300
BODY_LIMIT = 2000
TRACEBACK_LINES = 25
URL_LIMIT = 8000


class Unavailable(Exception):
    """GitHub cannot be asked, or the user's configuration says not to."""


def _data(name: str) -> str:
    with open(os.path.join(_HERE, name), "r", encoding="utf-8") as f:
        return f.read()


def config() -> dict:
    return json.loads(_data("config.json"))


def repository() -> str:
    return config()["repository"]


def trusted() -> dict:
    """The maintainers whose comments are guidance, by GitHub user id."""
    return {entry["id"]: entry["login"] for entry in config()["trusted"]}


def policy() -> str:
    from partcad_utils.user_config import user_config

    return user_config.agent_issues


def _allowed(network: bool = True) -> str:
    from partcad_utils.user_config import user_config

    current = user_config.agent_issues
    if current == "off":
        raise Unavailable("'agentIssues' is 'off' in the user's PartCAD configuration")
    if network and user_config.offline:
        raise Unavailable("PartCAD is offline")
    return current


# --- Signature ---------------------------------------------------------------

_FRAME = re.compile(r'File "([^"]+)", line \d+, in (\S+)')
_OWN = re.compile(r"partcad(?:_[a-z_]+)?")
_RAISED = re.compile(r"^([A-Za-z_][\w.]*(?:Error|Exception|Exit|Interrupt|Warning|Failure))(?::|$)")


def normalize(message: Optional[str]) -> str:
    """The message without what differs between machines and runs."""
    text = message or ""
    text = re.sub(r"\b\w+://\S+", "<url>", text)
    text = re.sub(r"//[\w./-]*(?::[\w.;=,-]+)?", "<object>", text)
    text = re.sub(r"'[^'\n]*'|\"[^\"\n]*\"", "<q>", text)
    text = re.sub(r"(?:\b[A-Za-z]:)?(?:[\\/][^\s\\/:'\"<>]+)+[\\/]?", "<path>", text)
    text = re.sub(r"\b0x[0-9a-fA-F]+\b|\b(?=[0-9a-fA-F]*\d)[0-9a-fA-F]{7,}\b", "<hex>", text)
    text = re.sub(r"\d+(?:\.\d+)?", "<n>", text)
    return " ".join(text.split())


def frame(traceback: Optional[str]) -> str:
    """The innermost frame of PartCAD's own code, as 'package/module.py:function'."""
    found = ""
    for path, function in _FRAME.findall(traceback or ""):
        parts = re.split(r"[\\/]", path)
        own = [i for i, part in enumerate(parts[:-1]) if _OWN.fullmatch(part)]
        if own:
            found = "%s:%s" % ("/".join(parts[own[-1] :]), function)
    return found


def _raised(traceback: Optional[str]) -> tuple:
    for line in reversed((traceback or "").strip().splitlines()):
        raised = _RAISED.match(line.strip())
        if raised:
            return raised.group(1).rsplit(".", 1)[-1], line.strip()[len(raised.group(0)) :].strip()
    return "", None


def error_type(traceback: Optional[str]) -> str:
    return _raised(traceback)[0]


def signature(message: Optional[str], traceback: Optional[str] = None) -> str:
    """'pc-sig:<hex>': one defect's name, the same on every machine that hits it, whoever asks."""
    kind, raised = _raised(traceback)
    if raised is None:
        kind, raised = _raised(message)
    key = "\n".join((kind, frame(traceback), normalize(message if raised is None else raised)))
    return "pc-sig:" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


# --- Scrubbing ---------------------------------------------------------------

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_SECRET = re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16})\b")
_ASSIGNED = re.compile(
    r"(?i)\b(authorization|bearer|token|password|passwd|secret|api[_-]?key)(\s*[:=]\s*|\s+)([\"']?)[^\s\"',]+"
)


def _aliases(workspace: Optional[str]) -> list:
    pairs = []
    if workspace:
        pairs.append((os.path.abspath(workspace), "<workspace>"))
    home = os.path.expanduser("~")
    if home and len(home) > 1 and home != "~":
        pairs.append((home, "~"))
    spelled = set()
    for path, alias in pairs:
        for variant in (path, path.replace("\\", "/"), path.replace("/", "\\")):
            spelled.add((variant, alias))
    return sorted(spelled, key=lambda pair: -len(pair[0]))


def scrub(text: Optional[str], workspace: Optional[str] = None) -> str:
    """'text' without the user's paths, addresses and credentials."""
    text = text or ""
    for path, alias in _aliases(workspace):
        text = re.sub(re.escape(path) + r"(?=[\\/\s'\":,)]|$)", lambda _: alias, text)
    text = _SECRET.sub("<redacted>", text)
    text = _ASSIGNED.sub(lambda m: m.group(1) + m.group(2) + m.group(3) + "<redacted>", text)
    return _EMAIL.sub("<email>", text)


# --- Untrusted text ----------------------------------------------------------

_HIDDEN = re.compile(r"<!--.*?(?:-->|\Z)", re.S)
_INVISIBLE = re.compile("[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f­​-‏‪-‮⁠-⁤⁦-⁯" "﻿\U000e0000-\U000e007f]")


def untrusted_text(text: Optional[str], limit: int) -> str:
    """Third-party text, without what a reader of the page would not see, and bounded."""
    text = _INVISIBLE.sub("", _HIDDEN.sub("", text or ""))
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) > limit:
        text = text[:limit] + " <%d more characters>" % (len(text) - limit)
    return text


# --- GitHub ------------------------------------------------------------------


def _token() -> Optional[str]:
    """The user's own GitHub token, for the rate limit. Used to read and nothing else."""
    for name in ("GH_TOKEN", "GITHUB_TOKEN"):
        if os.environ.get(name):
            return os.environ[name]
    gh = shutil.which("gh")
    if gh:
        try:
            out = subprocess.run([gh, "auth", "token"], capture_output=True, text=True, timeout=5, check=False)
        except (OSError, subprocess.SubprocessError):
            return None
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    return None


def _get(path: str, params: Optional[dict] = None, token: Optional[str] = None):
    url = "%s/%s" % (API, path.lstrip("/"))
    if params:
        url += "?" + urllib.parse.urlencode(params)
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "partcad/%s" % __version__,
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # nosec B310 - a fixed https host
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise Unavailable("GitHub answered %d to %s" % (e.code, path)) from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise Unavailable("GitHub could not be reached: %s" % e) from e


def _keywords(text: str, count: int = 6) -> str:
    words = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", re.sub(r"<[a-z]+>", " ", normalize(text)))
    return " ".join(words[:count])


def _comments(repo: str, number: int, token: Optional[str]) -> tuple:
    maintainers = trusted()
    notes = config()["notes"]
    guidance, others = [], 0
    for comment in _get("repos/%s/issues/%d/comments" % (repo, number), {"per_page": 100}, token):
        author = (comment.get("user") or {}).get("id")
        if author in maintainers:
            guidance.append(
                {
                    "author": maintainers[author],
                    "date": comment.get("created_at"),
                    "url": comment.get("html_url"),
                    "text": comment.get("body") or "",
                }
            )
        else:
            others += 1
    return {"trust": notes["trusted"], "comments": guidance}, others


def _upvoted(repo: str, number: int, token: Optional[str], login: Optional[str]) -> Optional[bool]:
    if not login:
        return None
    reactions = _get("repos/%s/issues/%d/reactions" % (repo, number), {"content": "+1", "per_page": 100}, token)
    return any((reaction.get("user") or {}).get("login") == login for reaction in reactions)


def _issue(repo: str, item: dict, token: Optional[str], login: Optional[str]) -> dict:
    notes = config()["notes"]
    number = item["number"]
    guidance, others = _comments(repo, number, token) if item.get("comments") else ({}, 0)
    found = {
        "number": number,
        "url": item.get("html_url"),
        "state": item.get("state"),
        "state_reason": item.get("state_reason"),
        "labels": [label.get("name") for label in item.get("labels") or []],
        "upvotes": (item.get("reactions") or {}).get("+1", 0),
        "upvoted_by_you": _upvoted(repo, number, token, login),
        "untrusted": {
            "trust": notes["untrusted"],
            "author": (item.get("user") or {}).get("login"),
            "title": untrusted_text(item.get("title"), TITLE_LIMIT),
            "description": untrusted_text(item.get("body"), BODY_LIMIT),
        },
        "other_comments": {"count": others, "trust": notes["withheld"]},
    }
    if guidance:
        found["guidance"] = guidance
    return found


def search(
    signature: Optional[str] = None,
    text: Optional[str] = None,
    workspace: Optional[str] = None,
    limit: int = SEARCH_LIMIT,
) -> dict:
    """PartCAD's issues matching a signature, or failing that an error message, open and closed."""
    current = _allowed()
    repo = repository()
    token, login = _token(), None
    if token:
        try:
            login = _get("user", token=token).get("login")
        except Unavailable:
            token = None
    items = {}
    here = recorded(signature) if signature else None
    if here:
        items[here["issue"]] = _get("repos/%s/issues/%d" % (repo, here["issue"]), token=token)
    queries = []
    if signature:
        queries.append('"%s"' % signature)
    if text and _keywords(scrub(text, workspace)):
        queries.append(_keywords(scrub(text, workspace)) + " in:title,body")
    for query in queries:
        if items:
            break
        answer = _get("search/issues", {"q": "repo:%s is:issue %s" % (repo, query), "per_page": limit}, token)
        for item in answer.get("items", []):
            if "pull_request" not in item:
                items.setdefault(item["number"], item)
    result = {
        "policy": current,
        "do": config()["policies"][current],
        "repository": repo,
        "signature": signature,
        "installed": __version__,
        "issues": [_issue(repo, item, token, login) for item in list(items.values())[:limit]],
        "upvote": "gh api -X POST repos/%s/issues/<number>/reactions -f content=+1" % repo,
    }
    if here:
        result["reported_here"] = here
    if any(issue["state"] == "closed" for issue in result["issues"]):
        try:
            from .. import selfupdate

            latest = selfupdate.latest_version()
            if selfupdate.is_newer(latest, __version__):
                result["newer_release"] = latest
        except Exception:  # pylint: disable=broad-except
            pass
    return result


# --- Draft -------------------------------------------------------------------


def installation() -> str:
    try:
        from .. import selfupdate

        return selfupdate.installation_kind()
    except Exception:  # pylint: disable=broad-except
        return "unknown"


def sandbox() -> str:
    try:
        from partcad_utils.user_config import user_config

        return str(user_config.python_sandbox or "-")
    except Exception:  # pylint: disable=broad-except
        return "-"


def _title(error: str) -> str:
    first = next((line.strip() for line in (error or "").splitlines() if line.strip()), "PartCAD failed")
    return first if len(first) <= 100 else first[:97] + "..."


def draft(
    error: str,
    traceback: Optional[str] = None,
    summary: Optional[str] = None,
    reproduction: Optional[str] = None,
    method: Optional[str] = None,
    daemon: Optional[str] = None,
    agent: Optional[str] = None,
    workspace: Optional[str] = None,
    title: Optional[str] = None,
) -> dict:
    """A new issue for PartCAD's defect: its title, its body, and how to file it."""
    current = _allowed(network=False)
    repo = repository()
    sig = signature(error, traceback)
    lines = (traceback or "").rstrip().splitlines()
    if len(lines) > TRACEBACK_LINES:
        lines = ["..."] + lines[-TRACEBACK_LINES:]
    shown = [("Method: %s" % method) if method else "", error or "", "\n".join(lines)]
    values = {
        "marker": config()["marker"],
        "summary": scrub(summary, workspace) or "-",
        "error": scrub("\n".join(part for part in shown if part), workspace).replace("```", "'''"),
        "reproduction": scrub(reproduction, workspace) or "-",
        "version": __version__,
        "daemon": daemon or "-",
        "installation": installation(),
        "platform": "%s %s (%s)" % (platform.system(), platform.release(), platform.machine()),
        "python": platform.python_version(),
        "sandbox": sandbox(),
        "agent": agent or "-",
        "signature": sig,
    }
    body = string.Template(_data("report.md")).safe_substitute(values)
    title = scrub(title, workspace) if title else _title(scrub(error, workspace))
    url = "https://github.com/%s/issues/new?%s" % (repo, urllib.parse.urlencode({"title": title, "body": body}))
    if len(url) > URL_LIMIT:
        url = "https://github.com/%s/issues/new?%s" % (repo, urllib.parse.urlencode({"title": title}))
    result = {
        "policy": current,
        "do": config()["policies"][current],
        "repository": repo,
        "signature": sig,
        "title": title,
        "body": body,
        "file": "gh api repos/%s/issues -f title=<title> -F body=@<file holding the body>" % repo,
        "url": url,
    }
    here = recorded(sig)
    if here:
        result["reported_here"] = here
    return result


# --- Ledger ------------------------------------------------------------------


def ledger_path() -> str:
    from partcad_utils.user_config import UserConfig

    return os.path.join(UserConfig.get_config_dir(), "issues", "reported.json")


def _ledger() -> dict:
    try:
        with open(ledger_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def recorded(sig: Optional[str]) -> Optional[dict]:
    """What this machine did about a signature: the issue, and whether it filed or upvoted it."""
    return _ledger().get(sig) if sig else None


def record(sig: str, issue: int, action: str = "filed") -> dict:
    if not re.fullmatch(r"pc-sig:[0-9a-f]{12}", sig or ""):
        raise ValueError("Not a signature: %r" % sig)
    entry = {
        "issue": int(issue),
        "action": action,
        "version": __version__,
        "date": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    ledger = _ledger()
    ledger[sig] = entry
    path = ledger_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = "%s.%d.tmp" % (path, os.getpid())
    with open(temporary, "w", encoding="utf-8") as f:
        json.dump(ledger, f, indent=2, sort_keys=True)
    os.replace(temporary, path)
    return entry


__all__ = [
    "Unavailable",
    "config",
    "draft",
    "normalize",
    "policy",
    "record",
    "recorded",
    "repository",
    "scrub",
    "search",
    "signature",
    "trusted",
    "untrusted_text",
]
