import cadquery as cq

width = 3.0
length = 4.0

sk1 = cq.Sketch().rect(width, length).push([(0, 0.75), (0, -0.75)]).regularPolygon(0.5, 6, 90, mode="s")

result = cq.Workplane("front").placeSketch(sk1)
show_object(result)
