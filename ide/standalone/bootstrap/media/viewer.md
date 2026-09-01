## The PartCAD Viewer

Select a part in the PartCAD Explorer and it appears in the viewer: the shape
the script produced, not a preview of the text.

The shape is built by PartCAD rather than by the editor, in a sandbox it makes
for the CAD kernel the part needs. The first build of a part downloads that
sandbox, so it takes a while; the ones after it do not.

Save the script and the viewer follows.

The 3D view needs WebGL. This IDE turns on the software renderer, so it works
on a machine with no usable GPU driver -- a virtual machine, a remote desktop,
a container -- rather than showing an empty canvas.
