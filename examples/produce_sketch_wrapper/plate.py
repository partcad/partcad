#
# The 'plate' sketchType (kind: wrapper).
#
# Run inside the PartCAD sandbox by wrappers/wrapper_part_type.py with the
# sketch's 'request' in globals and the run name '__partcad_sketch__'. It builds
# the sketch's geometry in the XY plane and leaves it in the global 'output':
# here a face with holes (one face, its holes inner wires) and an open wire
# made of a line and an arc. build123d objects are handed back as they are;
# OCP shapes would do as well.
#

# Raise with any change to what this produces (see 'partcad.code_version').
CACHE_VERSION = 1

if __name__ == "__partcad_sketch__":
    from build123d import Circle, Line, Pos, RectangleRounded, ThreePointArc, Wire

    parameters = request["parameters"]  # noqa: F821 - injected
    width = float(parameters.get("width", 40))
    height = float(parameters.get("height", 20))
    holes = max(0, int(parameters.get("holes", 2)))

    plate = RectangleRounded(width, height, height / 4)
    pitch = width / (holes + 1)
    for index in range(holes):
        plate -= Pos(-width / 2 + pitch * (index + 1), 0) * Circle(height / 8)

    # The bend line: open, so it stays a wire rather than becoming a face.
    y = height / 2 + 5
    bend = Wire(
        [
            Line((-width / 2, y), (0, y)),
            ThreePointArc((0, y), (width / 4, y + 5), (width / 2, y)),
        ]
    )
    output = {"shapes": [plate, bend]}
