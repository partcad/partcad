import sdf
import partcad as pc

part = pc.get_part_sdf(
    "//pub/examples/partcad/produce_part_sdf:box",
)

show_object(part)
