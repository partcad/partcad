# PartCAD IDE bootstrap

The extension that makes the [PartCAD IDE](../README.md) open into the PartCAD workbench, and that connects it
to the PartCAD command line tools shipped in the same application.

It is built and installed by `../build.sh` and ships only inside that IDE. It is not published to any registry:
in a plain VS Code there are no bundled tools beside the application and no reason to override the user's
layout, and this extension does nothing there.

Two settings turn its two behaviors off: `partcadIde.openWorkbenchOnStartup` and `partcadIde.useBundledTools`.
