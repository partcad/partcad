@cli @pc-render
Feature: `pc render` command

  Background: Sandbox
    Given I am in "/tmp/sandbox/behave" directory
    Given I have temporary $HOME in "/tmp/sandbox/home"
    Given a file named "partcad.yaml" does not exist

  @success @pc-render @pc-render-parametrized
  Scenario: Each reading of one drawing renders to a file of its own
    # A sketch read with particular parameter values is an object of its own -
    # 'examples/produce_part_sheet_metal' holds one DXF with two bend lines on
    # two layers, and three parts read it: one folded at each line, and one
    # folded at both - and the file each reading is written to is named after
    # it, parameters and all. Both ';' and '=' are legal in a filename
    # everywhere PartCAD runs; '/' and ':' are the ones that are not, and
    # neither can appear in an object name.
    #
    # What this rules out is the two ways it could go wrong: a reading that
    # writes nothing, and readings that write over each other or over the
    # projection of the drawing itself.
    # Written with the multi-line form and *double* quotes on purpose. A
    # parameterized name holds ';', which a POSIX shell reads as a command
    # separator, so it has to be quoted -- and these commands run through
    # 'subprocess.run(shell=True)', which is 'cmd.exe' on Windows, where "'"
    # quotes nothing and would be passed through as part of the name. The
    # object would then begin "'" rather than ':', 'resolve_resource_path'
    # would cut the package at the ':' after it, and the render would be asked
    # for a package named "'".
    When I run command
      """
      pc --no-ansi -p $PARTCAD_ROOT/examples render --package //produce_part_sheet_metal -t svg -O ./ -s ":panel;include=BEND_UP"
      """
    Then the command should exit with a status code of "0"
    When I run command
      """
      pc --no-ansi -p $PARTCAD_ROOT/examples render --package //produce_part_sheet_metal -t svg -O ./ -s ":panel;include=BEND_DOWN"
      """
    Then the command should exit with a status code of "0"
    When I run command
      """
      pc --no-ansi -p $PARTCAD_ROOT/examples render --package //produce_part_sheet_metal -t svg -O ./ -s ":panel;include=BEND_UP,BEND_DOWN"
      """
    Then the command should exit with a status code of "0"
    Then a file named "panel;include=BEND_UP.svg" should be created
    And a file named "panel;include=BEND_DOWN.svg" should be created
    And a file named "panel;include=BEND_UP,BEND_DOWN.svg" should be created
    # Nobody asked for the drawing itself, and nothing wrote it: a reading that
    # lost its parameters on the way to a filename would have landed here.
    And a file named "panel.svg" should not exist

  Scenario Outline: `pc render` command
    When I run "pc --no-ansi -p $PARTCAD_ROOT/examples render --package /produce_assembly_assy -t <type> -O ./ -a :logo_embedded"
    Then the command should exit with a status code of "0"
    Then a file named "<filename>" should be created
    Given a file named "partcad.yaml" does not exist
    Then STDERR should contain "DONE: Render: //pub/examples/partcad/produce_assembly_assy:"
    Then STDERR should not contain "WARN:"

  # TODO-63: @alexanderilyin: consider extracting `-t readme` as `pc generate readme` command
  # An assembly is the subject of its own document (its bill of materials),
  # rather than of the package document that `-t readme` generates without `-a`.
  @type-text
  Examples: Media Types: Text
    |    type | filename              |
    |  readme | logo_embedded.md      |

  @type-image
  Examples: Media Type: .svg
    |    type | filename              |
    |     svg | logo_embedded.svg     |

  @type-image
  Examples: Media Type: .png
    |    type | filename              |
    |     png | logo_embedded.png     |

  @type-image
  Examples: Media Type: .jpg
    |    type | filename              |
    |    jpeg | logo_embedded.jpg     |

  # The assembly instruction book: the same document laid out on paper and as
  # pages to flip through. The examples package declares itself
  # `manufacturable: false`, so generating one takes the flag that says so.
  #
  # `primitive` rather than `logo_embedded`: an instruction book renders an
  # illustration per item and per step, and this one is the smallest assembly
  # that still has a step in it. What the steps themselves look like is covered
  # by the unit tests, which do not pay the cost of a CLI round trip.
  Scenario Outline: `pc render` of an assembly instruction book
    When I run "pc --no-ansi -p $PARTCAD_ROOT/examples render --package /produce_assembly_assy -t <type> --ignore-manufacturability -O ./ -a :primitive"
    Then the command should exit with a status code of "0"
    Then a file named "<filename>" should be created
    Given a file named "partcad.yaml" does not exist
    Then STDERR should contain "DONE: Render: //pub/examples/partcad/produce_assembly_assy:"

    @type-guide
    Examples: Media Types: Assembly instructions
      |    type | filename          |
      |     pdf | primitive.pdf     |
      |    html | primitive.html    |

  # A port is a coordinate frame and an interface is a named set of them, so
  # neither is geometry and neither reaches a drawing without being asked for.
  # `feature_interface` is the example that has them.
  @type-image
  Scenario Outline: `pc render` draws the ports and the interfaces
    When I run "pc --no-ansi -p $PARTCAD_ROOT/examples render --package //feature_interface -t png -O ./ <option> example-bracket"
    Then the command should exit with a status code of "0"
    Then a file named "example-bracket.png" should be created
    Given a file named "partcad.yaml" does not exist
    # The report names which of the two overlays this invocation resolved to,
    # so each option is told apart from the others rather than only from none.
    Then STDERR should contain "<reported>: 10 port(s) drawn on the projection"
    # Every port drawn is also named in the log, where it can be copied from
    # into an ASSY file.
    Then STDERR should contain "L-30mm-slotted-3mm-thru-opening-m4"

    Examples: The three ways to ask
      |            option |                           reported |
      |      --with-ports |                       --with-ports |
      | --with-interfaces |                  --with-interfaces |
      |        --with-all | --with-ports and --with-interfaces |

  # What the options put in the file, rather than in the log: the projection
  # gains a layer per overlay, and only for the overlay that was asked for. SVG
  # because it is the format that says so in text; the other three are the same
  # projection converted (see `//builtin/render`).
  #
  # `--with-internals` because the object is an assembly and this one
  # externalizes nothing: an assembly is taken at its word, so the ports being
  # drawn here are the ones inside it (see "Ports and interfaces of an
  # assembly").
  @type-image
  Scenario Outline: `pc render` writes a layer per overlay
    When I run "pc --no-ansi -p $PARTCAD_ROOT/examples render --package //feature_interface -t svg -O ./ -a --with-internals <option> connect-mates"
    Then the command should exit with a status code of "0"
    Then a file named "connect-mates.svg" should be created
    Given a file named "partcad.yaml" does not exist
    # The layer names of the projection, which is where they appear and the
    # only place they do: the port names themselves are drawn as line segments.
    Then a file named "connect-mates.svg" should contain "Visible"
    Then a file named "connect-mates.svg" should contain "<present>"
    Then a file named "connect-mates.svg" should not contain "<absent>"

    Examples: One overlay at a time
      |            option |    present |     absent |
      |      --with-ports |      Ports | Interfaces |
      | --with-interfaces | Interfaces |      Ports |

  # Naming one object renders that object. The package holds four assemblies,
  # three more parts and three sketches, none of which was asked for.
  @type-image
  Scenario: `pc render` of one object renders only that object
    When I run "pc --no-ansi -p $PARTCAD_ROOT/examples render --package //feature_interface -t png -O ./ example-bracket"
    Then the command should exit with a status code of "0"
    Then a file named "example-bracket.png" should be created
    Given a file named "partcad.yaml" does not exist
    Then a file named "example-motor.png" should not exist
    Then a file named "socket-head-m3-screw-6mm.png" should not exist
    Then a file named "socket-head-m4-screw-6mm.png" should not exist
    Then a file named "connect-ports.png" should not exist
    Then a file named "connect-interfaces.png" should not exist
    Then a file named "connect-mates.png" should not exist
    Then a file named "connect-instructions.png" should not exist
    Then a file named "m3.png" should not exist
    Then a file named "m4.png" should not exist
    Then a file named "m5.png" should not exist

  # The viewing angle of a projection. `--view` is shorthand for the
  # `viewport_origin`/`viewport_up` pair a `render:` file type is configured
  # with, so what is worth a CLI round trip here is that the option survives one
  # and reaches the implementation. Which way each name points, and that the
  # override beats the configuration, are unit tests.
  #
  # `feature_render:cylinder` rather than any other part: it configures a
  # viewport of its own, so a render that ignored `--view` would still succeed
  # and this would still be looking at the picture the package asked for.
  @type-image
  Scenario: `pc render --view` aims the projection
    When I run "pc --no-ansi -p $PARTCAD_ROOT/examples render --package //feature_render -t svg --view front -O ./ :cylinder"
    Then the command should exit with a status code of "0"
    Then a file named "cylinder.svg" should be created
    Given a file named "partcad.yaml" does not exist
    Then STDERR should contain "DONE: Render: //pub/examples/partcad/feature_render:"

  # A request that cannot be aimed is refused before anything is rendered,
  # rather than producing a picture of something else.
  Scenario Outline: `pc render` refuses a viewport it cannot make sense of
    When I run "pc --no-ansi -p $PARTCAD_ROOT/examples render --package //feature_render -t svg <options> -O ./ :cylinder"
    Then the command should exit with a status code of "2"
    Then a file named "cylinder.svg" should not exist

    Examples: Bad viewports
      |                    options |
      |          --view isometric  |
      |      --viewport-origin 1,2 |
      |        --viewport-up 0,0,0 |

  # A name with a "/" in it is a projection in a sub-directory of that name,
  # created on the way -- the same thing `pc export` does with the file it
  # writes. `feature_import` declares its parts that way in `partcad.yaml`.
  @type-image
  Scenario: `pc render` of a part whose name has a "/" in it
    When I run "pc --no-ansi -p $PARTCAD_ROOT/examples render --package //feature_import -t svg -O ./ :AeroAssembly_assy_example/AeroFrame_Cap"
    Then the command should exit with a status code of "0"
    Then a file named "AeroAssembly_assy_example/AeroFrame_Cap.svg" should be created
    Given a file named "partcad.yaml" does not exist
    Then STDERR should contain "DONE: Render: //pub/examples/partcad/feature_import:"

  @type-guide
  Scenario: `pc render -t pdf` refuses an assembly that is not meant to be built
    When I run "pc --no-ansi -p $PARTCAD_ROOT/examples render --package /produce_assembly_assy -t pdf -O ./ -a :primitive"
    Then the command should exit with a status code of "2"
    Then STDERR should contain "--ignore-manufacturability"
    Then a file named "primitive.pdf" should not exist


# pc -p $PARTCAD_ROOT/examples render --package /produce_assembly_assy -t readme -a :logo_embedded
# pc -p $PARTCAD_ROOT/examples render --package /produce_assembly_assy -t svg -a :logo_embedded
# pc -p $PARTCAD_ROOT/examples render --package /produce_assembly_assy -t png -a :logo_embedded
# pc -p $PARTCAD_ROOT/examples render --package /produce_assembly_assy -t step -a :logo_embedded
# pc -p $PARTCAD_ROOT/examples render --package /produce_assembly_assy -t stl -a :logo_embedded
# pc -p $PARTCAD_ROOT/examples render --package /produce_assembly_assy -t 3mf -a :logo_embedded
# pc -p $PARTCAD_ROOT/examples render --package /produce_assembly_assy -t threejs -a :logo_embedded
# pc -p $PARTCAD_ROOT/examples render --package /produce_assembly_assy -t obj -a :logo_embedded
# pc -p $PARTCAD_ROOT/examples render --package /produce_assembly_assy -t gltf -a :logo_embedded
# pc -p $PARTCAD_ROOT/examples render --package /produce_assembly_assy -t iges -a :logo_embedded

# ⬢ [Docker] ❯ pc -p $PARTCAD_ROOT/examples render --package /produce_assembly_assy -t readme -O $PWD -a :logo_embedded
# INFO:  DONE: InitCtx: $PARTCAD_ROOT/examples: 0.01s
# WARN: Skipping rendering of logo: no image found at ./logo.svg
# WARN: Skipping rendering of logo_embedded: no image found at ./logo_embedded.svg
# WARN: Skipping rendering of partcad_logo: no image found at ./logo.svg
# WARN: Skipping rendering of partcad_logo_short: no image found at ./logo.svg
# WARN: Skipping rendering of primitive: no image found at ./primitive.svg
# INFO:  DONE: Render: //pub/examples/partcad/produce_assembly_assy: 0.02s
