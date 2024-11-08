s = 10; // side length of the hexagonal base
h = 10; // height of the prism

r_outer = s / sqrt(3);

module hexagon(s) {
    polygon(points=[
        [s/2, 0],
        [s/4, s*sqrt(3)/2],
        [-s/4, s*sqrt(3)/2],
        [-s/2, 0],
        [-s/4, -s*sqrt(3)/2],
        [s/4, -s*sqrt(3)/2]
    ]);
}

module hexagonal_prism(s, h) {
    linear_extrude(height=h)
        hexagon(s);
}

hexagonal_prism(s, h);
