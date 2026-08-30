@cli @pc-render
Feature: `pc render` command

  Background: Sandbox
    Given I am in "/tmp/sandbox/behave" directory
    Given I have temporary $HOME in "/tmp/sandbox/home"
    Given a file named "partcad.yaml" does not exist

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
    # Every port drawn is also named in the log, where it can be copied from
    # into an ASSY file.
    Then STDERR should contain "10 port(s) drawn on the projection"
    Then STDERR should contain "L-30mm-slotted-3mm-thru-opening-m4"

    Examples: The three ways to ask
      |            option |
      |      --with-ports |
      | --with-interfaces |
      |        --with-all |

  # Naming one object renders that object. The package holds four assemblies and
  # three more parts, none of which was asked for.
  @type-image
  Scenario: `pc render` of one object renders only that object
    When I run "pc --no-ansi -p $PARTCAD_ROOT/examples render --package //feature_interface -t png -O ./ example-bracket"
    Then the command should exit with a status code of "0"
    Then a file named "example-bracket.png" should be created
    Given a file named "partcad.yaml" does not exist
    Then a file named "connect-mates.png" should not exist
    Then a file named "example-motor.png" should not exist

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
