# Original code taken from https://gist.github.com/SDI8/3137ee70649e4901913c7c8e6b534ec8

"""
MIT License
Copyright (c) 2022 Simon Dibbern
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

# Also influenced by https://github.com/gumyr/build123d/blob/dev/src/build123d/persistence.py

"""
build123d pickle support

name: persistence.py
by:   Jojain & bernhard-42
date: September 8th, 2023

desc:
    This python module enables build123d objects to be pickled.

license:

    Copyright 2023 Jojain & bernhard-42

    Licensed under the Apache License, Version 2.0 (the "License");
    you may not use this file except in compliance with the License.
    You may obtain a copy of the License at

        http://www.apache.org/licenses/LICENSE-2.0

    Unless required by applicable law or agreed to in writing, software
    distributed under the License is distributed on an "AS IS" BASIS,
    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
    See the License for the specific language governing permissions and
    limitations under the License.

"""

# NOTE: this module used to install 'copyreg' handlers ('register()', with the
# '_reduce_*'/'_inflate_*' pairs) so that OCCT objects could be pickled, because
# the wrapper protocol was a pickle envelope. The protocol is now a plain JSON
# envelope with explicit BREP markers - see 'ocp_wire' - so that pickle support
# has been retired: no global 'copyreg' state is registered any more, and no
# OCP-aware unpickling machinery is reachable from the protocol.
#
# What remains here are 'shapetype()' and 'downcast()', which are ordinary
# utilities unrelated to serialization. They deliberately stay at this import
# path so that existing importers keep working; 'ocp_wire' re-exports them.

from typing import Any

import OCP


downcast_LUT = {
    OCP.TopAbs.TopAbs_VERTEX: OCP.TopoDS.TopoDS.Vertex_s,
    OCP.TopAbs.TopAbs_EDGE: OCP.TopoDS.TopoDS.Edge_s,
    OCP.TopAbs.TopAbs_WIRE: OCP.TopoDS.TopoDS.Wire_s,
    OCP.TopAbs.TopAbs_FACE: OCP.TopoDS.TopoDS.Face_s,
    OCP.TopAbs.TopAbs_SHELL: OCP.TopoDS.TopoDS.Shell_s,
    OCP.TopAbs.TopAbs_SOLID: OCP.TopoDS.TopoDS.Solid_s,
    OCP.TopAbs.TopAbs_COMPOUND: OCP.TopoDS.TopoDS.Compound_s,
    OCP.TopAbs.TopAbs_COMPSOLID: OCP.TopoDS.TopoDS.CompSolid_s,
}


def shapetype(obj: OCP.TopoDS.TopoDS_Shape) -> OCP.TopAbs.TopAbs_ShapeEnum:
    """Return TopoDS_Shape's TopAbs_ShapeEnum"""
    if obj.IsNull():
        raise ValueError("Null TopoDS_Shape object")

    return obj.ShapeType()


def downcast(obj: OCP.TopoDS.TopoDS_Shape) -> OCP.TopoDS.TopoDS_Shape:
    """Downcasts a TopoDS object to suitable specialized type

    Args:
      obj: TopoDS_Shape:

    Returns:

    """

    f_downcast: Any = downcast_LUT[shapetype(obj)]
    return_value = f_downcast(obj)

    return return_value
