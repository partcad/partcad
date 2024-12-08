@cli @add-assembly
Feature: `pc add assembly` command

  Background: Initialize sandbox
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"

  Scenario: Add assembly from `logo.assy` file
    When I run command:
      """
      cat << EOF > partcad.yaml
      parts:
        cube:
          type: cadquery
          desc: This is a cube from examples
          parameters:
            width:
              default: 10.0
            length:
              default: 10.0
            height: 10.0
          aliases: ["box"]
        cylinder:
          type: cadquery
          path: cylinder.py
          desc: This is a cylinder from examples
      EOF
      """
    Then the command should exit with a status code of "0"
    When I run command:
      """
      cat << EOF > cylinder.py
      import cadquery as cq

      if __name__ != "__cqgi__":
          from cq_server.ui import ui, show_object

      shape = cq.Workplane("front").circle(10.0).extrude(10.0)
      show_object(shape)
      EOF
      """
    Then the command should exit with a status code of "0"
    When I run command:
      """
      cat << EOF > cube.py
      import cadquery as cq

      if __name__ != "__cqgi__":
          from cq_server.ui import ui, show_object

      width = 10.0
      length = 10.0
      height = 10.0

      shape = cq.Workplane("front").box(width, length, height)

      show_object(shape)
      EOF
      """
    Then the command should exit with a status code of "0"
    When I run command:
      """
      cat << EOF > primitive.assy
      links:
        - part: cube
          location: [[0,0,0], [0,0,1], 0]
        - part: cylinder
          location: [[0,0,5], [0,0,1], 0]
      EOF
      """
    Then the command should exit with a status code of "0"
    When I run command:
      """
      partcad add assembly assy primitive.assy
      """
    Then the command should exit with a status code of "0"
    # INFO:  Adding the assembly primitive.assy of type assy
    When I run command:
      """
      partcad inspect -V cube
      """
    Then the command should exit with a status code of "0"
    # ERROR: Error in ['/home/vscode/.partcad/runtime/partcad-python-conda-3.10/v-env-8a5edab282632443219e051e4ade2d1d5bbc671c781051bf1437897cbdfea0f1/bin/python', '-sOOIu', '-m', 'pip', 'install', 'numpy==1.26.4']: ERROR: pip's dependency resolver does not currently take into account all the packages that are installed. This behaviour is the source of the following dependency conflicts.
    When I run command:
      """
      partcad inspect -V cylinder
      """
    Then the command should exit with a status code of "0"
    When I run command:
      """
      partcad inspect -V primitive
      """
    Then the command should exit with a status code of "0"

#   Background: Initialize PartCAD project
#     Given I am in "/tmp/sandbox/behave" directory
#     And I have temporary $HOME in "/tmp/sandbox/home"
#     And a file named "partcad.yaml" does not exist
#     When I run "partcad --no-ansi init -p"
#     Then the command should exit with a status code of "0"
#     And a file named "partcad.yaml" should be created with content:
#       """
#       import:
#       parts:
#       assemblies:
#       """
# # TODO: Error case: Adding an assembly with invalid YAML syntax
# # TODO: Error case: Adding an assembly with non-existent referenced parts
# # TODO: Error case: Adding an assembly with duplicate name
# # TODO: Success case: Adding multiple assemblies
# # TODO: Success case: Adding an assembly with relative file paths

#   @ai-openscad
#   Scenario: Add assembly from `logo.assy` file
#     Given a file named "logo.assy" with content:
#       """
#       links:
#         - part: /produce_part_cadquery_logo:bone
#           location: [[0, 0, 0], [0, 0, 1], 0]
#         - part: /produce_part_cadquery_logo:bone
#           location: [[0, 0, -2.5], [0, 0, 1], -90]
#         - links:
#             - part: /produce_part_cadquery_logo:head_half
#               location: [[0, 0, 2.5], [0, 0, 1], 0]
#             - part: /produce_part_cadquery_logo:head_half
#               location: [[0, 0, 0], [0, 0, 1], -90]
#           location: [[0, 0, 25], [1, 0, 0], 0]
#         - part: /produce_part_step:bolt
#           package:
#           location: [[0, 0, 7.5], [0, 0, 1], 0]
#       """
#     When I run "partcad add-assembly assy logo.assy"
#     Then the command should exit with a status code of "0"
#     And a file named "partcad.yaml" should have YAML content:
#       """
#       import:
#       parts:
#       assemblies:
#         logo:
#           type: assy
#       """

#   @ai-openscad @failure
#   Scenario: Fail to add assembly with invalid YAML syntax
#     Given a file named "invalid.assy" with content:
#       """
#       links:
#         - this is not valid yaml
#       """
#     When I run "partcad add-assembly assy invalid.assy"
#     Then the command should exit with a status code of "1"
#     And STDERR should contain "Invalid YAML syntax"

#   @ai-openscad @failure
#   Scenario: Fail to add assembly with missing referenced parts
#     Given a file named "missing.assy" with content:
#       """
#       links:
#         - part: /nonexistent_part:bone
#           location: [[0, 0, 0], [0, 0, 1], 0]
#       """
#     When I run "partcad add-assembly assy missing.assy"
#     Then the command should exit with a status code of "1"
#     And STDERR should contain "Referenced part not found"
