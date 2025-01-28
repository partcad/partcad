import build123d as b3d
import partcad as pc

part = pc.get_part_build123d(
    "//pub/std/metric/cqwarehouse:fastener/hexhead-iso4014",
)

show_object(part)
