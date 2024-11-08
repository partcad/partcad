@wip @cli @pc-render
Feature: `pc inspect` command

  Background: Sandbox
    Given I am in "/tmp/sandbox/behave" directory
    Given I have temporary $HOME in "/tmp/sandbox/home"
    Given a file named "partcad.yaml" does not exist

  Scenario Outline: `pc inspect -i` command
    Given steps for testing

  Scenario Outline: `pc inspect -a` command
    When I run "partcad -p /workspaces/partcad/examples inspect -a -V --package <package> <part>"
    Then the command should exit with a status code of "0"      
    Then STDOUT should contain "DONE: Inspect: this:"
    Then STDOUT should not contain "WARN:"
    Then STDOUT should not contain "ERROR:"

  # for PACKAGE in $(find /workspaces/partcad/examples/produce_assembly_* -type d -print); do for SKETCH in $(yq -r '.assemblies | keys[]' $PACKAGE/partcad.yaml); do echo "| $PACKAGE | $SKETCH |"; done; done;
  @assembly
  Examples: Assembly
    | package | part |
    | /produce_assembly_assy | logo |
    | /produce_assembly_assy | logo_embedded |
    | /produce_assembly_assy | partcad_logo |
    | /produce_assembly_assy | partcad_logo_short |
    | /produce_assembly_assy | primitive |

  Scenario Outline: `pc inspect -s` command
    When I run "partcad -p /workspaces/partcad/examples inspect -s -V --package <package> <part>"
    Then the command should exit with a status code of "0"      
    Then STDOUT should contain "DONE: Inspect: this:"
    Then STDOUT should not contain "WARN:"
    Then STDOUT should not contain "ERROR:"

  # for PACKAGE in $(find /workspaces/partcad/examples/produce_sketch_* -type d -print); do for SKETCH in $(yq -r '.sketches | keys[]' $PACKAGE/partcad.yaml); do echo "| $PACKAGE | $SKETCH |"; done; done;

  @basic
  Examples: Sketch: basic
    | package | part |
    | /produce_sketch_basic | circle_01 |
    | /produce_sketch_basic | circle_02 |
    | /produce_sketch_basic | circle_03 |
    | /produce_sketch_basic | rect_01 |
    | /produce_sketch_basic | square_01 |

  @basic
  Examples: Sketch: basic
    | package | part |
    | /produce_sketch_build123d | clock |

  @cadquery
  Examples: Sketch: CadQuery
    | package | part |
    | /produce_sketch_cadquery | sketch |

  @dxf
  Examples: Sketch: dxf
    | package | part |
    | /produce_sketch_dxf | dxf_01 |

  @svg
  Examples: Sketch: svg
    | package | part |
    | /produce_sketch_svg | svg_01 |  

  Scenario Outline: `pc inspect` command
    When I run "partcad -p /workspaces/partcad/examples inspect -V --package <package> <part>"
    Then the command should exit with a status code of "0"      
    Then STDOUT should contain "DONE: Inspect: this:"
    Then STDOUT should not contain "WARN:"
    Then STDOUT should not contain "ERROR:"

  # for PACKAGE in $(find /workspaces/partcad/examples/produce_part_* -type d -print); do for PART in $(yq -r '.parts | keys[]' $PACKAGE/partcad.yaml); do echo "| $PACKAGE | $PART |"; done; done;

  @3mf
  Examples: Part: 3mf
    | package | part |
    | /produce_part_3mf | cube |

  @ai @build123d
  Examples: Part: build123d [AI]
    | package | part |
    | /produce_part_ai_build123d | cube |
    | /produce_part_ai_build123d | prism |
    | /produce_part_ai_build123d | tetrahedron |

  @ai @cadquery
  Examples: Part: CadQuery [AI]
    | package | part |
    | /produce_part_ai_cadquery | cube |
    | /produce_part_ai_cadquery | prism |
    | /produce_part_ai_cadquery | tetrahedron |

  @ai @openscad
  Examples: Part: OpenSCAD [AI]
    | package | part |
    | /produce_part_ai_openscad | cube |
    | /produce_part_ai_openscad | prism |
    | /produce_part_ai_openscad | tetrahedron |

  @build123d
  Examples: Part: build123d
    | package | part |
    | /produce_part_build123d_primitive | cube |

  @cadquery
  Examples: Part: cadquery
    | package | part |
    | /produce_part_cadquery_logo | bone |
    | /produce_part_cadquery_logo | head_half |
    | /produce_part_cadquery_primitive | brick |
    | /produce_part_cadquery_primitive | cube |
    | /produce_part_cadquery_primitive | cylinder |

  @extrude
  Examples: Part: extrude
    | package | part |
    | /produce_part_extrude | clock |
    | /produce_part_extrude | cylinder |
    | /produce_part_extrude | dxf |

  @openscad
  Examples: Part: OpenSCAD
    | package | part |
    | /produce_part_openscad | cube |

  @step
  Examples: Part: step
    | package | part |
    | /produce_part_step | bolt |
    | /produce_part_step | fastener |
    | /produce_part_step | screw |

  @stl
  Examples: Part: stl
    | package | part |
    | /produce_part_stl | cube |  
