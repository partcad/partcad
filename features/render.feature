@cli @pc-render
Feature: `pc render` command

  Background: Sandbox
    Given I am in "/tmp/sandbox/behave" directory
    Given I have temporary $HOME in "/tmp/sandbox/home"
    Given a file named "partcad.yaml" does not exist

  Scenario Outline: `pc render` command
    When I run "partcad -p /workspaces/partcad/examples render --package /produce_assembly_assy -t <type> -O ./ -a :logo_embedded"
    Then the command should exit with a status code of "0"
    Then a file named "<filename>" should be created
    Given a file named "partcad.yaml" does not exist
    Then STDOUT should contain "DONE: Render: this:"
    Then STDOUT should not contain "WARN:"

  # TODO: @openvmp: consider extracting `-t readme` as `pc generate readme` command
  # @wip @type-text
  # Examples: Media Types: Text
    # |    type | filename              |
    # |  readme | README.md             |

  # @type-image
  # Examples: Media Types: Image
    # |    type | filename              |
    # |     svg | logo_embedded.svg     |
    # |     png | logo_embedded.png     |

  @type-object
  Examples: Media Types: Object
    |    type | filename              |
    # |    step | logo_embedded.step    |
    # |     stl | logo_embedded.stl     |
    # |     3mf | logo_embedded.3mf     |
    | threejs | logo_embedded.json    |
    # |     obj | logo_embedded.obj     |
    |    gltf | logo_embedded.json    |


# pc render -t png -a $assembly
# pc render -t png $part
# pc render -t step -a <assembly path>
# pc render -t stl :test
# pc render -t stl <part path>



# pc -p /workspaces/partcad/examples render --package /produce_assembly_assy -t readme -a :logo_embedded
# pc -p /workspaces/partcad/examples render --package /produce_assembly_assy -t svg -a :logo_embedded
# pc -p /workspaces/partcad/examples render --package /produce_assembly_assy -t png -a :logo_embedded
# pc -p /workspaces/partcad/examples render --package /produce_assembly_assy -t step -a :logo_embedded
# pc -p /workspaces/partcad/examples render --package /produce_assembly_assy -t stl -a :logo_embedded
# pc -p /workspaces/partcad/examples render --package /produce_assembly_assy -t 3mf -a :logo_embedded
# pc -p /workspaces/partcad/examples render --package /produce_assembly_assy -t threejs -a :logo_embedded
# pc -p /workspaces/partcad/examples render --package /produce_assembly_assy -t obj -a :logo_embedded
# pc -p /workspaces/partcad/examples render --package /produce_assembly_assy -t gltf -a :logo_embedded

# ⬢ [Docker] ❯ pc -p /workspaces/partcad/examples render --package /produce_assembly_assy -t readme -O $PWD -a :logo_embedded
# INFO:  DONE: InitCtx: /workspaces/partcad/examples: 0.01s
# WARN: Skipping rendering of logo: no image found at ./logo.svg
# WARN: Skipping rendering of logo_embedded: no image found at ./logo_embedded.svg
# WARN: Skipping rendering of partcad_logo: no image found at ./logo.svg
# WARN: Skipping rendering of partcad_logo_short: no image found at ./logo.svg
# WARN: Skipping rendering of primitive: no image found at ./primitive.svg
# INFO:  DONE: Render: this: 0.02s
