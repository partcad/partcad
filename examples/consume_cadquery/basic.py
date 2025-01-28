import cadquery as cq
import partcad as pc

part = pc.get_part_cadquery(
    "//pub/std/metric/cqwarehouse:fastener/hexhead-iso4014",
)

show_object(part)
