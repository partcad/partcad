---
name: pc-ci-dependency-bot
description: Sweep the open dependency-bot pull requests once - rebase the stale ones, re-trigger infrastructure failures, and merge the green patch and minor updates. Use when the user wants to baby sit, unblock, or push through pending dependabot pull requests, and on each firing of a /loop that watches them.
allowed-tools: Bash(gh:*), Bash(git:*), AskUserQuestion
license: Apache 2.0
compatibility: Requires GitHub CLI (`gh`), authenticated with merge rights on the target repository.
metadata:
  author: partcad
  version: "2.0"
---

Sweep the open dependency-bot pull requests once: rebase the stale ones, re-trigger
infrastructure failures, and merge the ones that are green and in scope.

**This skill performs a single pass and exits.** It never sleeps and never loops
internally. To baby sit continuously, drive it from the loop skill:

```
/loop 1h pc-ci-dependency-bot
```

Each firing is a fresh session with no memory of the last one, so every piece of state
this skill relies on is re-read from the GitHub API rather than carried in context.

**Scope:** GitHub only. The triage below is built on `gh` and on dependabot's comment
commands. GitLab and Gerrit are not supported — stop and say so rather than improvising
an equivalent.

**Input:** Optionally a repository (URL or `OWNER/NAME`). Defaults to the current
working directory's repository.

## Steps

### 1. Select the repository

If the user named a repository, use it. Otherwise infer it from the conversation, then
fall back to `git remote get-url origin`. If it is still ambiguous, ask with the
**AskUserQuestion** tool.

Announce the choice and how to change it:

```
Using upstream: <owner/name> — re-run with `pc-ci-dependency-bot <owner/name>` to target another repository.
```

Pass the repository explicitly on every `gh` call (`--repo <owner/name>`) so the skill
behaves identically inside and outside a checkout.

### 2. List the open bot pull requests

```bash
gh pr list --repo <owner/name> --state open --author "app/dependabot" \
  --json number,title,url,headRefName,mergeStateStatus,labels
```

If the list is empty, report "No open dependency-bot pull requests" and **exit**. Do not
wait — the next `/loop` firing is the wait.

Note that this repository configures dependabot for `github-actions` on a **monthly**
interval (`.github/dependabot.yml`), so most passes will find nothing. That is the
expected outcome, not a failure.

Then handle each pull request with steps 3–6. A pull request that gets an action in step
3 is done for this pass; move to the next one.

### 3. Bring the pull request up to date first

CI results from before a base-branch move describe a merge that no longer exists, so
settle freshness before reading any logs.

Read `mergeStateStatus` from step 2:

- **`BEHIND`** — the branch is out of date. Ask dependabot to rebase and move on to the
  next pull request; the new runs are evaluated on a later pass:

  ```bash
  gh pr comment <number> --repo <owner/name> --body "@dependabot rebase"
  ```

  Do not re-comment if the most recent comment on the pull request is already an
  unactioned `@dependabot rebase` — check with
  `gh pr view <number> --repo <owner/name> --json comments`. Dependabot queues these, and
  repeating the request hourly spams the thread without changing anything.

- **`DIRTY`** — the branch conflicts with the base. Dependabot cannot rebase through a
  conflict. Report it under "Needs attention" and move on.

- **`BLOCKED`** — a required review or check is missing, or branch protection is
  unsatisfied. Continue to step 4; the merge in step 6 will surface the real reason.

- **`CLEAN`, `UNSTABLE`, `HAS_HOOKS`** — up to date. Continue to step 4.

### 4. Read the check status

```bash
gh pr checks <number> --repo <owner/name> --json name,state,bucket,link
```

The `bucket` field categorises each check as `pass`, `fail`, `pending`, `skipping`, or
`cancel`.

- Any check in `pending` — the pull request is still building. Skip it this pass and
  report it as pending.
- All checks in `pass` or `skipping` — go to step 6.
- Any check in `fail` or `cancel` — go to step 5.

### 5. Triage the failures

For each failing check, read enough of the log to classify it:

```bash
gh run view <run-id> --repo <owner/name> --log-failed
```

**Re-trigger only failures that are not caused by the pull request** — network timeouts,
runner eviction, registry rate limits, corrupted package downloads and similar
infrastructure noise. Compile errors, test assertions and lint violations are caused by
the change: leave them, and report the pull request under "Needs attention".

Before re-triggering, check how many attempts the run has already had. The attempt
counter lives in the API, which is what makes it survive across `/loop` firings:

```bash
gh run list --repo <owner/name> --branch <headRefName> \
  --json databaseId,workflowName,conclusion,status,attempt
```

`attempt` is 1 for a run that has never been re-triggered. **Re-trigger at most 3 times**
— if `attempt >= 4`, stop re-triggering that run and report the pull request under "Needs
attention" instead. A failure that survives three re-runs is not flaky, whatever the log
looks like.

```bash
gh run rerun <run-id> --repo <owner/name> --failed
```

A re-trigger completes this pull request for this pass; the result is evaluated on a
later firing.

### 6. Merge what is in scope

Only reached when every check passes.

**Check the version jump before merging.** Dependabot titles carry it, in the form
`bump <dependency> from <old> to <new>`. Compare the leading numeric component:

- **Patch or minor bump** — approve and merge:

  ```bash
  gh pr review <number> --repo <owner/name> --approve
  gh pr merge <number> --repo <owner/name> --squash
  ```

- **Major bump** (leading component differs, e.g. `from 4 to 8`) — **do not merge.**
  Green CI does not prove a major bump is safe; it proves the parts covered by CI still
  run. Report it under "Needs attention" with the old and new versions and let a human
  decide.

- **Version unparseable from the title** — treat it as a major bump and report it.

If the merge is rejected (branch protection, required reviewers, a merge queue), report
the error verbatim rather than working around it.

## Output

Report every pull request examined, then exit.

```
Using upstream: <owner/name> — re-run with `pc-ci-dependency-bot <owner/name>` to target another repository.

## PR #<number> — <title>
<what was found and what was done>
✓ <Merged | Rebase requested | Re-triggered (attempt N of 3) | Pending>

## PR #<number> — <title>
<what was found and what was done>
✓ <action>

---
Swept N pull requests: <x> merged, <y> awaiting CI, <z> need attention.
```

If any pull request needs a human:

```
## Needs attention

**PR:** #<number> — <title>
**URL:** <url>

### Issue
<what is blocking it: conflict, real test failure, exhausted retries, or major version bump>

**Options:**
1. <option 1>
2. <option 2>
3. Other approach
```

End the pass there. Do not ask a blocking question and do not wait for an answer — a
`/loop` firing has no one to answer it. Report the options and exit; the user acts
between firings.

## Guardrails

- One pass per invocation. Never sleep, never restart from step 1.
- Never re-trigger a run that is already on its 4th attempt.
- Never re-trigger a failure the pull request actually caused.
- Report blockers and exit rather than guessing or working around branch protection.
