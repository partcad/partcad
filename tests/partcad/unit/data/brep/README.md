# BREP fixtures

What `test_brep_inspect.py` reads. Each file is the output of
`BRepTools::Write` on a shape built with OCCT — real bytes from the writer
`partcad.brep_inspect` is written against, rather than BREP text written by
hand, so the test is a test of the format and not of somebody's idea of it.

They are checked in rather than generated because the test must run with no CAD
kernel installed. That is the property under test: the core answers a question
about a shape's topology off the payload it already holds, without OCP and
without a sandbox. A test that built its own fixtures would need the very
dependency the module exists to avoid.

| file | the shape | what it is for |
| --- | --- | --- |
| `solid.brep` | a 10×20×30 box | A solid is bounded by a shell, so this payload *has* a shell record in it and no free shell. The case that would make a naive "does it contain a shell" test fail every part there is. |
| `shell_closed.brep` | that box's shell, alone | The part a script means as a body and hands back as a skin. Closed, so `wrapper_common.solidify` converts it — this is what it looks like when it does not. |
| `shell_open.brep` | one face in a shell | Not closed, so there is no solid it bounds and nothing converts it. What actually reaches the core, and what the `shell` check reports. |
| `face.brep` | one of the box's faces | No shell anywhere: a payload shaped like a sketch. |
| `compound_solid_and_shell.brep` | a cylinder and a shell in one compound | The case that needs the care: two shells, one of them the cylinder's boundary and one free. |
| `compound_two_solids.brep` | two boxes in one compound | Two shells, both somebody's boundary. Free shells are counted, not sensed, and this is where a boolean would get it wrong. |
| `compound_nested_shell.brep` | a box, and a compound holding a shell | The shell is two levels down. |
| `compsolid.brep` | two boxes in a compsolid | A compsolid is made of solids, not of shells, so its references must not be mistaken for shells that bound something. |

Regenerating them means rebuilding the same shapes with OCCT and writing them
again; nothing reads them but the one test, and the test states the topology it
expects of each, so a regenerated fixture that differs is a question to answer
rather than a number to update.
