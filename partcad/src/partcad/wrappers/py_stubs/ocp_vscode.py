#
# OpenVMP, 2023-2024
#
# Author: PartCAD Inc. <support@partcad.org>
# Created: 2024-04-08
#
# Licensed under Apache License, Version 2.0.
#

from enum import Enum
from ocp_tessellate.ocp_utils import (
    is_vector,
    is_topods_shape,
    is_topods_compound,
    is_cadquery,
    is_cadquery_assembly,
    is_cadquery_sketch,
    is_build123d,
    is_toploc_location,
    is_wrapped,
)

saved_show_object = None


class Camera(Enum):
    """Camera reset modes"""

    RESET = "reset"
    CENTER = "center"
    KEEP = "keep"


class Collapse(Enum):
    """Collapse modes for the CAD navigation tree"""

    NONE = 0
    LEAVES = 1
    ALL = 2
    ROOT = 3


def show_object(
    cad_obj,
    name=None,
    options=None,
    parent=None,
    clear=False,
    port=None,
    progress="-+c",  # Ignore it, we don't want any output
    glass=None,
    tools=None,
    measure_tools=None,
    tree_width=None,
    axes=None,
    axes0=None,
    grid=None,
    ortho=None,
    transparent=None,
    default_opacity=None,
    black_edges=None,
    orbit_control=None,
    collapse=None,
    ticks=None,
    center_grid=None,
    up=None,
    zoom=None,
    position=None,
    quaternion=None,
    target=None,
    reset_camera=None,
    clip_slider_0=None,
    clip_slider_1=None,
    clip_slider_2=None,
    clip_normal_0=None,
    clip_normal_1=None,
    clip_normal_2=None,
    clip_intersection=None,
    clip_planes=None,
    clip_object_colors=None,
    pan_speed=None,
    rotate_speed=None,
    zoom_speed=None,
    deviation=None,
    angular_tolerance=None,
    edge_accuracy=None,
    default_color=None,
    default_facecolor=None,
    default_thickedgecolor=None,
    default_vertexcolor=None,
    default_edgecolor=None,
    ambient_intensity=None,
    metalness=None,
    roughness=None,
    direct_intensity=None,
    render_edges=None,
    render_normals=None,
    render_mates=None,
    render_joints=None,
    parallel=None,
    show_parent=None,
    show_sketch_local=None,
    helper_scale=None,
    mate_scale=None,  # DEPRECATED
    debug=None,
    timeit=None,
):
    if options is None:
        options = {}
    options.update(
        {
            "name": name,
            "parent": parent,
            "clear": clear,
            "port": port,
            # "progress": progress,
            "glass": glass,
            "tools": tools,
            "measure_tools": measure_tools,
            "tree_width": tree_width,
            "axes": axes,
            "axes0": axes0,
            "grid": grid,
            "ortho": ortho,
            "transparent": transparent,
            "default_opacity": default_opacity,
            "black_edges": black_edges,
            "orbit_control": orbit_control,
            "collapse": collapse,
            "ticks": ticks,
            "center_grid": center_grid,
            "up": up,
            "zoom": zoom,
            "position": position,
            "quaternion": quaternion,
            "target": target,
            "reset_camera": reset_camera,
            "clip_slider_0": clip_slider_0,
            "clip_slider_1": clip_slider_1,
            "clip_slider_2": clip_slider_2,
            "clip_normal_0": clip_normal_0,
            "clip_normal_1": clip_normal_1,
            "clip_normal_2": clip_normal_2,
            "clip_intersection": clip_intersection,
            "clip_planes": clip_planes,
            "clip_object_colors": clip_object_colors,
            "pan_speed": pan_speed,
            "rotate_speed": rotate_speed,
            "zoom_speed": zoom_speed,
            "deviation": deviation,
            "angular_tolerance": angular_tolerance,
            "edge_accuracy": edge_accuracy,
            "default_color": default_color,
            "default_facecolor": default_facecolor,
            "default_thickedgecolor": default_thickedgecolor,
            "default_vertexcolor": default_vertexcolor,
            "default_edgecolor": default_edgecolor,
            "ambient_intensity": ambient_intensity,
            "metalness": metalness,
            "roughness": roughness,
            "direct_intensity": direct_intensity,
            "render_edges": render_edges,
            "render_normals": render_normals,
            "render_mates": render_mates,
            "render_joints": render_joints,
            "parallel": parallel,
            "show_parent": show_parent,
            "show_sketch_local": show_sketch_local,
            "helper_scale": helper_scale,
            "mate_scale": mate_scale,  # DEPRECATED
            "debug": debug,
            "timeit": timeit,
        }
    )
    saved_show_object(
        cad_obj,
        options=options,
    )


def show(
    *args,
    names=None,
    colors=None,
    alphas=None,
    port=None,
    progress="-+c",  # Ignore it, we don't want any output
    glass=None,
    tools=None,
    measure_tools=None,
    tree_width=None,
    axes=None,
    axes0=None,
    grid=None,
    ortho=None,
    transparent=None,
    default_opacity=None,
    black_edges=None,
    orbit_control=None,
    collapse=None,
    explode=None,
    ticks=None,
    center_grid=None,
    up=None,
    zoom=None,
    position=None,
    quaternion=None,
    target=None,
    reset_camera=None,
    clip_slider_0=None,
    clip_slider_1=None,
    clip_slider_2=None,
    clip_normal_0=None,
    clip_normal_1=None,
    clip_normal_2=None,
    clip_intersection=None,
    clip_planes=None,
    clip_object_colors=None,
    pan_speed=None,
    rotate_speed=None,
    zoom_speed=None,
    deviation=None,
    angular_tolerance=None,
    edge_accuracy=None,
    default_color=None,
    default_edgecolor=None,
    default_facecolor=None,
    default_thickedgecolor=None,
    default_vertexcolor=None,
    ambient_intensity=None,
    direct_intensity=None,
    metalness=None,
    roughness=None,
    render_edges=None,
    render_normals=None,
    render_mates=None,
    render_joints=None,
    show_parent=None,
    show_sketch_local=None,
    parallel=None,
    helper_scale=None,
    mate_scale=None,  # DEPRECATED
    debug=None,
    timeit=None,
    _force_in_debug=False,
):
    for idx, cad_obj in enumerate(args):
        saved_show_object(
            cad_obj,
            options={
                "name": names[idx] if names is not None else None,
                "color": colors[idx] if colors is not None else None,
                "alpha": alphas[idx] if alphas is not None else None,
                "port": port,
                # "progress": progress,
                "glass": glass,
                "tools": tools,
                "measure_tools": measure_tools,
                "tree_width": tree_width,
                "axes": axes,
                "axes0": axes0,
                "grid": grid,
                "ortho": ortho,
                "transparent": transparent,
                "default_opacity": default_opacity,
                "black_edges": black_edges,
                "orbit_control": orbit_control,
                "collapse": collapse,
                "ticks": ticks,
                "center_grid": center_grid,
                "up": up,
                "zoom": zoom,
                "position": position,
                "quaternion": quaternion,
                "target": target,
                "reset_camera": reset_camera,
                "clip_slider_0": clip_slider_0,
                "clip_slider_1": clip_slider_1,
                "clip_slider_2": clip_slider_2,
                "clip_normal_0": clip_normal_0,
                "clip_normal_1": clip_normal_1,
                "clip_normal_2": clip_normal_2,
                "clip_intersection": clip_intersection,
                "clip_planes": clip_planes,
                "clip_object_colors": clip_object_colors,
                "pan_speed": pan_speed,
                "rotate_speed": rotate_speed,
                "zoom_speed": zoom_speed,
                "deviation": deviation,
                "angular_tolerance": angular_tolerance,
                "edge_accuracy": edge_accuracy,
                "default_color": default_color,
                "default_facecolor": default_facecolor,
                "default_thickedgecolor": default_thickedgecolor,
                "default_vertexcolor": default_vertexcolor,
                "default_edgecolor": default_edgecolor,
                "ambient_intensity": ambient_intensity,
                "metalness": metalness,
                "roughness": roughness,
                "direct_intensity": direct_intensity,
                "render_edges": render_edges,
                "render_normals": render_normals,
                "render_mates": render_mates,
                "render_joints": render_joints,
                "parallel": parallel,
                "show_parent": show_parent,
                "show_sketch_local": show_sketch_local,
                "helper_scale": helper_scale,
                "mate_scale": mate_scale,  # DEPRECATED
                "debug": debug,
                "timeit": timeit,
            },
        )


def show_clear():
    pass


def show_all(
    variables=None, exclude=None, classes=None, _visual_debug=False, **kwargs
):
    import inspect
    import re

    if variables is None:
        cf = inspect.currentframe()
        variables = cf.f_back.f_locals

    if exclude is None:
        exclude = []

    objects = []
    names = []
    for name, obj in variables.items():
        if (
            isinstance(obj, type)
            or name in ["_", "__", "___"]
            or name.startswith("__")
            or re.search("_\\d+", name) is not None
        ):
            continue  # ignore classes and jupyter variables
        if hasattr(obj, "area") and obj.area > 1e99:  # inifinite face
            print(f"infinite face {name} skipped")
            continue

        if name not in exclude:
            if (
                hasattr(obj, "_obj")
                and obj._obj is None  # pylint: disable=protected-access
            ):
                continue

            if hasattr(obj, "locations") and hasattr(obj, "local_locations"):
                obj = obj.locations

            if hasattr(obj, "local_coord_system"):
                obj = obj.location

            if (
                (
                    hasattr(obj, "wrapped")
                    and (
                        is_topods_shape(obj.wrapped)
                        or is_topods_compound(obj.wrapped)
                        or is_toploc_location(obj.wrapped)
                    )
                )
                or is_vector(obj)  # Vector
                or is_cadquery(obj)
                or is_build123d(obj)
                or is_cadquery_assembly(obj)
                or (
                    hasattr(obj, "wrapped")
                    and hasattr(obj, "position")
                    and hasattr(obj, "direction")
                )
            ):
                objects.append(obj)
                names.append(name)

    if len(objects) > 0:
        show(
            *objects,
            names=names,
            collapse=Collapse.ROOT,
            _force_in_debug=_visual_debug,
            **kwargs,
        )
    else:
        show_clear()


def set_defaults(**kwargs):
    pass
