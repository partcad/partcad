@cli @pc-export
Feature: `pc export` command

  Background: Sandbox
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"
    And a file named "partcad.yaml" does not exist

  Scenario Outline: `pc export` command
    When I run "pc --no-ansi -p $PARTCAD_ROOT/examples export --package /produce_assembly_assy -t <type> -O ./ -a :logo_embedded"
    Then the command should exit with a status code of "0"
    And a file named "<filename>" should be created
    And a file named "partcad.yaml" should not exist
    And STDERR should contain "DONE: Export: this:"
    And STDERR should not contain "WARN:"

  @type-object
  Examples: Media Type: .step
    |    type | filename              |
    |    step | logo_embedded.step    |

  @type-object
  Examples: Media Type: .stl
    |    type | filename              |
    |     stl | logo_embedded.stl     |

  @type-object
  Examples: Media Type: .3mf
    |    type | filename              |
    |     3mf | logo_embedded.3mf     |

  @type-object
  Examples: Media Type: .json (Three.js)
    |    type | filename              |
    | threejs | logo_embedded.json    |

  @type-object
  Examples: Media Type: .obj
    |    type | filename              |
    |     obj | logo_embedded.obj     |

  @type-object
  Examples: Media Type: .json (glTF)
    |    type | filename              |
    |    gltf | logo_embedded.json    |

  @type-object
  Examples: Media Type: .iges
    |    type | filename              |
    |    gltf | logo_embedded.iges    |
