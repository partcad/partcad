import sdf
import partcad as pc

part = pc.get_part_sdf(
    "//pub/examples/partcad/feature_convert/sdf:box",
)

show_object(part)
