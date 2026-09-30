# The extension test suite's workspace

`.vscode-test.js` opens this directory as the workspace folder of the VS Code
window the tests run in. It exists because the tests need *a* workspace: the
extension reports "No workspace folders found" and stops before it starts a
backend without one, so a window opened on nothing exercises almost none of it.

It is deliberately empty of PartCAD content. There is no `partcad.yaml` here,
because that would activate the extension through `workspaceContains` before a
test has said to -- and what the first test asserts is that activating it works.
