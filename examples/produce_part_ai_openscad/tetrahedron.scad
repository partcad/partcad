module tetrahedron(length) {
    // Define vertices of the tetrahedron
    verts = [
        [ length, 0, -1/sqrt(2)*length ], // vertex A
        [ -length, 0, -1/sqrt(2)*length ], // vertex B
        [ 0, length, 1/sqrt(2)*length ], // vertex C
        [ 0, -length, 1/sqrt(2)*length ] // vertex D
    ];

    // Define faces of the tetrahedron using vertex indices
    faces = [
        [0, 1, 2], // face ABC
        [0, 1, 3], // face ABD
        [0, 2, 3], // face ACD
        [1, 2, 3]  // face BCD
    ];

    // Create the tetrahedron
    polyhedron(verts, faces);
}

// Call the module with the given length
tetrahedron(10);
