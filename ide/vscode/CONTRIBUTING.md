# PartCAD Visual Studio Code Extension

## Submitting your changes

Please create a pull request.

## Prerequisites

Node.js and `npm`, and nothing else. **There is no Python in this package.** The extension is a JSON-RPC client
of the `partcad-json-rpc` service: it carries no language server and no vendored dependencies, so it needs no
interpreter, no `nox` and none of the native build prerequisites those used to require. The `bundled/libs` tree
that did is gone; see "There used to be a second backend" in [AGENTS.md](./AGENTS.md).

CI pins **Node 22** for packaging (`.github/workflows/vsix.yml`) and runs the tests on Node 24
(`.github/workflows/npm-test.yml`). Anything from 22 up works — `@vscode/test-cli` and `@vscode/test-electron`
declare `node >= 22`, so an older Node installs with `EBADENGINE` warnings and cannot run `npm test`.

Run every command below from this directory (`ide/vscode/`), on the host or inside the dev container as you
prefer. Unlike the Python packages, nothing here needs the container's pinned toolchain: this package is
Node and TypeScript, the container carries Node as well, and CI builds it on a plain runner with
`actions/setup-node`. What matters is the Node version, not where it comes from.

## Setup

```bash
npm ci
```

`npm ci` installs exactly what `package-lock.json` pins, which is what both workflows do. `npm install` is fine
while developing, but re-lock deliberately rather than as a side effect.

## Building and packaging

```bash
npm run vsce-package
```

That is the whole build. `vsce package` runs the `vscode:prepublish` script, which is the production webpack
build, so this compiles and packages in one step and writes `partcad.vsix` into this directory.

The output name is fixed rather than versioned because `ide/standalone/build.sh` looks for that exact file when
it builds the copy of the extension that ships inside the PartCAD IDE. The release asset is a renamed copy —
`vsix.yml` does `cp partcad.vsix "partcad-$(jq -r .version package.json).vsix"` — rather than a second build.

One build serves every platform. The package has no compiled content left, so the `.vsix` you produce is the
`.vsix` CI produces on its single `ubuntu-24.04` runner; this is why `vsix.yml` has a one-entry matrix and why
there is no per-platform packaging step anywhere.

To try the result:

```bash
code --install-extension partcad.vsix
```

`.vscodeignore` is what keeps your working directory out of the package, and CI never exercises it: `vsix.yml`
packages a fresh checkout, where none of what it excludes exists yet. Two things it has had to learn, both
found by packaging a directory that had been worked in:

* A stale Python virtualenv (`.nox/`, `.venv/`, `.conda/`) *breaks* the build rather than merely bloating the
  package. Its `bin/python*` symlinks point at an interpreter that may not exist, `vsce` fails to `stat` them,
  and packaging dies with `currentLevel is undefined for home in ...`.
* `out/` is where `npm run compile-tests` puts the compiled tests, and `npm test` runs that first — so running
  the tests before packaging used to add 54 files of test build output to the `.vsix`. The shipped bundle is
  `dist/`; `out/` is never part of it.

So build artefacts and throwaway directories go in `.vscodeignore` when you add them, not when someone notices
a 20 MB `.vsix`.

## Developing

Open the **repository root** in VS Code and run the `Debug Extension and Python` launch configuration
(`.vscode/launch.json`). It starts the `npm: watch` task and opens an Extension Development Host with
`--extensionDevelopmentPath=ide/vscode`. `npm run watch` on its own is the same webpack watch build without the
host.

Two bundles come out of webpack, because the extension host is CommonJS and the viewer webview is a browser
context: `dist/extension.js` and `dist/viewer.js`. `npm run compile` builds both.

After changing `partcad` core code, click "Restart PartCAD" in the PartCAD `Context` view. The extension talks
to a warm daemon, which otherwise keeps the old code loaded.

## Testing and linting

```bash
npm run lint            # eslint over src/**/*.ts
npm run format-check    # prettier
npm test                # vscode-test; on Linux: xvfb-run -a npm test
```

`npm test` downloads a VS Code build on first run and needs a display, hence `xvfb-run` on a headless Linux
machine — exactly what `npm-test.yml` does on its Ubuntu leg. `pretest` (compile + lint) runs first
automatically.

`npm run format-check` used to exit 2 however well formatted the tree was: it carried `build/**/*.yml` and
`.github/**/*.yml` over from the extension template this package started as, both resolved against this
directory, which holds neither, and prettier treats a glob matching nothing as an error. It checks
`src/**/*.ts` and nothing else now, in double quotes so that npm on Windows hands the glob to prettier rather
than to `cmd`. Nothing in CI runs it, which is why the dead globs went unnoticed for so long.

The packaging job deliberately does not lint: a check belongs in one workflow, so that one failure has one
place to appear.

`pre-commit` (`dev-tools/pre-commit-config.yaml`) runs `eslint` on changed `.ts` files and has to pass in CI
before a pull request can merge.

## Upgrading dependencies

The npm dependencies of this extension are updated by hand. `.github/dependabot.yml` has an entry for them, but
it is commented out along with everything except `github-actions`; if you enable it, add the labels it names to
the repository first.

To upgrade manually:

1. Create a branch for the dependency updates.
2. Run `npm update` to move the Node.js dependencies to their latest compatible versions.
3. Run `npm ci && npm run vsce-package` and `npm test`, and exercise the extension against a real package —
   the tests do not cover the viewer's rendering or the daemon handshake.
