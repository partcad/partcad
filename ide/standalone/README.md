# The PartCAD IDE

The PartCAD extension is a good way to work with PartCAD once Visual Studio Code, a Python environment, a CAD
sandbox and half a dozen extensions are in place. This directory removes that sentence: it builds an
application a user downloads and opens, with all of it inside, and with the PartCAD workbench on screen the
first time it starts.

|                       | wheels                       | standalone command line tools | PartCAD IDE                     |
| --------------------- | ---------------------------- | ----------------------------- | ------------------------------- |
| Install               | `pip install -U partcad`     | `install.sh`                  | `install.sh --ide`, or a .dmg   |
| Needs Python          | yes, 3.10-3.14               | no                            | no                              |
| Needs an editor       | -                            | -                             | no, it is one                   |
| What you get          | `pc`, `partcad`, the library | `pc`, `partcad`               | the editor, the extension, `pc` |
| Size (Linux, unpacked)| ~15MB plus dependencies      | ~875MB                        | ~1.2GB                          |

It is built from [VSCodium](https://vscodium.com/), rebranded, with the extensions this repository recommends
installed into it and the [standalone command line tools](../dev-tools/pyinstaller/README.md) inside it. The
result per platform -- an archive everywhere, a `.dmg` on MacOS, a setup program on Windows -- is published on
the same GitHub release as everything else.

## Licensing

**The editor is VSCodium, not Visual Studio Code.** Visual Studio Code's source is MIT, but the builds
Microsoft ships are not: they are covered by a proprietary license that does not permit redistributing a
modified copy, and the Visual Studio Marketplace's terms restrict its use to Microsoft's own products.
Rebranding those binaries and pointing them at a marketplace would violate both. VSCodium is a build of the
same MIT source with the Microsoft branding, telemetry and marketplace configuration removed, published under
the MIT license, and redistributing a modified copy of it is exactly what the license allows. The gallery it
comes configured with is [Open VSX](https://open-vsx.org/), and `product.overlay.json` deliberately leaves that
setting alone.

The same question applies to every extension the IDE carries, which is why they are not simply installed from a
list: see [`extensions.json`](./extensions.json). One of the repository's recommendations, Pylance, cannot ship
at all -- it is proprietary and licensed for use only with Microsoft's products -- and the build says so rather
than dropping it quietly.

## Files

- `build.sh` - the build. Downloads VSCodium, installs the extensions, rebrands, embeds the tools, packs.
- `vscodium.json` - which VSCodium release to build from, and its checksum.
- `extensions.json` - what to do about recommendations that cannot simply be installed. The list itself is
  `../.vscode/extensions.json`.
- `product.overlay.json` - the branding, merged into the editor's `product.json`.
- `installer/partcad-ide.iss` - the Windows installer, compiled by Inno Setup.
- `bootstrap/` - a small extension that ships only in this IDE: it opens the PartCAD workbench on startup and
  points the PartCAD extension at the tools in the same application.
- `tools/` - the parts of the build that are more than a shell one-liner, each with its own tests.
- `tests/` - `pytest` tests for `tools/`.

## Building

From the repository root, with Node.js and Python available:

```bash
ide/standalone/build.sh
```

That produces `dist/ide/` with the application and its archive. Add the command line tools -- the IDE is
usable without them, but then it downloads them on first use, which is the friction this component exists to
remove:

```bash
dev-tools/pyinstaller/build.sh --no-archive          # produces dist/standalone/partcad
ide/standalone/build.sh --with-cli-bundle dist/standalone/partcad
```

Useful while iterating: `--no-extensions` (much faster, and not shippable), `--no-archive`, `--no-icons`,
`--no-installer`. `--help` lists them all. The VSCodium download is cached in `build/vscodium/`, so a rebuild does not fetch it
again. Everything else the build produces for itself -- the extension plan, the staging directories, the rendered icons -- goes
to `build/ide-work/`, and only `build/ide/` becomes the application: on Linux and Windows the VSCodium archive unpacks flat, so
anything written beside it would be shipped inside the release.

With no `version` in `vscodium.json` the build asks the GitHub API which VSCodium released last, and an anonymous API call is
rate limited per source IP -- on a shared address that is a `403` before anything is downloaded. Set `GITHUB_TOKEN` (or
`GH_TOKEN`) to be counted against an account instead, or pin a version, which is worth doing anyway: a pinned build produces the
same IDE next month as it does today.

Two optional dependencies change what the build can do, and it reports what it left out rather than failing:

- `cairosvg` and `Pillow` (`pip install cairosvg pillow`) render the icons from the project's logo. Without
  them the application keeps VSCodium's icon.
- `rcedit` (`npm install -g rcedit`) puts the icon into `partcad-ide.exe`. There is no other way to change a
  Windows executable's icon after it is linked.
- Inno Setup 6.3 or newer (`choco install innosetup`) compiles the Windows installer. Without it the build
  produces the `.zip` only.

## What the build does to VSCodium, and why

**`product.json` is rebranded** (`tools/brand.py product` with `product.overlay.json`). Names, the data folder,
the URL scheme, where "Help" points. Two entries are worth calling out: `updateUrl` is *removed*, because
VSCodium's update server serves VSCodium and installing that over this application would replace everything
this build added; and `configurationDefaults` sets the defaults the IDE starts from -- including
`partcad.backend`, so the extension uses the service rather than looking for a Python environment. They are
defaults, so a user's own `settings.json` still wins.

**The extensions are installed by the editor itself**, into the application's own extensions directory. The
build runs the VSCodium command line with a staging directory (`--install-extension`), and then moves the
result inside the application. It does not write that directory itself: the editor resolves each extension
against the gallery, picks the build for this platform and writes the layout it expects to read back.

They go into the *application's* extensions directory rather than the user's for two reasons. On MacOS a user
installs by dragging the bundle to /Applications, and anything that was beside the bundle is left behind. And
on any platform, a PartCAD IDE that installed extensions into `~/.vscode` would be editing the state of a
Visual Studio Code on the same machine. The cost is that these extensions cannot be uninstalled, only
disabled -- and that a user who installs a newer version of one from the Extensions view gets that newer
version, which is the behavior anyone would expect.

Nothing shipped this way updates itself: a built-in extension is not checked against the gallery. For most of
them that only means a user updates them by hand if they want to. For the PartCAD extension it is the intended
behavior -- it is versioned with the IDE, and a new one arrives with a new IDE.

**The executable is renamed** to `partcad-ide`, so that the process, the window and the task bar say what this
is. The `bin/` launcher names the executable it runs, so it is rewritten to match (`tools/brand.py shim`);
that rewrite replaces whole words only, or a data directory like `.vscodium` would be renamed along with it.
On MacOS nothing is renamed inside the bundle -- the launcher finds the executable through the bundle, and it
is the bundle directory that becomes `PartCAD IDE.app`.

**The command line tools are embedded** at `<resources>/partcad-cli`, beside `<resources>/app` rather than
inside it, so that no extension scan walks a gigabyte of Python. The bootstrap extension finds them there
relative to `appRoot`, which is the same relative path on all three platforms.

**The result is checked** (`tools/verify_bundle.py`): branding applied, every required extension present, no
extension present that the policy skips, the tools where they should be, the launcher runnable. Each of those
failures produces an application that starts and looks right, so none of them would be noticed before a user
hit it.

## Starting in the PartCAD workbench

`bootstrap/` is an extension that exists only in this IDE. On startup it runs
`workbench.view.extension.partcad-container` -- the command the editor derives from the view container the
PartCAD extension contributes -- so the IDE opens on the PartCAD Explorer rather than on an empty editor. It
also points `partcad.servicePath` at the bundled `partcad-json-rpc` and prepends the tools directory to the
PATH of the integrated terminal, so `pc` works in it without the user installing anything.

The PartCAD extension does the PATH half for itself now too (`partcad.addToolsToTerminalPath`, see
`ide/vscode/AGENTS.md`), so inside this IDE both run. They agree on the directory -- the extension
resolves `partcad.servicePath`, which `bootstrap` has just pointed at the bundled service -- so the only effect
is that it appears on `PATH` twice. This part of `bootstrap` stays because it is what sets `servicePath` in the
first place, and because it has to work in an editor where the PartCAD extension is disabled.

The IDE's other view of PartCAD comes from the package rather than from here: `pc init` adds a **Render**
command to the repository's `.vscode/launch.json` (see `src/partcad/launch_config.py`), so "Run and
Debug" has something in it that renders the package the moment there is a package to render.

Both behaviors have a setting (`partcadIde.openWorkbenchOnStartup`, `partcadIde.useBundledTools`), and both
notice when they have nothing to work with: in an editor without the PartCAD extension, or without tools next
to the application, the extension does nothing rather than failing.

It is a separate extension rather than a few lines in `ide/vscode` on purpose. The PartCAD extension
activates when a workspace looks like a PartCAD project; making it activate on startup, everywhere, to check
whether it is running inside this IDE would slow down every other Visual Studio Code that has it installed.

## Where things end up on the user's machine

| | Linux | MacOS | Windows |
| --- | --- | --- | --- |
| The application | `~/.local/share/partcad/<version>-ide` | `/Applications/PartCAD IDE.app` | wherever the .zip was unpacked |
| Settings, state, extensions the user installs | `~/.partcad-ide` | `~/.partcad-ide` | `%USERPROFILE%\.partcad-ide` |
| PartCAD's own cache and configuration | `~/.partcad` | `~/.partcad` | `%USERPROFILE%\.partcad` |

`~/.partcad-ide` is what keeps this IDE from sharing anything with a Visual Studio Code or VSCodium on the same
machine. `~/.partcad` is deliberately shared: it is PartCAD's, not the editor's, and a package installed from
the command line should be there in the IDE.

## MacOS: signing

Editing files inside a signed application bundle invalidates its signature, and MacOS refuses to open a bundle
whose signature does not verify. The build signs the result ad-hoc (`codesign --sign -`), which makes it
launchable. It is not a Developer ID signature and the application is not notarized, so MacOS still refuses a
copy that carries the "downloaded from the internet" flag. `install.sh --ide` clears that flag on the copy it
installs; someone who unpacks the archive by hand clears it with:

```bash
xattr -dr com.apple.quarantine "/Applications/PartCAD IDE.app"
```

Signing and notarizing properly needs an Apple Developer ID, which is an account and a certificate rather than
a change to this build. When there is one, sign with it here instead of ad-hoc and the step above disappears.

## Windows: the installer

Windows has no `install.sh`, so `installer/partcad-ide.iss` is the equivalent: an
[Inno Setup](https://jrsoftware.org/isinfo.php) script, compiled by `build.sh` into
`partcad-ide-<version>-windows-x86_64-setup.exe` whenever `ISCC.exe` is on the machine (`choco install
innosetup`; the build says so and carries on when it is not). It needs Inno Setup 6.3 or newer, for the
`x64compatible` architecture identifiers.

It installs **per user** by default -- into `%LOCALAPPDATA%\Programs\PartCAD IDE`, with no UAC prompt -- and
offers "for all users" in the wizard for someone with an administrator account. That choice is what the `HKA`
registry root in the script follows: the same entries land in `HKCU` or in `HKLM` depending on which install it
is. What it sets up beyond the files: a Start menu entry, an optional desktop icon, the `partcad-ide://` URL
scheme, an App Paths entry so `partcad-ide` works from the Run dialog, optional "Open with PartCAD IDE" entries
in the Explorer context menu for files and folders, and -- on by default -- `PATH` entries for the editor's
`bin` and for the command line tools inside the application, so `partcad-ide` and `pc` work in a new terminal.
Uninstalling removes all of it, including the `PATH` entries. `%USERPROFILE%\.partcad-ide` is left alone, the
way `install.sh` leaves `~/.partcad`.

`AppId` in the script is the identity Windows recognizes an upgrade and an uninstall by. It is fixed for the
life of the product: regenerating it turns the next release into a second application installed beside this
one.

The `.zip` is still published next to the installer, for unpacking without installing.

The installer is **not signed**. SmartScreen warns about an unsigned installer from an unknown publisher, and
the way past that is an authenticode certificate, not a change here. `Compression` is set to `lzma2/fast`
rather than `max` on purpose: the payload is around a gigabyte, and the difference is minutes of build time
against a fraction of the download.

## Updating VSCodium

`vscodium.json` pins the release. To move to a newer one:

```bash
ide/standalone/build.sh --vscodium-version <tag> --record
```

`--record` writes the version and the checksum of what it downloaded into `vscodium.json` -- as plain JSON,
without the comments that explain the file, so put those back before committing. Then check the two things a
VSCodium release can break: that the extensions still install (the build fails if a required one does not), and
that the launcher was still rewritten (the build runs `--version` through it and fails if it does not run).

With `version` left as `null`, the build takes whatever VSCodium released last. That is convenient and not
reproducible: a rebuild of an old PartCAD version then produces a different IDE. Pin it before a release.

## Adding an extension

Add it to `../.vscode/extensions.json`. That file is the source of truth, so a contributor's recommendation and
the IDE's contents cannot drift apart, and nothing else needs editing -- unless the extension is not on Open
VSX, or cannot be redistributed, in which case `extensions.json` here says what to do about it and why. The
build prints the whole plan before it installs anything; `tools/resolve_extensions.py --explain` prints it
without building.

## Releasing

`.github/workflows/build-ide-standalone.yml` builds every platform and then installs the result with
`install.sh --ide` on a runner that has never seen PartCAD. `deploy.yml` calls it on a push to `main` and
uploads the archives to the same GitHub release as the wheels and the command line bundles, which is where
`install.sh --ide` downloads from.

It does not build the command line bundles it embeds. `deploy.yml` builds them once, in the same run, and the
IDE build downloads them from there; on every other trigger the IDE build finds the sibling `Standalone`
workflow run for the same commit and downloads them from that run instead. Building them here as well would
mean freezing every platform twice for one commit -- and the `bundles` job in that workflow explains what else
it meant. When no `Standalone` run exists for the commit (a change confined to `ide/standalone/**`
fires the IDE workflow and not that one) the build falls back to the newest bundles on the base branch and says
so, loudly, in the log and the run summary.
