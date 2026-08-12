#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Core-side entry point for 'pc convert assembly'.

Converts an assembly between the two formats that can express one:

  * **to URDF** - the assembly is exported as a ``.urdf`` file plus a directory
    of the STL files it references, one per distinct shape in it, and the
    package's declaration switches to ``type: urdf``.

  * **to ASSY** - every URDF link becomes an ``stl`` part of the package and
    every URDF joint becomes a pair of PartCAD interfaces, so the resulting
    ``.assy`` places its parts with ``connect:`` rather than with hard-coded
    coordinates. The package's declaration switches to ``type: assy``.

The second direction is where the two models actually have to be reconciled, and
the mapping is described in docs/source/simulation.rst. In short: a URDF joint
relates two link frames, while PartCAD relates two *ports* that face each other,
so each joint becomes a "socket" interface the parent implements at the joint
origin and a "plug" interface the child implements at its own origin. Joints
that say the same thing share one pair of interfaces.
"""

import asyncio
import math
from pathlib import Path

import ruamel.yaml
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from ... import logging as pc_logging
from ...assembly import Assembly, AssemblyChild
from ...geom import Location
from ...project import Project
from ...utils import resolve_resource_path

SUPPORTED_FORMATS = ("assy", "urdf")

# PartCAD connects two ports by turning one to face the other; a URDF joint
# instead has the two link frames coincide. The flip that reconciles them is
# this half turn, and it is what the generated "plug" interface carries. See
# 'joint_axis_in_port_frame' for the one other place it shows up.
FACING = [[0.0, 0.0, 0.0], [0.71, 0.71, 0.0], 180.0]

# What a joint's freedom of movement becomes as a PartCAD interface parameter.
# 'turn' is degrees about an axis, 'move' is millimetres along one.
JOINT_PARAMETERS = {
    "revolute": ("angle", "turn", math.degrees),
    "continuous": ("angle", "turn", math.degrees),
    "prismatic": ("offset", "move", lambda v: v * 1000.0),
}

# How far a continuous joint is allowed to turn in the generated parameter.
# URDF says "no limit"; a PartCAD parameter has to name a range, and a full turn
# either way is the honest reading of one.
CONTINUOUS_RANGE = 360.0


def _yaml():
    yaml = ruamel.yaml.YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)
    return yaml


def _flow(values):
    """A list rendered inline, so a location stays on one line."""
    seq = CommentedSeq(values)
    seq.fa.set_flow_style()
    return seq


def _location(packed):
    return _flow([_flow(packed[0]), _flow(packed[1]), packed[2]])


def is_identity(packed):
    """Whether a packed location is a no-op, within rounding noise."""
    translation, _, angle = Location(packed).as_packed()
    return all(abs(v) < 1e-9 for v in translation) and abs(angle) < 1e-9


def joint_axis_in_port_frame(axis):
    """A URDF joint axis, expressed in the frame the connection works in.

    The generated plug carries a half turn about (1, 1, 0) so that the two ports
    face each other the way PartCAD expects. A rotation conjugated by that half
    turn is the same rotation about the mapped axis, and the map is
    (x, y, z) -> (y, x, -z). Stating the axis that way is what makes
    ``connect: {toParams: {angle: 30}}`` turn the joint by exactly 30 degrees in
    the URDF sense.
    """
    return [float(axis[1]), float(axis[0]), -float(axis[2])]


def joint_signature(joint):
    """What makes two joints the same connection, and so share one interface."""
    return repr(
        [
            joint.get("type"),
            [round(float(v), 9) for v in joint.get("axis") or ()],
            sorted((joint.get("limit") or {}).items()),
            sorted((joint.get("dynamics") or {}).items()),
            sorted((joint.get("mimic") or {}).items()),
            sorted((joint.get("safety_controller") or {}).items()),
            sorted((joint.get("calibration") or {}).items()),
        ]
    )


def build_interfaces(assembly_name, joints, used_joints):
    """The interface pair each distinct joint turns into.

    Returns ``(interfaces, by_joint)``: the ``interfaces:`` section to write, and
    a map from joint name to its ``(socket, plug)`` interface names. Joints that
    say the same thing share a pair - every fixed joint in a robot is the same
    connection, and so is every identical revolute one.
    """
    interfaces = CommentedMap()
    by_signature = {}
    by_joint = {}

    for joint_name in used_joints:
        joint = joints[joint_name]
        signature = joint_signature(joint)
        if signature in by_signature:
            socket, plug = by_signature[signature]
            interfaces[socket]["desc"] += ", %s" % joint_name
            by_joint[joint_name] = (socket, plug)
            continue

        base = "%s/%s" % (assembly_name, "fixed" if joint["type"] == "fixed" else joint_name)
        socket, plug = "%s-socket" % base, "%s-plug" % base

        socket_config = CommentedMap()
        socket_config["desc"] = "URDF %s joint, as seen from the parent link. Used by: %s" % (
            joint["type"],
            joint_name,
        )
        # One port, at the interface origin: the parent implements it at the
        # joint origin, which is where the joint frame sits in the parent link.
        socket_config["ports"] = CommentedMap({"joint": None})

        motion = CommentedMap({"type": joint["type"]})
        if joint.get("axis"):
            motion["axis"] = _flow([float(v) for v in joint["axis"]])
        limit = joint.get("limit") or {}
        limits = CommentedMap()
        for key in ("lower", "upper"):
            if key in limit:
                limits[key] = limit[key]
        if limits:
            # In URDF's own units - radians for a revolute joint, metres for a
            # prismatic one - because this section is a record of what the URDF
            # said, not something PartCAD reinterprets.
            limits["units"] = "rad" if joint["type"] in ("revolute", "continuous") else "m"
            motion["limits"] = limits
        socket_config["motion"] = motion

        physics = CommentedMap()
        for section in ("limit", "dynamics", "mimic", "safety_controller", "calibration"):
            if joint.get(section):
                physics[section] = CommentedMap(joint[section])
        if physics:
            socket_config["physics"] = CommentedMap({"urdf": physics})

        parameter = movement_parameter(joint)
        if parameter is not None:
            socket_config["parameters"] = CommentedMap({parameter[0]: parameter[1]})

        plug_config = CommentedMap()
        plug_config["desc"] = "URDF %s joint, as seen from the child link" % joint["type"]
        # The half turn that makes the child's frame face the parent's port.
        plug_config["ports"] = CommentedMap({"joint": _location(FACING)})
        plug_config["mates"] = socket

        interfaces[socket] = socket_config
        interfaces[plug] = plug_config
        by_signature[signature] = (socket, plug)
        by_joint[joint_name] = (socket, plug)

    return interfaces, by_joint


def movement_parameter(joint):
    """The interface parameter that makes a movable joint actually move.

    ``motion`` above records what the joint is; this is the executable half. A
    connection that names it ("connect: {toParams: {angle: 30}}") places the
    child where the joint at that value puts it.
    """
    spec = JOINT_PARAMETERS.get(joint["type"])
    if spec is None or not joint.get("axis"):
        return None
    name, kind, convert = spec

    limit = joint.get("limit") or {}
    if joint["type"] == "continuous":
        lower, upper = -CONTINUOUS_RANGE, CONTINUOUS_RANGE
    elif "lower" in limit or "upper" in limit:
        lower = convert(float(limit.get("lower", 0.0)))
        upper = convert(float(limit.get("upper", 0.0)))
    else:
        return None

    config = CommentedMap()
    config["type"] = kind
    config["dir"] = _flow(joint_axis_in_port_frame(joint["axis"]))
    config["min"] = round(lower, 9)
    config["max"] = round(upper, 9)
    # The assembly shows the joint at zero, which is where URDF's own zero
    # configuration puts it, so that is the default.
    config["default"] = 0.0 if lower <= 0.0 <= upper else round(lower, 9)
    return name, config


def link_order(links):
    """Link names, parents before children, so 'connect:' always has its target."""
    children = {}
    roots = []
    for name, link in links.items():
        parent = link.get("parent")
        if parent is None or parent not in links:
            roots.append(name)
        else:
            children.setdefault(parent, []).append(name)

    ordered = []
    stack = list(reversed(roots))
    while stack:
        name = stack.pop()
        ordered.append(name)
        stack.extend(reversed(children.get(name, [])))
    return ordered


def effective_joint(link, joints, warnings):
    """The joint that attaches a link to the part above it, or None.

    A link whose parent has no geometry of its own is attached through a chain
    of joints; the last one is the joint proper and the ones before it are just
    frames folded into its origin. If one of *those* moves, the movement is lost
    - which is worth saying out loud.
    """
    chain = link.get("joints") or []
    if not chain:
        return None
    for joint_name in chain[:-1]:
        if joints[joint_name]["type"] != "fixed":
            warnings.append(
                "The %s joint '%s' passes through a link with no geometry; it is folded into the "
                "placement of '%s' and stops being a joint of its own"
                % (joints[joint_name]["type"], joint_name, chain[-1])
            )
    return joints[chain[-1]]


def at_link_frame(project: Project, assembly_name: str, link_name: str, item, shape_origin):
    """'item' seen from the link frame, so its mesh comes out in that frame.

    A link that is a sub-assembly already is in its own frame; a link that
    collapsed into a single part sits at that shape's ``<origin>`` instead, and
    has to be put back. Wrapping it either way keeps the caller uniform.
    """
    if is_identity(shape_origin):
        return item

    wrapper = Assembly(
        project.name,
        {"name": "%s:%s:frame" % (assembly_name, link_name), "child": True, "cache": False},
    )
    wrapper.cacheable = False
    wrapper.instantiate = lambda _self: True
    wrapper.children.append(AssemblyChild(item, link_name, Location(shape_origin)))
    return wrapper


def urdf_to_assy(project: Project, assembly_name: str, config: dict, out_dir: Path):
    """Turn a URDF assembly into an ASSY one, with parts and interfaces.

    Every link becomes an ``stl`` part written into ``<assembly>/`` inside the
    package, carrying whatever the URDF said about it in its ``physics``
    section. Every joint becomes an interface pair, and the ``.assy`` connects
    the parts through them.
    """
    ctx = project.ctx
    assembly = project.get_assembly(assembly_name)
    if assembly is None:
        raise ValueError("Assembly '%s' not found in '%s'" % (assembly_name, project.name))
    factory = getattr(assembly, "urdf_factory", None)
    if factory is None:
        raise ValueError("Assembly '%s' is not a URDF assembly" % assembly_name)

    result = asyncio.run(factory.read_async())
    links = result["links"]
    joints = result["joints"]
    warnings = []

    if not links:
        raise ValueError("The URDF assembly '%s' has no geometry to convert" % assembly_name)

    ordered = link_order(links)
    used_joints = []
    for link_name in ordered:
        joint = effective_joint(links[link_name], joints, warnings)
        if joint is not None and links[link_name].get("parent") in links:
            used_joints.append(joint["name"])
    interfaces, interface_of_joint = build_interfaces(assembly_name, joints, used_joints)

    # Each link's shape as one STL beside the package, and the part that reads
    # it. A link may be a single part or a sub-assembly of several shapes; both
    # render to one mesh, and both are re-expressed in the link frame first so
    # that the connections below place the *link*, not one of its pieces.
    asyncio.run(assembly.do_instantiate())
    parts = CommentedMap()
    implements = {name: CommentedMap() for name in links}
    for link_name in ordered:
        item = factory.link_item(link_name)
        if item is None:
            raise ValueError("The URDF link '%s' produced no shape to convert" % link_name)

        relative = "%s/%s.stl" % (assembly_name, link_name)
        stl_path = out_dir / relative
        stl_path.parent.mkdir(parents=True, exist_ok=True)
        in_link_frame = at_link_frame(project, assembly_name, link_name, item, links[link_name]["shape_origin"])
        asyncio.run(in_link_frame.render_async(ctx, "stl", project=project, filepath=str(stl_path)))
        if not stl_path.exists():
            raise RuntimeError("Failed to write the mesh of the link '%s'" % link_name)

        entry = CommentedMap()
        entry["type"] = "stl"
        entry["path"] = relative
        entry["desc"] = "Link '%s' of '%s'" % (link_name, assembly_name)
        if links[link_name].get("physics"):
            entry["physics"] = links[link_name]["physics"]
        parts["%s/%s" % (assembly_name, link_name)] = entry

    # Which interface each link implements, and where.
    for link_name in ordered:
        link = links[link_name]
        parent = link.get("parent")
        if parent is None or parent not in links:
            continue
        joint = effective_joint(link, joints, warnings)
        socket, plug = interface_of_joint[joint["name"]]
        # The parent carries the socket at the joint origin; the child carries
        # the plug at its own origin, and the plug's port supplies the flip.
        implements[parent].setdefault(socket, CommentedMap())[joint["name"]] = _location(link["origin"])
        implements[link_name][plug] = None

    for link_name, entries in implements.items():
        if entries:
            parts["%s/%s" % (assembly_name, link_name)]["implements"] = entries

    # The ASSY file itself.
    assy_links = CommentedSeq()
    for link_name in ordered:
        link = links[link_name]
        node = CommentedMap()
        node["part"] = ":%s/%s" % (assembly_name, link_name)
        node["name"] = link_name
        parent = link.get("parent")
        if parent is None or parent not in links:
            node["location"] = _location(link["origin"])
        else:
            joint = effective_joint(link, joints, warnings)
            socket, plug = interface_of_joint[joint["name"]]
            connect = CommentedMap()
            connect["with"] = plug
            connect["name"] = parent
            connect["to"] = socket
            connect["toInstance"] = joint["name"]
            node["connect"] = connect
        assy_links.append(node)

    assy_path = out_dir / ("%s.assy" % assembly_name)
    document = CommentedMap()
    document["name"] = assembly_name
    if result.get("robot_name"):
        document["description"] = "Converted from the URDF robot '%s'" % result["robot_name"]
    document["links"] = assy_links
    with open(assy_path, "w", encoding="utf-8") as f:
        _yaml().dump(document, f)

    # 'effective_joint' is consulted more than once per link, so the same
    # observation can be recorded more than once.
    for warning in sorted(set(warnings)):
        pc_logging.warning("%s: %s" % (assembly_name, warning))

    assembly_config = CommentedMap({"type": "assy"})
    if config.get("desc"):
        assembly_config["desc"] = config["desc"]
    try:
        assembly_config["path"] = str(assy_path.resolve().relative_to(Path(project.config_dir).resolve())).replace(
            "\\", "/"
        )
    except ValueError:
        assembly_config["path"] = str(assy_path)

    return {"assemblies": {assembly_name: assembly_config}, "parts": parts, "interfaces": interfaces}


def assy_to_urdf(project: Project, assembly_name: str, config: dict, out_dir: Path):
    """Export an assembly as a URDF file plus the STL files it references."""
    assembly = project.get_assembly(assembly_name)
    if assembly is None:
        raise ValueError("Assembly '%s' not found in '%s'" % (assembly_name, project.name))

    urdf_path = out_dir / ("%s.urdf" % assembly_name)
    urdf_path.parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(assembly.render_async(project.ctx, "urdf", project=project, filepath=str(urdf_path)))
    if not urdf_path.exists():
        raise RuntimeError("Failed to write the URDF file for '%s'" % assembly_name)

    assembly_config = CommentedMap({"type": "urdf"})
    if config.get("desc"):
        assembly_config["desc"] = config["desc"]
    try:
        assembly_config["path"] = str(urdf_path.resolve().relative_to(Path(project.config_dir).resolve())).replace(
            "\\", "/"
        )
    except ValueError:
        assembly_config["path"] = str(urdf_path)

    return {"assemblies": {assembly_name: assembly_config}}


def apply_config(project: Project, sections: dict) -> None:
    """Merge the generated sections into the package's 'partcad.yaml'."""
    yaml = _yaml()
    with open(project.config_path) as f:
        config = yaml.load(f)
    if config is None:
        config = CommentedMap()

    for section, entries in sections.items():
        if not entries:
            continue
        existing = config.get(section)
        if existing is None:
            config[section] = CommentedMap()
            existing = config[section]
        for name, entry in entries.items():
            existing[name] = entry

    with open(project.config_path, "w") as f:
        yaml.dump(config, f)

    # Keep the loaded package in step with what was just written, so a daemon
    # that goes on serving this context sees the converted assembly rather than
    # the one it had already built.
    project.config_obj = config
    instantiated = {"assembly": project.assemblies, "part": project.parts, "interface": project.interfaces}
    for section, entries in sections.items():
        kind = {"assemblies": "assembly", "parts": "part", "interfaces": "interface"}[section]
        known = project._object_configs.get(kind)
        for name, entry in entries.items():
            if known is not None:
                known[name] = entry
            # Drop what was built from the old configuration; the next lookup
            # rebuilds it from the new one.
            instantiated[kind].pop(name, None)


def convert_assembly_action(
    project: Project,
    object_name: str,
    target_format: str = None,
    output_dir: str = None,
    dry_run: bool = False,
):
    """Convert an assembly to another format and update its declaration."""
    if target_format not in SUPPORTED_FORMATS:
        raise ValueError(
            "Assemblies convert between %s; '%s' is not one of them"
            % (" and ".join(sorted(SUPPORTED_FORMATS)), target_format)
        )

    package_name, assembly_name = resolve_resource_path(project.name, object_name)
    if package_name != project.name:
        project = project.ctx.get_project(package_name)
        if project is None:
            raise ValueError("Package '%s' not found for '%s'" % (package_name, assembly_name))

    config = project.get_assembly_config(assembly_name)
    if config is None:
        raise ValueError("Assembly '%s' not found in '%s'" % (assembly_name, project.name))
    source_format = config.get("type")
    if source_format == target_format:
        pc_logging.info("Assembly '%s' is already '%s'; nothing to convert." % (assembly_name, target_format))
        return None
    if source_format not in SUPPORTED_FORMATS:
        raise ValueError("Assemblies of type '%s' cannot be converted" % source_format)

    out_dir = Path(output_dir).resolve() if output_dir else Path(project.config_dir).resolve()
    if dry_run:
        pc_logging.info(
            "[Dry Run] Would convert the assembly '%s' from '%s' to '%s' in %s"
            % (assembly_name, source_format, target_format, out_dir)
        )
        return None

    pc_logging.info(
        "Converting the assembly '%s': %s to %s (%s)" % (assembly_name, source_format, target_format, out_dir)
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    if target_format == "urdf":
        sections = assy_to_urdf(project, assembly_name, config, out_dir)
    else:
        sections = urdf_to_assy(project, assembly_name, config, out_dir)

    apply_config(project, sections)
    pc_logging.info("Conversion of the assembly '%s' is completed." % assembly_name)
    return sections
