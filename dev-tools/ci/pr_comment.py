#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""One comment on a pull request, edited in place on every run.

A CI job that has something to say about a pull request -- today the coverage
report, tomorrow whatever else -- says it here. The comment is identified by an
invisible marker in its body rather than by who wrote it or what it starts with,
so a run finds its own previous comment and edits that instead of posting a
fifteenth copy under a pull request somebody pushed to fifteen times.

Two things about GitHub's token make this smaller than it looks, and both are
the reason this is a script rather than an action:

  * A pull request **from a fork** runs with a read-only `GITHUB_TOKEN`, on
    purpose: a fork's branch is untrusted code, and a token that could write to
    the repository would be a token that untrusted code can reach. So the write
    fails with 403 there and nothing can be done about it from inside the run
    that measured the coverage. That is not an error to fail a job over -- the
    job summary carries the same report, and the gate still gates -- so a 403 on
    the write is reported as a warning and the script exits 0.

  * Everything else is a real failure and exits non-zero. A malformed body, a
    pull request number that does not exist, a network error: those are bugs in
    the caller or in the run, and swallowing them would make this script
    silently do nothing for as long as nobody checks.

`urllib` rather than a GitHub client library: this runs in a job whose whole
dependency list is coverage.py, and a REST call to two endpoints does not earn a
package.
"""

import argparse
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

API = os.environ.get("GITHUB_API_URL", "https://api.github.com")


def request(method, url, token, payload=None):
    """One authenticated REST call, returning the decoded JSON body."""
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Authorization": f"Bearer {token}",
        "User-Agent": "partcad-ci",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    call = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(call) as response:  # nosec B310 - the URL is the API, built here
        body = response.read().decode("utf-8")
    return json.loads(body) if body else None


def find_comment(repo, number, marker, token):
    """The id of this script's previous comment on the pull request, if any.

    Pull request comments are issue comments: the review-comment endpoints are a
    different thing entirely, attached to lines of the diff.
    """
    page = 1
    while True:
        url = f"{API}/repos/{repo}/issues/{number}/comments?per_page=100&page={page}"
        comments = request("GET", url, token)
        if not comments:
            return None
        for comment in comments:
            if marker in (comment.get("body") or ""):
                return comment["id"]
        page += 1


def failed(what, error):
    """Report an HTTP error as a job annotation, and be the exit status for it."""
    print(f"::error title=PR comment::{what}: {error.code} {error.reason}: {error.read().decode('utf-8', 'replace')}")
    return 1


def main(argv=None):
    """Post or edit the comment, and treat only a read-only token as survivable."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--body-file", required=True, help="file holding the markdown to post")
    parser.add_argument("--marker", required=True, help="invisible string identifying this comment")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""), help="owner/name")
    parser.add_argument("--pr", default="", help="pull request number; nothing is posted without one")
    args = parser.parse_args(argv)

    if not args.pr:
        print("No pull request to update.")
        return 0
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        print("::warning title=PR comment::GITHUB_TOKEN is not set; the pull request was not updated")
        return 0

    body = pathlib.Path(args.body_file).read_text(encoding="utf-8")
    if args.marker not in body:
        # Without the marker the next run cannot find this comment, and the
        # thread grows one copy per push. Worth failing over: it is a caller bug
        # and it is invisible until somebody counts the comments.
        print(f"::error title=PR comment::the body in {args.body_file} does not carry the marker")
        return 1

    # The lookup is outside the survivable case below, deliberately. Reading
    # issue comments is not what a fork's token is refused -- it can read the
    # repository perfectly well -- so a 403 here is something else entirely: a
    # rate limit, most likely, which GitHub also answers 403. Inside that
    # `except` it would be reported as "this is a fork, never mind", and the
    # comment would go missing on ordinary pull requests with nothing said.
    try:
        existing = find_comment(args.repo, args.pr, args.marker, token)
    except urllib.error.HTTPError as error:
        return failed("could not read the existing comments", error)

    try:
        if existing is None:
            url = f"{API}/repos/{args.repo}/issues/{args.pr}/comments"
            posted = request("POST", url, token, {"body": body})
            print(f"Posted {posted['html_url']}")
        else:
            url = f"{API}/repos/{args.repo}/issues/comments/{existing}"
            posted = request("PATCH", url, token, {"body": body})
            print(f"Updated {posted['html_url']}")
    except urllib.error.HTTPError as error:
        # 403 and only 403, and only on the write. GitHub answers 403 --
        # "Resource not accessible by integration" -- when an authenticated
        # token is refused the write, which is the fork case; 401 means the
        # credential itself is bad. They were handled together at first, and
        # that is a hole rather than a simplification: a token that has stopped
        # working is a real breakage this script exists to do something about,
        # and reporting it as "this is a fork, never mind" would hide it on
        # every pull request, forks and branches alike, for as long as nobody
        # wondered where the comment went.
        if error.code == 403:
            # Said once, plainly, so that a maintainer reading a fork's run
            # knows where the report went rather than thinking this broke.
            print(
                "::warning title=PR comment::this run's token cannot write to the repository "
                "(a pull request from a fork), so the comment was not posted. "
                "The same report is in this job's summary."
            )
            return 0
        return failed("the comment could not be written", error)
    return 0


if __name__ == "__main__":
    sys.exit(main())
