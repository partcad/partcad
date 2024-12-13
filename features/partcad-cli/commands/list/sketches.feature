@cli @add-assembly
Feature: `pc list assemblies` command

  Background: Initialize sandbox
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"

  Scenario: Add assembly from `logo.assy` file
    When I run command:
      """
      cat << EOF > partcad.yaml
      sketches:
        circle_01:
          type: basic
          desc: The shortest way to create a basic circle in PartCAD
          circle: 5
      EOF
      """
    Then the command should exit with a status code of "0"
    When I run command:
      """
      cat << EOF > circle_01.svg
      <?xml version='1.0' encoding='utf-8'?>
      <svg width="513.0mm" height="296.6033378253mm" viewBox="-5.009765625 -2.8965169709 10.01953125 5.7930339419" version="1.1" xmlns="http://www.w3.org/2000/svg">
        <g transform="scale(1,-1)" stroke-linecap="round">
          <g fill="none" stroke="rgb(64,192,64)" stroke-width="0.01953125" id="Visible">
            <path d="M 3.5355339059,-2.0412414523 A 5.0,2.886751345948129 0.0 0,1 -3.5355339059,2.0412414523 A 5.0,2.886751345948129 0.0 0,1 3.5355339059,-2.0412414523" />
          </g>
        </g>
      </svg>
      EOF
      """
    Then the command should exit with a status code of "0"
    When I run command:
      """
      partcad list sketches
      """
    Then the command should exit with a status code of "0"
    Then STDOUT should contain "DONE: InitCtx:"
    Then STDOUT should contain "PartCAD sketches:"
    Then STDOUT should contain "circle_01"
    Then STDOUT should contain "The shortest way to create a basic circle in PartCAD"
    Then STDOUT should contain "Total: 1"
    Then STDOUT should contain "DONE: ListSketches: this:"

# Feature: List sketches recursively
#   As a PartCAD user
#   I want to list all sketches recursively
#   So that I can see the complete sketch hierarchy

#   Scenario: List sketches in a complex project
#     Given I have a project with nested sketches
#     When I run "pc list-sketches -r"
#     Then the command should succeed
#     And the output should contain all sketches in hierarchical order
#     And each sketch should display its parent-child relationships

#   Scenario: List sketches in an empty project
#     Given I have a project with no sketches
#     When I run "pc list-sketches -r"
#     Then the command should succeed
#     And the output should indicate no sketches found
