import build123d as bd

# A 100 x 10 x 10 mm bar, centred on the origin and lying along X, so it runs
# from x = -50 (the clamped root) to x = +50 (the loaded tip). Centred rather
# than aligned to a face on purpose: `Box` centres by default, and a validation
# case is the last place to spend correctness on a nicety of placement.
with bd.BuildPart() as result:
    bd.Box(100, 10, 10)

if "show_object" in locals():
    show_object(result.part.wrapped, name="cantilever")
