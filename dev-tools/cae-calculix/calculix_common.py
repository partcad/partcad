#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The pipeline both CalculiX analyses share: mesh, deck, solve, read, draw.

`fea_calculix.py` and `cfd_calculix.py` differ in the deck they write and the
field they read back out of the results. Everything around that is the same and
lives here:

    the shape  -->  gmsh  -->  nodes and elements
    a port     -->  the nodes within a radius of it  -->  a CalculiX node set
    a deck     -->  ccx   -->  a .frd file
    a field    -->  a colour per node  -->  a binary glTF

Runs inside a PartCAD sandbox, so it may import gmsh, numpy and trimesh, and it
is handed the shape as a live OCCT object (PartCAD decodes the envelope before
the implementation sees it). It may **not** import `partcad`: a sandbox has none.

`ccx` is not a Python package and pip cannot install it. It is looked up on the
PATH, then in the places the common distributions put it; a machine without one
is told so as a sentence naming what to install, because that is a finding about
the machine rather than about the part.
"""

import math
import os
import shutil
import subprocess
import tempfile

# Where to look for the solver, after PATH. The names the distributions use:
# Debian and Ubuntu ship `ccx` in `calculix-ccx`, Homebrew and the CalculiX
# binaries from calculix.de use `ccx_<version>`, and conda-forge uses `ccx`.
CCX_NAMES = ("ccx", "ccx_2.22", "ccx_2.21", "ccx_2.20", "ccx_static")
CCX_DIRECTORIES = ("/usr/bin", "/usr/local/bin", "/opt/homebrew/bin", "/opt/CalculiX/bin")

# The environment variable that overrides all of that, for a machine where the
# solver lives somewhere nobody would guess.
CCX_ENV = "PARTCAD_CCX"

# Millimetres per metre. PartCAD carries geometry in millimetres; CalculiX has no
# units of its own, so a deck is only consistent if everything in it agrees, and
# SI is what the material constants are written in.
MM_PER_M = 1000.0


class SolverMissing(Exception):
    """No CalculiX on this machine, with the sentence that says what to install."""


class SolverFailed(Exception):
    """CalculiX ran and did not produce a result, with what it said."""


def find_ccx():
    """The CalculiX executable, or raise saying how to get one."""
    named = os.environ.get(CCX_ENV)
    if named:
        if os.path.isfile(named) and os.access(named, os.X_OK):
            return named
        raise SolverMissing("%s points at something that is not an executable: %s" % (CCX_ENV, named))

    for name in CCX_NAMES:
        found = shutil.which(name)
        if found:
            return found
    for directory in CCX_DIRECTORIES:
        for name in CCX_NAMES:
            candidate = os.path.join(directory, name)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate

    raise SolverMissing(
        "CalculiX (ccx) is not installed on this machine. Install it with "
        "'apt install calculix-ccx', 'brew install calculix-ccx' or "
        "'conda install -c conda-forge calculix', or point %s at the executable." % CCX_ENV
    )


# --------------------------------------------------------------------------- #
# The mesh                                                                    #
# --------------------------------------------------------------------------- #


class Mesh:
    """A volume mesh of one shape, in millimetres.

    Attributes:
        node_ids: the CalculiX node numbers, in the order `coordinates` holds.
        coordinates: an (n, 3) array of node positions, in millimetres.
        elements: a list of (element id, [node ids]).
        element_type: the CalculiX element keyword the elements are written as.
        extent: the largest dimension of the shape, in millimetres.
    """

    def __init__(self, node_ids, coordinates, elements, element_type, extent):
        self.node_ids = node_ids
        self.coordinates = coordinates
        self.elements = elements
        self.element_type = element_type
        self.extent = extent

    def nodes_near(self, point, radius):
        """The node ids within `radius` millimetres of a point.

        This is how a port becomes a boundary condition. A PartCAD port is a
        coordinate frame rather than a face -- it says where a bolt goes, not
        which surface it clamps -- so what a solver can be told about it is "the
        material around here", and the radius is what "around here" means. It is
        a parameter of the file type (`port_radius`) precisely because the right
        answer depends on the part: a hole pattern in a 200 mm plate and one in a
        10 mm bracket are not the same neighbourhood.
        """
        import numpy as np

        offsets = self.coordinates - np.asarray(point, dtype=float)
        within = np.einsum("ij,ij->i", offsets, offsets) <= float(radius) ** 2
        return [int(self.node_ids[index]) for index in np.flatnonzero(within)]

    def surface_triangles(self):
        """The outward faces of the mesh, as triangles of node indices.

        A tetrahedral volume mesh has no surface of its own: what is drawn is the
        set of faces that exactly one element owns. Built here rather than asked
        of gmsh a second time so that the triangles index the same node array the
        result field does -- a surface meshed separately would have nodes the
        field says nothing about.
        """
        import numpy as np

        index_of = {node: index for index, node in enumerate(self.node_ids)}
        counts = {}
        for _element_id, nodes in self.elements:
            # The four corner nodes of a tetrahedron, whichever order it is
            # written in: a second-order element carries its mid-side nodes after
            # them, and a mid-side node is not a corner of any face.
            corners = nodes[:4]
            for face in (
                (corners[0], corners[2], corners[1]),
                (corners[0], corners[1], corners[3]),
                (corners[1], corners[2], corners[3]),
                (corners[0], corners[3], corners[2]),
            ):
                key = tuple(sorted(face))
                if key in counts:
                    counts[key] = None  # shared, so interior
                else:
                    counts[key] = face

        triangles = [face for face in counts.values() if face is not None]
        return np.array([[index_of[node] for node in face] for face in triangles], dtype=np.int64)


def mesh_shape(shape, size_fraction, order):
    """Mesh a live OCCT shape with gmsh, in millimetres.

    The shape is written to a STEP file and read back rather than handed to gmsh
    in memory: gmsh's OCC kernel is its own build of OpenCASCADE, and two
    OpenCASCADE libraries in one process is how a segfault happens.
    """
    import gmsh
    import numpy as np

    with tempfile.TemporaryDirectory() as work:
        step = os.path.join(work, "shape.step")
        _write_step(shape, step)

        gmsh.initialize()
        try:
            # gmsh prints a great deal, and a sandbox's stdout is the wrapper's
            # channel back to PartCAD: anything written to it is noise in the
            # middle of a serialized response.
            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.option.setNumber("General.Verbosity", 1)
            gmsh.model.add("partcad")
            gmsh.model.occ.importShapes(step)
            gmsh.model.occ.synchronize()

            extent = _extent(gmsh)
            target = max(extent * float(size_fraction), extent / 500.0)
            gmsh.option.setNumber("Mesh.MeshSizeMin", target / 3.0)
            gmsh.option.setNumber("Mesh.MeshSizeMax", target)
            gmsh.option.setNumber("Mesh.ElementOrder", int(order))
            gmsh.model.mesh.generate(3)

            raw_ids, raw_coords, _ = gmsh.model.mesh.getNodes()
            node_ids = np.array(raw_ids, dtype=np.int64)
            coordinates = np.array(raw_coords, dtype=float).reshape(-1, 3)

            element_type, elements = _tetrahedra(gmsh, int(order))
        finally:
            gmsh.finalize()

    if len(elements) == 0:
        raise SolverFailed("gmsh produced no volume elements: the shape may not be a closed solid")
    return Mesh(node_ids, coordinates, elements, element_type, extent)


def _write_step(shape, path):
    """The shape as a STEP file, whichever CAD object PartCAD handed over."""
    # PartCAD decodes an envelope into whatever the sandbox has. Try the
    # libraries in the order of how specific their exporter is; the last is
    # OCP itself, which is always there because the decode used it.
    exporters = (
        lambda: __import__("build123d").export_step(shape, path),
        lambda: __import__("cadquery").exporters.export(shape, path, "STEP"),
    )
    for export in exporters:
        try:
            export()
            if os.path.isfile(path) and os.path.getsize(path) > 0:
                return
        except Exception:
            continue

    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer

    writer = STEPControl_Writer()
    native = getattr(shape, "wrapped", shape)
    writer.Transfer(native, STEPControl_AsIs)
    if writer.Write(path) != IFSelect_RetDone:
        raise SolverFailed("Failed to write the shape out as STEP for meshing")


def _extent(gmsh):
    """The largest dimension of what gmsh has loaded, in millimetres."""
    xmin, ymin, zmin, xmax, ymax, zmax = gmsh.model.getBoundingBox(-1, -1)
    extent = max(xmax - xmin, ymax - ymin, zmax - zmin)
    if not math.isfinite(extent) or extent <= 0:
        raise SolverFailed("The shape has no extent to mesh")
    return extent


def _tetrahedra(gmsh, order):
    """The volume elements, as (CalculiX keyword, [(id, [nodes])])."""
    # gmsh element type 4 is the 4-node tetrahedron, 11 the 10-node one.
    gmsh_type, per_element, keyword = (11, 10, "C3D10") if order >= 2 else (4, 4, "C3D4")
    types, tags, node_tags = gmsh.model.mesh.getElements(3)
    elements = []
    for kind, ids, nodes in zip(types, tags, node_tags):
        if kind != gmsh_type:
            continue
        for index, element_id in enumerate(ids):
            start = index * per_element
            elements.append((int(element_id), [int(n) for n in nodes[start : start + per_element]]))
    return keyword, elements


# --------------------------------------------------------------------------- #
# The deck                                                                    #
# --------------------------------------------------------------------------- #


def deck_mesh(mesh):
    """The `*NODE` and `*ELEMENT` blocks, which every deck begins with.

    Written in metres, because the material constants are in SI and CalculiX has
    no units of its own: a deck is only consistent if everything in it agrees.
    """
    lines = ["*NODE, NSET=NALL"]
    for node_id, (x, y, z) in zip(mesh.node_ids, mesh.coordinates):
        lines.append("%d, %.9g, %.9g, %.9g" % (int(node_id), x / MM_PER_M, y / MM_PER_M, z / MM_PER_M))
    lines.append("*ELEMENT, TYPE=%s, ELSET=EALL" % mesh.element_type)
    for element_id, nodes in mesh.elements:
        lines.append("%d, %s" % (element_id, ", ".join(str(node) for node in nodes)))
    return lines


def deck_nset(name, node_ids):
    """One `*NSET`, wrapped at CalculiX's 16-entries-per-line limit."""
    lines = ["*NSET, NSET=%s" % name]
    for start in range(0, len(node_ids), 16):
        lines.append(", ".join(str(node) for node in node_ids[start : start + 16]))
    return lines


def port_node_sets(mesh, boundary, radius_fraction):
    """A node set per boundary condition, and the ones that reached no material.

    `boundary` is what PartCAD resolved: one record per port a `fix:` or a
    `load:` named, carrying where the port is and what was asked of it. Returns
    `(sets, empty)`, where `sets` is a list of
    `(name, node ids, record)` and `empty` names the records whose neighbourhood
    held no mesh node -- a port floating clear of the material, which is a
    finding about the part rather than a failure of the solver.
    """
    radius = mesh.extent * float(radius_fraction)
    sets = []
    empty = []
    for index, record in enumerate(boundary):
        location = record.get("location") or [[0, 0, 0], [0, 0, 1], 0]
        point = location[0]
        nodes = mesh.nodes_near(point, radius)
        if not nodes:
            empty.append(record)
            continue
        sets.append(("PORT%d" % index, nodes, record))
    return sets, empty


def run_ccx(lines, work, name="job"):
    """Write a deck, run CalculiX on it, and hand back the path of the `.frd`.

    CalculiX is run with the job name and no extension, which is what it expects,
    and from the working directory, because it writes its output beside the
    input whatever it was given.
    """
    ccx = find_ccx()
    deck = os.path.join(work, name + ".inp")
    with open(deck, "w") as f:
        f.write("\n".join(lines) + "\n")

    try:
        completed = subprocess.run(
            [ccx, name],
            cwd=work,
            capture_output=True,
            text=True,
            timeout=3600,
        )
    except subprocess.TimeoutExpired as e:
        raise SolverFailed("CalculiX did not finish within an hour") from e

    results = os.path.join(work, name + ".frd")
    if not os.path.isfile(results) or os.path.getsize(results) == 0:
        # ccx reports a diverged or ill-posed problem on stdout and exits 0, so
        # the exit status is not what says whether there is an answer.
        detail = (completed.stdout or "").strip().splitlines()
        tail = "\n".join(detail[-12:]) if detail else (completed.stderr or "").strip()
        raise SolverFailed("CalculiX produced no results:\n%s" % (tail or "it said nothing"))
    return results


# --------------------------------------------------------------------------- #
# The results                                                                 #
# --------------------------------------------------------------------------- #


def read_frd(path, blocks):
    """Read named result blocks out of a CalculiX `.frd` file.

    `blocks` maps the block name CalculiX writes (`DISP`, `STRESS`, `VELO`, ...)
    to how many components of it to keep. Returns `{block: {node id: [values]}}`,
    holding the **last** step in the file, which for a transient run is the one
    the solution was marched to.

    The `.frd` format is fixed-column ASCII and is documented in the CalculiX
    manual. Only what is needed is parsed: a `-4` line opens a block and names
    it, `-5` lines name its components, `-1` lines carry one node's values, and
    `-3` closes it.
    """
    wanted = {name.upper(): count for name, count in blocks.items()}
    results = {name: {} for name in wanted}
    current = None
    components = 0

    with open(path, "r", errors="replace") as f:
        for line in f:
            key = line[:5].strip()
            if key == "-4":
                name = line[5:18].strip().upper()
                if name in wanted:
                    current = name
                    components = wanted[name]
                    # A block repeated for a later step replaces the earlier one.
                    results[current] = {}
                else:
                    current = None
                continue
            if key == "-3":
                current = None
                continue
            if key != "-1" or current is None:
                continue

            node = int(line[5:15])
            values = []
            for index in range(components):
                start = 15 + index * 12
                text = line[start : start + 12].strip()
                if not text:
                    break
                values.append(float(text))
            if values:
                results[current][node] = values
    return results


def von_mises(components):
    """The von Mises equivalent of one CalculiX stress tensor.

    CalculiX writes the six independent components in the order
    SXX, SYY, SZZ, SXY, SYZ, SZX.
    """
    sxx, syy, szz, sxy, syz, szx = (list(components) + [0.0] * 6)[:6]
    return math.sqrt(0.5 * ((sxx - syy) ** 2 + (syy - szz) ** 2 + (szz - sxx) ** 2) + 3.0 * (sxy**2 + syz**2 + szx**2))


# The colour ramp the result model is painted with: blue where the field is
# lowest through to red where it is highest. Written out rather than taken from a
# plotting library because a sandbox that has to install matplotlib to colour a
# hundred triangles is a sandbox nobody waits for.
_RAMP = (
    (0.23, 0.30, 0.75),
    (0.30, 0.65, 0.90),
    (0.45, 0.85, 0.55),
    (0.98, 0.85, 0.25),
    (0.90, 0.35, 0.15),
)


def colours_for(values, low=None, high=None):
    """A colour per value, low to high, as an (n, 4) array of bytes."""
    import numpy as np

    values = np.asarray(values, dtype=float)
    low = float(np.nanmin(values)) if low is None else float(low)
    high = float(np.nanmax(values)) if high is None else float(high)
    if not math.isfinite(low) or not math.isfinite(high) or high <= low:
        # A uniform field: every point the same colour rather than a divide by
        # zero. This is what an unloaded part looks like, and it is a legitimate
        # answer.
        fractions = np.zeros_like(values)
    else:
        fractions = np.clip((values - low) / (high - low), 0.0, 1.0)

    ramp = np.array(_RAMP, dtype=float)
    positions = fractions * (len(ramp) - 1)
    lower = np.floor(positions).astype(int)
    upper = np.clip(lower + 1, 0, len(ramp) - 1)
    weight = (positions - lower)[:, None]
    rgb = ramp[lower] * (1.0 - weight) + ramp[upper] * weight

    colours = np.ones((len(values), 4), dtype=np.uint8) * 255
    colours[:, :3] = np.clip(rgb * 255.0, 0, 255).astype(np.uint8)
    return colours


def write_glb(path, coordinates, triangles, values, low=None, high=None):
    """The result surface as a binary glTF, coloured by the field.

    Metres and Y-up, which is what glTF is and what the PartCAD Viewer expects of
    anything it draws: the conversion from PartCAD's millimetre, Z-up geometry
    happens here because this is the last place that knows which it is.
    """
    import numpy as np
    import trimesh

    vertices = np.asarray(coordinates, dtype=float) / MM_PER_M
    # Z-up to Y-up: (x, y, z) -> (x, z, -y). The same rotation build123d's glTF
    # exporter bakes into the node transform of everything else PartCAD shows.
    vertices = np.column_stack((vertices[:, 0], vertices[:, 2], -vertices[:, 1]))

    mesh = trimesh.Trimesh(
        vertices=vertices,
        faces=np.asarray(triangles, dtype=np.int64),
        vertex_colors=colours_for(values, low, high),
        process=False,
    )
    with open(path, "wb") as f:
        f.write(trimesh.exchange.gltf.export_glb(trimesh.Scene(mesh)))


def field_per_node(mesh, per_node, default=0.0):
    """One value per node of the mesh, in the order the coordinates are in."""
    import numpy as np

    return np.array([per_node.get(int(node), default) for node in mesh.node_ids], dtype=float)


def failed(exception):
    """The answer PartCAD's meta-wrapper expects when nothing was produced."""
    return {"success": False, "exception": str(exception)}
