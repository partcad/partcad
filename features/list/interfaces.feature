@cli @list-assemblies
Feature: `pc list interfaces` command

  Background: Initialize sandbox
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"

  Scenario: Configure m3 interface
    When I run command:
      """
      cat << EOF > partcad.yaml
      sketches:
        m3:
          type: basic
          circle: 1.5 # 1.5mm radius equals to 3mm diameter

      interfaces:
        m3:
          desc: Abstract 3mm circular interface
          abstract: True
          ports:
            m3:
              location: [[0, 0, 0], [0, 0, 1], 0] # redundant, for demonstration
              sketch: m3
      EOF
      """
    Then the command should exit with a status code of "0"
    When I run command:
      """
      partcad list interfaces
      """
    Then the command should exit with a status code of "0"
    Then STDOUT should contain "DONE: InitCtx:"
    Then STDOUT should contain "PartCAD interfaces:"
    Then STDOUT should contain "m3"
    Then STDOUT should contain "Abstract 3mm circular interface"
    Then STDOUT should contain "Total: 1"
    Then STDOUT should contain "DONE: ListInterfaces: //"

# Feature: List Interfaces Command
#   As a PartCAD user
#   I want to list interfaces recursively
#   So that I can view all available interfaces in the project

#   Scenario: List interfaces recursively
#     Given I have a PartCAD project with interfaces
#     When I run "pc list-interfaces -r"
#     Then I should see a list of all interfaces
#     And the output should include nested interfaces

#    Then the output should contain interface paths
#    And each interface should show its version
#    And nested interfaces should be indented
#    And the output should be sorted alphabetically
