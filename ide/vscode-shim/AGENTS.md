# ide/vscode-shim

The `OpenVMP.partcad` marketplace entry, as a transition shim. It ships **no code**: one `package.json` whose
only substantive line is an `extensionDependencies` on `PartCAD.partcad-official`.

## Why it exists

The extension in `ide/vscode` used to be published by the `OpenVMP` publisher, so its marketplace identity was
`OpenVMP.partcad`. It is published by `PartCAD` now, which makes it a **different extension** as far as the
marketplace and the editor are concerned. A publisher is part of an extension's identity and there is no
rename: nothing carries an installed `OpenVMP.partcad` over to the new entry, and an abandoned entry keeps
serving the last version it was given, forever, to everyone who already has it.

So the old entry is not abandoned. It is replaced by this, and a user who has it installed gets it as an
ordinary update. The editor resolves `extensionDependencies` at install time, so the update pulls
`PartCAD.partcad-official` in and the window ends up with the real extension running. Nothing is asked of the
user and nothing they configured moves: `partcad.*` settings live in their `settings.json` under keys the new
extension contributes, not in anything the old one owned.

The new entry is `PartCAD.partcad-official` rather than `PartCAD.partcad` because of this package: the
marketplace does not let two publishers share an extension name, and this one holds `partcad`. That is a
consequence of keeping the old entry alive, not a second decision -- the name is the price of the shim, and it
goes away with it.

This is the same shape as `dev-tools/shim/`, which keeps `pip install partcad-cli` working now
that everything ships in one `partcad` wheel, and it is temporary in the same way. Delete it once the installed
base has moved.

## What must stay true of it

* **No `main`, no `contributes`, no `activationEvents`.** Both extensions are installed at once after the
  update, so anything contributed here would be contributed twice -- two `PartCAD` views in the activity bar,
  two handlers registered for one command id. A dependency-only package activates nothing and contributes
  nothing, which is why the user sees one extension rather than two.

* **The identity is the old one, exactly.** `name: partcad` and `publisher: OpenVMP` are what make this an
  update to the entry people have installed rather than a third extension beside it. Changing either one
  publishes something nobody receives. This is also why the real extension is named `partcad-official`: the
  name here is not available to it, and the entry people have installed is the one that must not move.

* **`extensionDependencies`, not `extensionPack`.** A pack is a bookmark: the editor installs its members and
  then lets the user remove them one by one, and removing the member is not removing the pack. A dependency is
  a requirement -- the editor keeps it installed for as long as this is, and uninstalling this releases it.
  That is the relationship wanted here, because this package is worthless without the extension it points at.

* **The version is not its own.** `package.json` says `0.0.0` and always will. The version the `.vsix`
  actually carries is the extension's, read out of `ide/vscode/package.json` at package time and handed to
  `vsce` as an argument -- `--no-update-package-json` keeps it from being written back.

  It has to move with each release, because the marketplace delivers an update only to an installation
  holding something older; a shim frozen behind the entry it replaces is one nobody receives. But *stating*
  it here would be a second literal whose only job is to agree with the first, and this repository has
  already been through that: five distributions each carrying a version and `==` pins on the others, with
  twenty-odd `bumpversion` entries keeping them in step. The entries are how you find out they disagreed,
  not how they stay agreed.

  It is not hypothetical here either. This shim spent its review sitting behind an extension that was
  released three times underneath it, because the bumps ran against a tree that did not yet have the
  `bumpversion` entry -- a build failure per release, none of them about the change under review. Derived,
  the two cannot drift: there is one version, and the shim reads it.

* **No icon**, on purpose rather than for want of one. The default placeholder does something useful in the
  "Installed" list: "PartCAD (moved)" with no logo reads as the stub it is, beside the real "PartCAD" with
  the logo. (This used to say the icon was unavailable because it is a git-lfs object. It no longer is --
  `.gitattributes` names `logo_128x128.png` as the one `.png` outside lfs, because `vsce` was packaging the
  pointer file into the real extension -- so the reason above is now the only one, and it is the one that
  was always doing the work.)

## Build

```bash
npm run vsce-package   # writes partcad-shim.vsix
```

`.github/workflows/vsix.yml` runs exactly this beside the real extension's build and uploads both to the same
artifact. There is no `npm ci` step, no `node_modules` and no lockfile, in CI or here: nothing is compiled and
nothing is bundled, so the script reaches `vsce` through `npx` at a pinned version rather than declaring a
dependency that would need a node project to install it. Run it from this directory -- it reads the version
out of `../vscode/package.json`.

**Publish `PartCAD.partcad-official` before this.** The editor fails an install whose `extensionDependencies`
cannot be resolved, so releasing this against a publisher that has nothing under it yet would break the very
installations it is meant to carry over.

That order is no longer only written down here: `deploy.yml`'s `publish-vscode-extension` job publishes the two
packages to the galleries after a release, extension first, and stops without touching the shim if the
extension did not go. Publishing by hand still has to obey the rule; the release path now cannot get it wrong.
