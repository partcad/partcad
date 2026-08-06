#
# The 'box' partType wrapper (kind: wrapper).
#
# Run inside the PartCAD sandbox by wrappers/wrapper_part_type.py with the part
# 'request' in globals and the run name '__partcad_part__'. It builds a shape
# and leaves it in the global 'output'.
#
if __name__ == "__partcad_part__":
    from build123d import Box

    size = float(request["parameters"].get("size", 10))  # noqa: F821 - injected
    output = {"shape": Box(size, size, size).wrapped}
