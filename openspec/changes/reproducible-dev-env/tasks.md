## 1. Restore the missing hook entry point

- [x] 1.1 Recover the original script with `git show 1f97c83:.devcontainer/behave_hook.sh > .devcontainer/behave_hook.sh` (do not rewrite it by hand)
- [x] 1.2 Restore the executable bit: `chmod +x .devcontainer/behave_hook.sh`, and confirm it matches `pytest_hook.sh`'s mode
- [x] 1.3 Verify the restored content invokes `behavex` with parallel processes, consistent with the hook's description in `dev-tools/pre-commit-config.yaml`
- [x] 1.4 Audit every other repository-relative `entry:` path in `dev-tools/pre-commit-config.yaml` and confirm each resolves to an existing executable file

## 2. Bring up the reproducible environment

- [x] 2.1 Confirm prerequisites on the host: Docker daemon reachable (`docker info`), and `node`/`npx` available
- [x] 2.2 Start the environment: `npx --yes @devcontainers/cli up --workspace-folder .` (expect a slow first run while features install)
- [x] 2.3 Confirm the container is running and the workspace is bind-mounted with correct file ownership (files must not appear root-owned inside the container)
- [x] 2.4 Confirm `postStartCommand` ran: `pre-commit` resolves on `PATH` inside the container and `.git/hooks/pre-commit` is present
- [x] 2.5 Confirm `SKIP` is set inside the container to the value declared in `.devcontainer/devcontainer.json`, and that it was not restated anywhere else

## 3. Prepare the staged change for commit

- [x] 3.1 Confirm the staged file set inside the container matches what is staged on the host (`git diff --cached --name-only`)
- [x] 3.2 Confirm git identity resolves inside the container (`git config user.name` and `git config user.email`); if it does not, resolve it and note the fix for documentation
- [x] 3.3 Dry-run the gates before committing: `npx --yes @devcontainers/cli exec --workspace-folder . pre-commit run --config dev-tools/pre-commit-config.yaml` against the staged files
- [x] 3.4 Fix any hook failures by correcting the content — not by extending `SKIP` and not with `--no-verify`
- [x] 3.5 Re-stage any files the hooks modified in place (formatters such as `trailing-whitespace` and `end-of-file-fixer` rewrite files)

### Discovered during implementation: commit signing

- [x] 3.6 Diagnose `commit.gpgsign=true` failing inside the container (public keyring present, no secret key; the VS Code extension forwards the GPG agent but the CLI does not)
- [x] 3.7 Forward the host `gpg-agent` extra socket via a `--mount` flag on `devcontainer up`, keeping `.devcontainer/devcontainer.json` portable and the private key on the host
- [x] 3.8 Redirect the container's socket path (`/run/user/1000/gnupg/S.gpg-agent`, not `~/.gnupg/`) at the forwarded socket and confirm signing succeeds

## 4. Commit inside the environment and validate

- [ ] 4.1 Run the commit inside the container: `npx --yes @devcontainers/cli exec --workspace-folder . git commit -m "<message>"`
- [ ] 4.2 Capture the hook output and confirm the hooks actually executed rather than being skipped wholesale
- [ ] 4.3 Verify the commit landed: `git log -1 --stat` on the host shows the new commit with the expected file set
- [ ] 4.4 Verify the working tree is clean afterward and no unintended files were committed
- [ ] 4.5 Confirm `--no-verify` was never used at any point in the flow

## 5. Document the flow for coding agents

- [x] 5.1 Update the root `AGENTS.md` with the headless `devcontainer up` / `devcontainer exec` commands
- [x] 5.2 State explicitly, for each documented command, whether it runs on the host or inside the environment
- [x] 5.3 Document the `` `pre-commit` not found `` failure as the signature of committing outside the environment, with re-running inside it as the remedy
- [x] 5.4 Document how to verify a commit actually landed with its hooks having run
- [x] 5.5 Reference `.devcontainer/devcontainer.json` as the source of the image, `SKIP` list, and hook-install command rather than copying those values into the prose
- [x] 5.6 Review `partcad/AGENTS.md`, `partcad-cli/AGENTS.md`, and `partcad-ide-vscode/AGENTS.md` for host-implied commands that contradict the container-first flow, and reconcile them
- [x] 5.7 Document the GPG agent forwarding step discovered during validation
- [x] 5.8 Correct the documented commands to the `poetry run` prefix (`pytest`/`pc`/`partcad` are not on `PATH`) and note the shared in-project `.venv` caveat

## 6. Document the flow for humans

- [ ] 6.1 Add a CLI-based dev container section to `docs/source/contributing.rst`, alongside the existing VS Code Dev Containers instructions
- [ ] 6.2 Cover the commit step and the host-vs-container distinction for contributors not using VS Code
- [ ] 6.3 Confirm the Sphinx docs still build without new errors or warnings

## 7. Verify against the specs

- [ ] 7.1 Run `openspec validate reproducible-dev-env` and resolve any reported issues
- [ ] 7.2 Walk each requirement in `specs/reproducible-dev-env/spec.md` and confirm the implementation satisfies its scenarios
- [ ] 7.3 Walk the `agent-instructions` and `user-documentation` deltas and confirm the documentation changes satisfy them
- [ ] 7.4 Confirm no new environment values were duplicated outside `.devcontainer/devcontainer.json`
