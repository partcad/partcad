// A library-style OpenSCAD file: it only *defines* a module and renders
// nothing on its own. PartCAD appends a call to `box(...)` (see `method` and
// `parameters` in partcad.yaml) so the module can be instantiated.
module box(width, depth, height) {
    cube([width, depth, height]);
}
