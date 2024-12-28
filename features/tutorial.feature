@cli @pc-render
Feature: `pc render` command

  Background: Sandbox
    Given I am in "/tmp/sandbox/behave" directory
    Given I have temporary $HOME in "/tmp/sandbox/home"

  Scenario: Tutorial
    When I run "pc init"
    Then the command should exit with a status code of "0"
    When I run command:
      """
      cat <<EOF > partcad.yaml
      import:
        # Public PartCAD repository (reference it explicitly if required)
        pub:
          type: git
          url: https://github.com/partcad/partcad-index.git
      EOF
      """
    Then the command should exit with a status code of "0"
    # When I run "pc init"
    # Then the command should exit with a status code of "0"
    When I run "pc list"
    Then the command should exit with a status code of "0"
    When I run "echo "translate (v= [0,0,0])  cube (size = 10);" > test.scad"
    Then the command should exit with a status code of "0"
    When I run "pc add part scad test.scad"
    Then the command should exit with a status code of "0"
    When I run "pc inspect :test"
    Then the command should exit with a status code of "0"
    When I run "pc render -t stl :test"
    Then the command should exit with a status code of "0"
