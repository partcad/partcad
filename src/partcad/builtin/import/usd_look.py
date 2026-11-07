#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What each face of a USD stage looks like: its colour, its finish and what it is made of.

USD says how a surface looks with a material bound to it - to a mesh, or to a
subset of its faces ('GeomSubset' of the 'materialBind' family) - whose surface
shader is one of a few kinds; and, where no material is bound or none can be
read, with the 'displayColor' and 'displayOpacity' primvars, which is what USD
says a renderer that cannot read a material draws. This reads what PartCAD can
draw of that, face by face:

  * the colour: the shader's base colour - a constant; a texture, read where
    each face is on it (at the middle of the face's UVs); or a primvar a reader
    names - else 'displayColor', which may differ face by face too;
  * how see-through it is: the shader's opacity, else 'displayOpacity';
  * the finish: its roughness and how metallic it is - constants, or what the
    textures giving them say where each face is;
  * what it is made of, where the source names it: a SimReady material's class
    ('opaque__metal__aluminium_pallet' is metal), else the name of the material
    a physics binding names.

The shaders read are UsdPreviewSurface, MaterialX's standard_surface, OpenPBR
and glTF PBR surfaces and its UsdPreviewSurface, and NVIDIA's OmniPBR,
OmniGlass and OmniSurface - their inputs on the shader prim, or the arguments
of an MDL preset in the package that calls one ('export material X(*) =
OmniPBR(...)'). Any other shader is a material PartCAD cannot read, and its
faces are drawn in 'displayColor'.

A MaterialX document ('.mtlx') a layer references is read here too: usd-core,
as it is published on PyPI, has no MaterialX file format, so such a reference
composes nothing and a mesh is bound to a material that is not there. Its
'surfacematerial' of that material's name is read instead, from the document
the binding's scope references ('MtlxDocument').

A face's look is '(name, rgba, roughness, metallic, material)'. 'name' is the
bound material's, or DISPLAY where none is bound: the designation a package's
colour declaration claims with 'ids: {usd: <name>}' (the 'usd' convention of
'partcad.cmf_conventions'). 'rgba' is the sRGB colour (0-255) and alpha (0-1),
and it and the rest are None where nothing says. The colours read face by face
are each material's palette - its most telling colours, by median cut - so that
a part is drawn in at most MAX_LOOKS looks and keeps every hue it has.

Images are read with Pillow, each once, shrunk to at most IMAGE_SIDE pixels a
side: a face is drawn in one colour, which a smaller image gives as well.
"""

import io
import os
import re
import zipfile

# The most looks a part is drawn in: a colour read off a texture face by face
# is rounded until there are no more than this.
MAX_LOOKS = 1024

# The look of the faces no material is bound to: they are drawn in their
# 'displayColor'.
DISPLAY = "displayColor"

# The size, in pixels a side, an image is shrunk to before it is read.
IMAGE_SIDE = 256

# The most pixels an image may be decoded at - after a JPEG's own reduction -
# for it to be read: a 16K texture is 1 GB of RGBA, and a face drawn in one
# colour is not worth that. A larger one is read as no image, so its texture's
# fallback, or the face's 'displayColor', draws the face.
MAX_DECODED_PIXELS = 8192 * 8192

# SimReady names a material '<opacity>__<class>__<what>'.
_SIMREADY = re.compile(r"^(opaque|translucent|transparent|emissive)__([A-Za-z0-9]+)__", re.IGNORECASE)

# How see-through each of SimReady's opacity classes is drawn, and how a
# SimReady class looks where nothing else says: (roughness, metallic).
_SIMREADY_ALPHA = {"translucent": 0.6, "transparent": 0.3}
_SIMREADY_FINISH = {"metal": (0.35, 1.0), "glass": (0.05, 0.0), "plastic": (0.45, 0.0), "rubber": (0.85, 0.0)}

# The shaders read, by their id, and the inputs that say what PartCAD draws.
_PREVIEW = ("UsdPreviewSurface", "ND_UsdPreviewSurface_surfaceshader")
_STANDARD = ("ND_standard_surface_surfaceshader",)
_OPEN_PBR = ("ND_open_pbr_surface_surfaceshader",)
_GLTF = ("ND_gltf_pbr_surfaceshader",)

# How much of a texture an output reads.
_OUTPUT_CHANNELS = {"rgb": (0, 1, 2), "rgba": (0, 1, 2, 3), "r": (0,), "g": (1,), "b": (2,), "a": (3,)}


def srgb_of_linear(values):
    """Linear colour channels (0 to 1) as sRGB ones (0 to 255), as floats."""
    import numpy

    values = numpy.clip(numpy.asarray(values, dtype=numpy.float64), 0.0, 1.0)
    return 255.0 * numpy.where(values <= 0.0031308, values * 12.92, 1.055 * numpy.power(values, 1 / 2.4) - 0.055)


def linear_of_srgb(values):
    """sRGB colour channels (0 to 1) as linear ones."""
    import numpy

    values = numpy.asarray(values, dtype=numpy.float64)
    return numpy.where(values <= 0.04045, values / 12.92, numpy.power((values + 0.055) / 1.055, 2.4))


# -- what a material says -------------------------------------------------------
#
# A channel of a surface - its colour, opacity, roughness or metallic - is where
# its value comes from: ('constant', value), ('texture', image, channels, uv
# primvar, scale, bias, fallback, is colour), or ('primvar', name, fallback).


class Surface:
    """What a material says to draw: its name and where each channel comes from."""

    def __init__(self, name):
        self.name = name
        self.color = None
        self.opacity = None
        self.roughness = None
        self.metallic = None
        self.material = None


def _constant(value):
    return ("constant", value)


class Looks:
    """What each face of a stage's meshes looks like (see the module's docstring)."""

    def __init__(self, stage, time):
        self.stage = stage
        self.time = time
        self.surfaces = {}  # material path -> Surface or None
        self.images = {}  # resolved path -> float array (rows, columns, 4), or None
        self.names = []
        self.materials = []
        self._name_index = {}
        self._material_index = {}
        # Every file a look was read from - an image, a MaterialX document, an
        # MDL module - by its resolved path: what the part is built from besides
        # the layers of the stage (see 'part_usd.read').
        self.read = set()

    def name_id(self, name):
        if name not in self._name_index:
            self._name_index[name] = len(self.names)
            self.names.append(name)
        return self._name_index[name]

    def material_id(self, material):
        if material is None:
            return -1
        if material not in self._material_index:
            self._material_index[material] = len(self.materials)
            self.materials.append(material)
        return self._material_index[material]

    # -- reading a material --

    def surface(self, material):
        """The Surface 'material' (a UsdShade.Material) says to draw, read once."""
        path = material.GetPath()
        if path not in self.surfaces:
            try:
                self.surfaces[path] = self._surface(material)
            except Exception:  # a material that cannot be read is drawn as none is
                self.surfaces[path] = Surface(material.GetPrim().GetName())
        return self.surfaces[path]

    def _surface(self, material):
        from pxr import UsdShade

        surface = Surface(material.GetPrim().GetName())
        simready = _SIMREADY.match(surface.name)
        if simready:
            surface.material = simready.group(2).lower()
        for context in ("", "mtlx"):
            shader = material.ComputeSurfaceSource(context)[0]
            ident = shader.GetIdAttr().Get() if shader else None
            if ident in _PREVIEW:
                surface.color = self._input(shader, "diffuseColor", True) or _constant((0.18, 0.18, 0.18))
                surface.opacity = self._input(shader, "opacity", False)
                surface.roughness = self._input(shader, "roughness", False) or _constant(0.5)
                surface.metallic = self._input(shader, "metallic", False) or _constant(0.0)
                break
            if ident in _OPEN_PBR + _GLTF:
                _pbr(ident in _GLTF, lambda name, colour: self._input(shader, name, colour), surface)
                break
            if ident in _STANDARD:
                surface.color = self._input(shader, "base_color", True) or _constant((0.8, 0.8, 0.8))
                weight = self._input(shader, "base", False)
                if weight is not None and weight[0] == "constant" and surface.color[0] == "constant":
                    surface.color = _constant(tuple(float(weight[1]) * c for c in surface.color[1]))
                surface.roughness = self._input(shader, "specular_roughness", False) or _constant(0.2)
                surface.metallic = self._input(shader, "metalness", False) or _constant(0.0)
                transmission = self._input(shader, "transmission", False)
                opacity = self._input(shader, "opacity", True)
                if opacity is not None and opacity[0] == "constant":
                    surface.opacity = _constant(sum(opacity[1]) / 3.0)
                elif transmission is not None and transmission[0] == "constant":
                    surface.opacity = _constant(1.0 - 0.7 * float(transmission[1]))
                break
        else:
            shader = material.ComputeSurfaceSource("mdl")[0]
            if shader:
                self._mdl(shader, surface)
        if simready:
            if surface.opacity is None and simready.group(1).lower() in _SIMREADY_ALPHA:
                surface.opacity = _constant(_SIMREADY_ALPHA[simready.group(1).lower()])
            finish = _SIMREADY_FINISH.get(surface.material)
            if finish is not None:
                surface.roughness = surface.roughness or _constant(finish[0])
                surface.metallic = surface.metallic or _constant(finish[1])
        if surface.material is None:
            surface.material = _physics_material(material.GetPrim(), UsdShade)
        return surface

    def _input(self, shader, name, colour):
        """The channel the input 'name' of 'shader' comes from, or None where it is not authored."""
        from pxr import UsdShade

        given = shader.GetInput(name)
        if not given:
            return None
        produced = given.GetValueProducingAttributes()
        if not produced:
            return None
        attribute = produced[0]
        output, kind = UsdShade.Utils.GetBaseNameAndType(attribute.GetName())
        if kind != UsdShade.AttributeType.Output:
            value = attribute.Get(self.time)
            return None if value is None else _constant(_plain(value))
        node = UsdShade.Shader(attribute.GetPrim())
        ident = str(node.GetIdAttr().Get() or "")
        if node.GetInput("file"):
            return self._texture(node, output, colour)
        if ident.startswith("UsdPrimvarReader") or "geompropvalue" in ident:
            varname = node.GetInput("varname") or node.GetInput("geomprop")
            fallback = node.GetInput("fallback") or node.GetInput("default")
            fallback = fallback.Get(self.time) if fallback else None
            return ("primvar", str(varname.Get(self.time)) if varname else DISPLAY, _plain(fallback))
        return None

    def _texture(self, node, output, colour):
        from pxr import UsdShade

        asset = node.GetInput("file").Get(self.time)
        resolved = getattr(asset, "resolvedPath", "") if asset is not None else ""
        uv = "st"
        st = node.GetInput("st") or node.GetInput("texcoord")
        if st:
            for attribute in st.GetValueProducingAttributes():
                reader = UsdShade.Shader(attribute.GetPrim())
                varname = reader.GetInput("varname") or reader.GetInput("geomprop")
                if varname and varname.Get(self.time):
                    uv = str(varname.Get(self.time))
        scale = _value(node, "scale", self.time, (1.0, 1.0, 1.0, 1.0))
        bias = _value(node, "bias", self.time, (0.0, 0.0, 0.0, 0.0))
        fallback = _value(node, "fallback", self.time, None)
        space = str(_value(node, "sourceColorSpace", self.time, "auto"))
        channels = _OUTPUT_CHANNELS.get(output, (0, 1, 2) if colour else (0,))
        is_colour = space == "sRGB" or (space == "auto" and colour)
        return ("texture", resolved, channels, uv, scale, bias, fallback, is_colour)

    def _mdl(self, shader, surface):
        """'surface' read off an MDL shader: OmniPBR, OmniGlass or OmniSurface, or a preset calling one."""
        prim = shader.GetPrim()
        source = prim.GetAttribute("info:mdl:sourceAsset").Get() if prim.HasAttribute("info:mdl:sourceAsset") else None
        sub = prim.GetAttribute("info:mdl:sourceAsset:subIdentifier")
        sub = str(sub.Get() or "") if sub else ""
        path = getattr(source, "path", "") if source is not None else ""
        known = _mdl_kind(os.path.basename(path)) or _mdl_kind(sub)
        kind, arguments = known if known is not None else (None, {})
        resolved = getattr(source, "resolvedPath", "") if source is not None else ""
        if kind is None and resolved:
            self.read.add(resolved)
            text = read_bytes(resolved)
            preset = parse_mdl_preset(text.decode("utf-8", "replace") if text else "", sub)
            if preset is not None:
                kind, arguments = preset
                arguments = {
                    key: (("asset", _beside(resolved, value[1])) if isinstance(value, tuple) and value[0] == "asset"
                          else value)
                    for key, value in arguments.items()
                }  # fmt: skip
        if kind is None:
            return
        for given in shader.GetInputs():
            channel = self._input(shader, given.GetBaseName(), "color" in given.GetBaseName())
            if channel is not None:
                arguments[given.GetBaseName()] = channel
        _omni(kind, arguments, surface, self)

    def _bound(self, binding):
        """What 'binding' binds, best first: UsdShade.Materials and Surfaces read from MaterialX; None for nothing.

        The binding a final render draws with - of the 'full' purpose, else of
        all purposes - and then a preview's, which is drawn with where the
        final one's colour cannot be read here (ALab's final materials read
        EXR textures, its previews JPEG).
        """
        from pxr import UsdShade

        found, seen = [], set()
        for purpose in (UsdShade.Tokens.full, UsdShade.Tokens.preview):
            material, _ = binding.ComputeBoundMaterial(purpose)
            if material:
                if material.GetPath() not in seen:
                    seen.add(material.GetPath())
                    found.append(material)
                continue
            # A material that is not there: one a MaterialX reference was to make.
            for asked in (purpose, UsdShade.Tokens.allPurpose):
                relation = binding.GetDirectBindingRel(asked)
                targets = relation.GetTargets() if relation else []
                surface = self.mtlx_surface(targets[0]) if targets else None
                if surface is not None and targets[0] not in seen:
                    seen.add(targets[0])
                    found.append(surface)
                    break
        return found or None

    def mtlx_surface(self, path):
        """The Surface the MaterialX 'surfacematerial' a missing material at 'path' was to be made of, or None.

        Looked for in the documents the scope above it references, nearest
        first, by the material's name.
        """
        from pxr import Sdf

        if path in self.surfaces:
            return self.surfaces[path]
        found = None
        parent = path.GetParentPath()
        while found is None and not parent.isEmpty and parent != Sdf.Path.absoluteRootPath:
            prim = self.stage.GetPrimAtPath(parent)
            for document in _mtlx_references(prim) if prim else []:
                found = self.mtlx(document).surface(path.name, self)
                if found is not None:
                    break
            parent = parent.GetParentPath()
        self.surfaces[path] = found
        return found

    def mtlx(self, resolved):
        """The MaterialX document at 'resolved', read once."""
        key = ("mtlx", resolved)
        if key not in self.surfaces:
            self.read.add(resolved)
            self.surfaces[key] = MtlxDocument(resolved)
        return self.surfaces[key]

    # -- reading a channel face by face --

    def image(self, resolved):
        """The image at 'resolved' as floats (rows, columns, 4), 0 to 1; None where it cannot be read."""
        if resolved not in self.images:
            self.read.add(resolved)
            self.images[resolved] = _read_image(resolved)
        return self.images[resolved]

    def evaluate(self, channel, prim, faces, corners, points, width):
        """'channel''s value for each triangle, as an array (triangles x width); None where it says nothing.

        'faces' is the face of the mesh each triangle is of, 'corners' its
        three face-vertices (indices into the face-vertex list) and 'points'
        its three points.
        """
        import numpy

        if channel is None:
            return None
        kind = channel[0]
        if kind == "constant":
            return _fit(numpy.asarray(channel[1], dtype=numpy.float64), width, len(faces))
        if kind == "primvar":
            values = _primvar(prim, channel[1], self.time, faces, corners, points)
            if values is None and channel[2] is not None:
                return _fit(numpy.asarray(channel[2], dtype=numpy.float64), width, len(faces))
            return None if values is None else _fit_rows(values, width)
        _, resolved, channels, uv_name, scale, bias, fallback, is_colour = channel
        image = self.image(resolved) if resolved else None
        if image is None:
            if fallback is not None:
                # The fallback is the texture's own four channels: the ones read are taken from it.
                return _fit(numpy.asarray(fallback, dtype=numpy.float64)[list(channels)], width, len(faces))
            return None
        uv = _primvar(prim, uv_name, self.time, faces, corners, points)
        if uv is None:
            uv = _any_uv(prim, self.time, faces, corners, points)
        if uv is None or uv.shape[1] < 2:
            # Laid by nothing this reads - a projection, a coordinate set it
            # does not find - and drawn in the image's mean.
            picked = numpy.repeat(image.reshape(-1, image.shape[2]).mean(axis=0)[None], len(faces), axis=0)
        else:
            rows, columns = image.shape[:2]
            x = numpy.mod(uv[:, 0], 1.0) * columns
            y = (1.0 - numpy.mod(uv[:, 1], 1.0)) * rows
            picked = image[numpy.clip(y.astype(int), 0, rows - 1), numpy.clip(x.astype(int), 0, columns - 1)]
        values = picked[:, list(channels)]
        if is_colour:
            values = linear_of_srgb(values)
        values = (
            values * numpy.asarray(scale, dtype=numpy.float64)[list(channels)]
            + numpy.asarray(bias, dtype=numpy.float64)[list(channels)]
        )
        return _fit_rows(values, width)

    def faces(self, prim, faces, corners, points, face_count):
        """Each triangle's look, as arrays: (names, rgb, alpha, roughness, metallic, materials).

        'rgb' is sRGB, 0 to 255, NaN where nothing colours a triangle; 'alpha',
        'roughness' and 'metallic' are NaN where nothing says; 'names' and
        'materials' are indices into 'names' and 'materials' (-1 for none).
        """
        import numpy
        from pxr import UsdShade

        count = len(faces)
        bound = numpy.full(face_count, -1, dtype=numpy.int64)
        found = []
        binding = UsdShade.MaterialBindingAPI(prim)
        own = self._bound(binding)
        if own is not None:
            found.append(own)
            bound[:] = 0
        for subset in binding.GetMaterialBindSubsets():
            material = self._bound(UsdShade.MaterialBindingAPI(subset.GetPrim()))
            indices = subset.GetIndicesAttr().Get(self.time)
            if material is None or not indices:
                continue
            indices = numpy.asarray(indices, dtype=numpy.int64)
            indices = indices[(indices >= 0) & (indices < face_count)]
            found.append(material)
            bound[indices] = len(found) - 1
        names = numpy.full(count, self.name_id(DISPLAY), dtype=numpy.int64)
        rgb = numpy.full((count, 3), numpy.nan)
        alpha = numpy.full(count, numpy.nan)
        roughness = numpy.full(count, numpy.nan)
        metallic = numpy.full(count, numpy.nan)
        materials = numpy.full(count, -1, dtype=numpy.int64)
        of_triangle = bound[faces]
        for index in range(-1, len(found)):
            mine = numpy.nonzero(of_triangle == index)[0]
            if not len(mine):
                continue
            candidates = found[index] if index >= 0 else []
            surfaces = [each if isinstance(each, Surface) else self.surface(each) for each in candidates]
            args = (prim, faces[mine], corners[mine], points[mine])
            # The first material whose colour can be read here draws the faces.
            surface, colour = (surfaces[0] if surfaces else None), None
            for candidate in surfaces:
                colour = self.evaluate(candidate.color, *args, 3)
                if colour is not None:
                    surface = candidate
                    break
            if colour is None:
                colour = self.evaluate(("primvar", DISPLAY, None), *args, 3)
            if colour is not None:
                rgb[mine] = srgb_of_linear(colour)
            opacity = self.evaluate(surface.opacity, *args, 1) if surface is not None else None
            if opacity is None:
                opacity = self.evaluate(("primvar", "displayOpacity", None), *args, 1)
            if opacity is not None:
                alpha[mine] = numpy.clip(opacity[:, 0], 0.0, 1.0)
            if surface is not None:
                names[mine] = self.name_id(surface.name)
                materials[mine] = self.material_id(surface.material)
                for channel, into in ((surface.roughness, roughness), (surface.metallic, metallic)):
                    value = self.evaluate(channel, *args, 1)
                    if value is not None:
                        into[mine] = numpy.clip(value[:, 0], 0.0, 1.0)
        return names, rgb, alpha, roughness, metallic, materials


def settle(names, rgb, alpha, roughness, metallic, materials, name_table, material_table):
    """'(looks, ids)': every look the triangles are in, rounded to at most MAX_LOOKS, and each triangle's.

    The arrays are each triangle's, as 'Looks.faces' gives them; a look is
    '(name, rgba, roughness, metallic, material)'.
    """
    import numpy

    count = len(names)
    if count == 0:
        return [], numpy.zeros(0, dtype=numpy.int64)
    coloured = ~numpy.isnan(rgb[:, 0])
    # Each material's colours, its palette where it has more than its share.
    rgb = rgb.copy()
    materials_named = numpy.unique(names[coloured]) if coloured.any() else []
    share = max(8, min(256, MAX_LOOKS // max(1, 2 * len(materials_named))))
    for name in materials_named:
        mine = numpy.nonzero(coloured & (names == name))[0]
        rgb[mine] = _palette(numpy.round(rgb[mine]), share)
    for step, finish_step in ((1, 0.01), (1, 0.05), (4, 0.05), (8, 0.1), (16, 0.25), (32, 0.25), (64, 0.5)):
        rows = numpy.column_stack(
            [
                names,
                materials,
                numpy.where(coloured[:, None], numpy.round(numpy.nan_to_num(rgb) / step) * step, -1),
                numpy.where(numpy.isnan(alpha), -1, numpy.round(numpy.nan_to_num(alpha) / 0.05) * 0.05),
                numpy.where(numpy.isnan(roughness), -1, numpy.round(numpy.nan_to_num(roughness) / finish_step)),
                numpy.where(numpy.isnan(metallic), -1, numpy.round(numpy.nan_to_num(metallic) / finish_step)),
            ]
        )
        unique, ids = numpy.unique(rows, axis=0, return_inverse=True)
        if len(unique) <= MAX_LOOKS:
            break
    looks = []
    for row in unique:
        name = name_table[int(row[0])]
        material = material_table[int(row[1])] if row[1] >= 0 else None
        rgba = None
        if row[2] >= 0:
            channels = [int(min(255, max(0, round(v)))) for v in row[2:5]]
            rgba = (channels[0], channels[1], channels[2], round(float(row[5]), 3) if row[5] >= 0 else 1.0)
        rough = round(float(row[6]) * finish_step, 3) if row[6] >= 0 else None
        metal = round(float(row[7]) * finish_step, 3) if row[7] >= 0 else None
        looks.append((name, rgba, rough, metal, material))
    return looks, ids.reshape(-1)


def _palette(rgb, colours):
    """Each of the sRGB colours 'rgb' (n x 3, 0-255) as the nearest of at most 'colours' of them, by median cut.

    Pillow's median cut, which keeps the colours a surface is most of and every
    hue it has; the colours as they are where there are no more than that, or
    no Pillow.
    """
    import numpy

    if len(numpy.unique(rgb, axis=0)) <= colours:
        return rgb
    try:
        from PIL import Image
    except ImportError:
        step = 256.0 / round(colours ** (1 / 3.0))
        return numpy.clip(numpy.round(rgb / step) * step, 0, 255)
    count = len(rgb)
    width = 1024
    rows = -(-count // width)
    padded = numpy.zeros((rows * width, 3), dtype=numpy.uint8)
    padded[:count] = numpy.clip(rgb, 0, 255).astype(numpy.uint8)
    # The padding is the first colour again, so it adds no colour of its own.
    padded[count:] = padded[0]
    image = Image.fromarray(padded.reshape(rows, width, 3), "RGB")
    reduced = image.quantize(colors=int(colours), method=Image.Quantize.MEDIANCUT)
    palette = numpy.asarray(reduced.getpalette()[: 3 * 256], dtype=numpy.float64).reshape(-1, 3)
    return palette[numpy.asarray(reduced).reshape(-1)[:count]]


# -- MaterialX -------------------------------------------------------------------------


def _mtlx_references(prim):
    """The resolved paths of the MaterialX documents 'prim' references, as its layers write them."""
    found = []
    for spec in prim.GetPrimStack():
        for arcs in (spec.referenceList, spec.payloadList):
            for arc in list(arcs.prependedItems) + list(arcs.appendedItems) + list(arcs.explicitItems):
                if arc.assetPath.lower().endswith(".mtlx"):
                    found.append(spec.layer.ComputeAbsolutePath(arc.assetPath))
    return found


def _mtlx_value(text):
    """A MaterialX value: a number, a colour or vector as a tuple of them, or the text as it is."""
    try:
        values = [float(v) for v in str(text).split(",")]
    except ValueError:
        return text
    return values[0] if len(values) == 1 else tuple(values)


class MtlxDocument:
    """A MaterialX document, read for what its 'surfacematerial's draw (see 'Looks.mtlx_surface')."""

    def __init__(self, resolved):
        import xml.etree.ElementTree as ElementTree

        self.resolved = resolved
        self.root = None
        data = read_bytes(resolved)
        if data:
            try:
                self.root = ElementTree.fromstring(data)
            except ElementTree.ParseError:
                self.root = None
        # Every element by name, a nodegraph's by '<graph>/<name>', with the
        # file prefix that applies to it.
        self.elements = {}
        if self.root is not None:
            self._index(self.root, "", self.root.get("fileprefix", ""))

    def _index(self, element, graph, prefix):
        for child in element:
            name = child.get("name")
            here = prefix + child.get("fileprefix", "") if child.get("fileprefix") else prefix
            if name:
                self.elements[(graph, name)] = (child, here)
            if child.tag == "nodegraph" and name:
                self._index(child, name, here)

    def surface(self, name, looks):
        """The Surface of the 'surfacematerial' (or 'material') named 'name', or None."""
        found = self.elements.get(("", name))
        if found is None or found[0].tag not in ("surfacematerial", "material"):
            return None
        material = found[0]
        shader = None
        for given in material.findall("input"):
            if given.get("name") == "surfaceshader" and given.get("nodename"):
                shader = self.elements.get(("", given.get("nodename")))
        for reference in material.findall("shaderref"):  # MaterialX 1.37
            shader = self.elements.get(("", reference.get("node") or reference.get("name")))
        if shader is None:
            return None
        shader = shader[0]
        surface = Surface(name)
        simready = _SIMREADY.match(name)
        if simready:
            surface.material = simready.group(2).lower()

        def channel(input_name, colour):
            return self._channel(shader, "", input_name, colour)

        if shader.tag == "standard_surface":
            surface.color = channel("base_color", True) or _constant((0.8, 0.8, 0.8))
            weight = channel("base", False)
            if weight is not None and weight[0] == "constant" and surface.color[0] == "constant":
                surface.color = _constant(tuple(float(weight[1]) * c for c in surface.color[1]))
            surface.roughness = channel("specular_roughness", False) or _constant(0.2)
            surface.metallic = channel("metalness", False) or _constant(0.0)
            transmission = channel("transmission", False)
            if transmission is not None and transmission[0] == "constant":
                surface.opacity = _constant(1.0 - 0.7 * float(transmission[1]))
        elif shader.tag in ("open_pbr_surface", "gltf_pbr"):
            _pbr(shader.tag == "gltf_pbr", channel, surface)
        elif shader.tag == "UsdPreviewSurface":
            surface.color = channel("diffuseColor", True) or _constant((0.18, 0.18, 0.18))
            surface.roughness = channel("roughness", False) or _constant(0.5)
            surface.metallic = channel("metallic", False) or _constant(0.0)
            surface.opacity = channel("opacity", False)
        else:
            return None
        return surface

    def _channel(self, node, graph, input_name, colour, depth=0):
        """The channel the input 'input_name' of 'node' comes from: a value, an image, or what a graph outputs."""
        given = next((i for i in node.findall("input") if i.get("name") == input_name), None)
        if given is None or depth > 8:
            return None
        if given.get("value") is not None and not given.get("nodename") and not given.get("nodegraph"):
            return _constant(_mtlx_value(given.get("value")))
        source_graph = given.get("nodegraph") if given.get("nodegraph") else graph
        name = given.get("nodename")
        if given.get("nodegraph"):
            output = self.elements.get((source_graph, given.get("output") or "out"))
            if output is None:
                outputs = [e for (g, _), (e, _) in self.elements.items() if g == source_graph and e.tag == "output"]
                output = (outputs[0], "") if outputs else None
            if output is None:
                return None
            name = output[0].get("nodename")
        found = self.elements.get((source_graph, name)) if name else None
        if found is None:
            return None
        element, prefix = found
        if element.tag in ("image", "tiledimage", "gltf_image"):
            file_input = next((i for i in element.findall("input") if i.get("name") == "file"), None)
            if file_input is None or not file_input.get("value"):
                return None
            path = (file_input.get("fileprefix") or prefix) + file_input.get("value")
            space = file_input.get("colorspace") or element.get("colorspace") or ""
            channels = {"color3": (0, 1, 2), "color4": (0, 1, 2, 3), "vector3": (0, 1, 2)}.get(
                element.get("type"), (0,)
            )
            is_colour = colour and (
                space.startswith("srgb") or (not space and element.get("type") in ("color3", "color4"))
            )
            return ("texture", _beside(self.resolved, path), channels, "st", (1.0,) * 4, (0.0,) * 4, None, is_colour)
        if element.tag == "constant":
            return self._channel(element, source_graph, "value", colour, depth + 1)
        if element.tag == "dot":
            return self._channel(element, source_graph, "in", colour, depth + 1)
        return None


def _pbr(gltf, channel, surface):
    """'surface' from an OpenPBR surface's inputs, or a glTF PBR one's ('gltf'); 'channel(name, colour)' reads one."""
    if gltf:
        surface.color = channel("base_color", True) or _constant((1.0, 1.0, 1.0))
        surface.roughness = channel("roughness", False) or _constant(1.0)
        surface.metallic = channel("metallic", False) or _constant(1.0)
        surface.opacity = channel("alpha", False)
        return
    surface.color = channel("base_color", True) or _constant((0.8, 0.8, 0.8))
    weight = channel("base_weight", False)
    if weight is not None and weight[0] == "constant" and surface.color[0] == "constant":
        surface.color = _constant(tuple(float(weight[1]) * c for c in surface.color[1]))
    surface.roughness = channel("specular_roughness", False) or _constant(0.3)
    surface.metallic = channel("base_metalness", False) or _constant(0.0)
    transmission = channel("transmission_weight", False)
    opacity = channel("geometry_opacity", False)
    if opacity is not None and opacity[0] == "constant":
        surface.opacity = opacity
    elif transmission is not None and transmission[0] == "constant":
        surface.opacity = _constant(1.0 - 0.7 * float(transmission[1]))


# -- MDL ----------------------------------------------------------------------------


def _mdl_kind(name):
    """'(kind, {})' for a module or material of NVIDIA's that this reads, by its name; None for any other."""
    base = os.path.splitext(name or "")[0]
    for kind in ("OmniPBR", "OmniGlass", "OmniSurface"):
        if base.startswith(kind):
            return kind, {}
    return None


_CALL = re.compile(r"=\s*(?:::)?(?:\w+::)*(OmniPBR\w*|OmniGlass\w*|OmniSurface\w*)\s*\(")
_NUMBER = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?f?"


def parse_mdl_preset(text, name=""):
    """'(kind, {argument: value})' of an MDL preset - 'export material X(*) = OmniPBR(...)' - or None.

    A value is a number, a bool, a colour '(r, g, b)', or ('asset', path) for a
    'texture_2d("path", ...)'; any other argument is left out.
    """
    text = re.sub(r"//[^\n]*", "", text or "")
    calls = list(_CALL.finditer(text))
    if not calls:
        return None
    if name:
        named = [c for c in calls if re.search(r"material\s+%s\b[^=]*$" % re.escape(name), text[: c.start() + 1])]
        calls = named or calls
    call = calls[0]
    kind = _mdl_kind(call.group(1))[0]
    depth, start, end = 1, call.end(), None
    for index in range(call.end(), len(text)):
        if text[index] == "(":
            depth += 1
        elif text[index] == ")":
            depth -= 1
            if depth == 0:
                end = index
                break
    if end is None:
        return None
    arguments = {}
    for key, value in _split_arguments(text[start:end]):
        parsed = _mdl_value(value)
        if parsed is not None:
            arguments[key] = parsed
    return kind, arguments


def _split_arguments(text):
    """'[(name, value text)]' of 'name: value, ...', commas inside brackets not splitting."""
    found, depth, current = [], 0, ""
    for character in text + ",":
        if character in "([":
            depth += 1
        elif character in ")]":
            depth -= 1
        if character == "," and depth == 0:
            if ":" in current:
                key, value = current.split(":", 1)
                found.append((key.strip(), value.strip()))
            current = ""
        else:
            current += character
    return found


def _mdl_value(text):
    texture = re.match(r'texture_2d\(\s*"([^"]+)"', text)
    if texture:
        return ("asset", texture.group(1))
    colour = re.match(r"(?:color|float3)\(\s*(%s)\s*(?:,\s*(%s)\s*,\s*(%s)\s*)?\)$" % ((_NUMBER,) * 3), text)
    if colour:
        values = [float(v.rstrip("f")) for v in colour.groups() if v is not None]
        return tuple(values * 3 if len(values) == 1 else values)
    if text in ("true", "false"):
        return text == "true"
    if re.match(r"^%s$" % _NUMBER, text):
        return float(text.rstrip("f"))
    return None


def _beside(resolved_mdl, path):
    """The resolved path of 'path', written in the MDL at 'resolved_mdl': beside it, in its package if it is in one."""
    if resolved_mdl.endswith("]") and "[" in resolved_mdl:
        package, inner = resolved_mdl[:-1].split("[", 1)
        return "%s[%s]" % (package, os.path.normpath(os.path.join(os.path.dirname(inner), path)).replace(os.sep, "/"))
    return os.path.normpath(os.path.join(os.path.dirname(resolved_mdl), path))


def _omni(kind, arguments, surface, looks):
    """'surface' from the arguments of one of NVIDIA's materials: OmniPBR, OmniGlass or OmniSurface.

    An argument is a value (a preset's), or a channel (a shader input's).
    """

    def channel(name, colour, default=None):
        value = arguments.get(name)
        if value is None:
            return None if default is None else _constant(default)
        if isinstance(value, tuple) and value and value[0] in ("constant", "texture", "primvar"):
            return value
        if isinstance(value, tuple) and value and value[0] == "asset":
            return ("texture", value[1], (0, 1, 2) if colour else (0,), "st", (1.0,) * 4, (0.0,) * 4, None, colour)
        return _constant(value)

    def asset(name, channels, colour):
        value = arguments.get(name)
        if isinstance(value, tuple) and value and value[0] == "asset":
            return ("texture", value[1], channels, "st", (1.0,) * 4, (0.0,) * 4, None, colour)
        if isinstance(value, tuple) and value and value[0] == "texture":
            return value[:2] + (channels,) + value[3:7] + (colour,)
        if isinstance(value, tuple) and value and value[0] == "constant" and hasattr(value[1], "path"):
            return ("texture", value[1].resolvedPath, channels, "st", (1.0,) * 4, (0.0,) * 4, None, colour)
        return None

    if kind == "OmniPBR":
        surface.color = asset("diffuse_texture", (0, 1, 2), True) or channel(
            "diffuse_color_constant", True, (0.2, 0.2, 0.2)
        )
        # OmniPBR's albedo: the texture's colour, or the constant, times its
        # tint, plus its 'albedo_add', times its 'albedo_brightness'.
        tint = _vector(arguments.get("diffuse_tint"), (1.0, 1.0, 1.0))
        add = _number(arguments.get("albedo_add"), 0.0)
        brightness = _number(arguments.get("albedo_brightness"), 1.0)
        if surface.color[0] == "constant":
            base = _vector(surface.color[1], (0.2, 0.2, 0.2))
            surface.color = _constant(tuple((c * t + add) * brightness for c, t in zip(base, tint)))
        elif surface.color[0] == "texture":
            scale = tuple(t * brightness for t in tint) + (1.0,)
            bias = (add * brightness,) * 3 + (0.0,)
            surface.color = surface.color[:4] + (scale, bias) + surface.color[6:]
        orm = asset("ORM_texture", (1,), False) if _flag(arguments.get("enable_ORM_texture")) else None
        rough = channel("reflection_roughness_constant", False, 0.5)
        if orm is not None and _number(arguments.get("reflection_roughness_texture_influence"), 0.0) > 0.5:
            rough = orm
        elif _number(arguments.get("reflection_roughness_texture_influence"), 0.0) > 0.5:
            rough = asset("reflectionroughness_texture", (0,), False) or rough
        surface.roughness = rough
        metal = channel("metallic_constant", False, 0.0)
        if orm is not None and _number(arguments.get("metallic_texture_influence"), 0.0) > 0.5:
            metal = orm[:2] + ((2,),) + orm[3:]
        elif _number(arguments.get("metallic_texture_influence"), 0.0) > 0.5:
            metal = asset("metallic_texture", (0,), False) or metal
        surface.metallic = metal
        if _flag(arguments.get("enable_opacity")):
            surface.opacity = channel("opacity_constant", False, 1.0)
    elif kind == "OmniGlass":
        tint = _vector(arguments.get("glass_color"), (1.0, 1.0, 1.0))
        surface.color = _constant(tuple(0.3 + 0.7 * c for c in tint))
        surface.opacity = _constant(0.25)
        surface.roughness = channel("frosting_roughness", False, 0.05)
        surface.metallic = _constant(0.0)
    elif kind == "OmniSurface":
        surface.color = asset("diffuse_reflection_color_image", (0, 1, 2), True) or channel(
            "diffuse_reflection_color", True, (0.8, 0.8, 0.8)
        )
        surface.roughness = channel("specular_reflection_roughness", False, 0.2)
        surface.metallic = channel("metalness", False, 0.0)
        if _flag(arguments.get("enable_specular_transmission")):
            weight = _number(arguments.get("specular_transmission_weight"), 0.0)
            surface.opacity = _constant(1.0 - 0.7 * weight)


def _vector(value, default):
    """A colour of an MDL argument - a value, or a constant channel of one - as three floats; 'default' if none."""
    if isinstance(value, tuple) and value and value[0] == "constant":
        value = value[1]
    if isinstance(value, tuple) and len(value) >= 3:
        try:
            return tuple(float(v) for v in value[:3])
        except (TypeError, ValueError):
            return default
    return default


def _flag(value):
    if isinstance(value, tuple) and value and value[0] == "constant":
        value = value[1]
    return bool(value) if value is not None else False


def _number(value, default):
    if isinstance(value, tuple) and value and value[0] == "constant":
        value = value[1]
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# -- reading -------------------------------------------------------------------------


def read_bytes(resolved):
    """The bytes of the file at 'resolved' - 'package.usdz[inner]' for one in a package - or None.

    A package in a package is 'outer.usdz[inner.usdz[file]]', as Ar writes it.
    """
    try:
        if resolved.endswith("]") and "[" in resolved:
            package, inner = resolved[:-1].split("[", 1)
            with zipfile.ZipFile(package) as z:
                return _member(z, inner)
        with open(resolved, "rb") as f:
            return f.read()
    except (OSError, KeyError, zipfile.BadZipFile, ValueError):
        return None


def _member(archive, inner):
    """The bytes of 'inner' in the open package 'archive': a file's name, or 'package[inner]' for one in a package."""
    if inner.endswith("]") and "[" in inner:
        nested, rest = inner[:-1].split("[", 1)
        with zipfile.ZipFile(io.BytesIO(archive.read(nested))) as z:
            return _member(z, rest)
    return archive.read(inner)


def _read_image(resolved):
    import numpy

    data = read_bytes(resolved)
    if not data:
        return None
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            image.draft("RGB", (IMAGE_SIDE, IMAGE_SIDE))  # a JPEG decodes smaller at once
            if image.size[0] * image.size[1] > MAX_DECODED_PIXELS:
                return None
            image = image.convert("RGBA")
            image.thumbnail((IMAGE_SIDE, IMAGE_SIDE), Image.Resampling.BOX)
            return numpy.asarray(image, dtype=numpy.float64) / 255.0
    except Exception:  # not an image Pillow reads (EXR, Ptex, ...), or no Pillow
        return None


def _plain(value):
    """A USD value as plain Python: a vector as a tuple of floats, a number as a float."""
    if value is None:
        return None
    if hasattr(value, "__len__") and not isinstance(value, str):
        try:
            return tuple(float(v) for v in value)
        except (TypeError, ValueError):
            return value
    if isinstance(value, bool):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


def _value(node, name, time, default):
    given = node.GetInput(name)
    value = given.Get(time) if given else None
    return default if value is None else _plain(value)


def _physics_material(prim, UsdShade):
    """The name of the material a physics binding names for 'prim', or None."""
    try:
        relation = UsdShade.MaterialBindingAPI(prim).GetDirectBindingRel("physics")
        targets = relation.GetTargets() if relation else []
        return targets[0].name if targets else None
    except Exception:
        return None


def _primvar(prim, name, time, faces, corners, points):
    """The primvar 'name' of 'prim' for each triangle (the mean of its corners'), as rows; None where it has none."""
    import numpy
    from pxr import UsdGeom

    primvars = UsdGeom.PrimvarsAPI(prim)
    primvar = primvars.FindPrimvarWithInheritance(name) if hasattr(primvars, "FindPrimvarWithInheritance") else None
    if not primvar:
        primvar = primvars.GetPrimvar(name)
    if not primvar or not primvar.HasValue():
        return None
    values = primvar.ComputeFlattened(time)
    if values is None or len(values) == 0:
        return None
    values = numpy.asarray(values, dtype=numpy.float64)
    if values.ndim == 1:
        values = values[:, None]
    interpolation = primvar.GetInterpolation()
    try:
        if interpolation == UsdGeom.Tokens.constant or len(values) == 1:
            return numpy.repeat(values[:1], len(faces), axis=0)
        if interpolation == UsdGeom.Tokens.uniform:
            return values[faces]
        if interpolation in (UsdGeom.Tokens.vertex, UsdGeom.Tokens.varying):
            return values[points].mean(axis=1)
        if interpolation == UsdGeom.Tokens.faceVarying:
            return values[corners].mean(axis=1)
    except IndexError:
        return None
    return None


def _any_uv(prim, time, faces, corners, points):
    """The first texture-coordinate primvar of 'prim', for each triangle: what a texture with no 'st' is laid by."""
    from pxr import Sdf, UsdGeom

    for primvar in UsdGeom.PrimvarsAPI(prim).GetPrimvarsWithValues():
        if primvar.GetTypeName() in (Sdf.ValueTypeNames.TexCoord2fArray, Sdf.ValueTypeNames.Float2Array):
            values = _primvar(prim, primvar.GetPrimvarName(), time, faces, corners, points)
            if values is not None:
                return values
    return None


def _fit(value, width, count):
    """'value' - a number or a vector - as 'count' rows of 'width'."""
    import numpy

    value = numpy.atleast_1d(value).astype(numpy.float64)
    if len(value) < width:
        value = numpy.resize(value, width)
    return numpy.repeat(value[None, :width], count, axis=0)


def _fit_rows(values, width):
    import numpy

    if values.shape[1] >= width:
        return values[:, :width]
    return numpy.repeat(values[:, :1], width, axis=1)
