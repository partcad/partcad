# The PartCAD IDE

The PartCAD extension is a good way to work with PartCAD once Visual Studio Code, a Python environment, a CAD
sandbox and half a dozen extensions are in place. This directory removes that sentence: it builds an
application a user downloads and opens, with all of it inside, and with the PartCAD workbench on screen the
first time it starts.

|                       | wheels                       | standalone command line tools | PartCAD IDE                     |
| --------------------- | ---------------------------- | ----------------------------- | ------------------------------- |
| Install               | `pip install -U partcad-cli` | `install.sh`                  | `install.sh --ide`, or a .dmg   |
| Needs Python          | yes, 3.10-3.14               | no                            | no                              |
| Needs an editor       | -                            | -                             | no, it is one                   |
| What you get          | `pc`, `partcad`, the library | `pc`, `partcad`               | the editor, the extension, `pc` |
| Size (Linux, unpacked)| ~15MB plus dependencies      | ~875MB                        | ~1.2GB                          |

It is built from [VSCodium](https://vscodium.com/), rebranded, with the extensions this repository recommends
installed into it and the [standalone command line tools](../dev-tools/pyinstaller/README.md) inside it. The
result is one archive per platform, published on the same GitHub release as everything else.

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
- `bootstrap/` - a small extension that ships only in this IDE: it opens the PartCAD workbench on startup and
  points the PartCAD extension at the tools in the same application.
- `tools/` - the parts of the build that are more than a shell one-liner, each with its own tests.
- `tests/` - `pytest` tests for `tools/`.

## Building

From the repository root, with Node.js and Python available:

```bash
partcad-ide-standalone/build.sh
```

That produces `dist/ide/` with the application and its archive. Add the command line tools -- the IDE is
usable without them, but then it downloads them on first use, which is the friction this component exists to
remove:

```bash
dev-tools/pyinstaller/build.sh --no-archive          # produces dist/standalone/partcad
partcad-ide-standalone/build.sh --with-cli-bundle dist/standalone/partcad
```

Useful while iterating: `--no-extensions` (much faster, and not shippable), `--no-archive`, `--no-icons`.
`--help` lists them all. The VSCodium download is cached in `build/vscodium/`, so a rebuild does not fetch it
again.

Two optional dependencies change what the build can do, and it reports what it left out rather than failing:

- `cairosvg` and `Pillow` (`pip install cairosvg pillow`) render the icons from the project's logo. Without
  them the application keeps VSCodium's icon.
- `rcedit` (`npm install -g rcedit`) puts the icon into `partcad-ide.exe`. There is no other way to change a
  Windows executable's icon after it is linked.

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

Both behaviors have a setting (`partcadIde.openWorkbenchOnStartup`, `partcadIde.useBundledTools`), and both
notice when they have nothing to work with: in an editor without the PartCAD extension, or without tools next
to the application, the extension does nothing rather than failing.

It is a separate extension rather than a few lines in `partcad-ide-vscode` on purpose. The PartCAD extension
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

## Windows: no installer

The Windows artifact is a `.zip` to unpack, not a setup program: `partcad-ide.exe` runs from wherever it lands.
There is no Start menu entry, no file association and no uninstaller. Producing those means driving Inno Setup
the way the upstream VS Code build does, which is more than a rebranding step and has not been done.

## Updating VSCodium

`vscodium.json` pins the release. To move to a newer one:

```bash
partcad-ide-standalone/build.sh --vscodium-version <tag> --record
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
