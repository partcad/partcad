# PartCAD IDE bootstrap

The extension that makes the [PartCAD IDE](../README.md) an IDE for PartCAD rather than an editor with an
extension in it: it opens the PartCAD workbench, connects the IDE to the PartCAD command line tools shipped in
the same application, and -- the first time it starts -- creates a package for the user and opens it, with the
welcome window beside it.

The welcome window is the walkthrough contributed by `package.json`; the text of its steps is in `media/`.
"The first start, and the welcome window" in `../README.md` explains what happens in which order, and why the
package is created here rather than by the installers.

It is built and installed by `../build.sh` and ships only inside that IDE. It is not published to any registry:
in a plain VS Code there are no bundled tools beside the application and no reason to override the user's
layout, and this extension does nothing there.

Three settings turn its three behaviors off: `partcadIde.openWorkbenchOnStartup`, `partcadIde.useBundledTools`
and `partcadIde.createStarterPackage`. Two commands reach the first start afterwards:
`PartCAD IDE: Open the starter package` and `PartCAD IDE: Welcome`.

Plain JavaScript, packaged as it is -- there is no compile step, so keep it that way.
