
@pc
Feature: Handle monorepo paths properly

  Background:
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"
    And a directory named "package_a" exists
    And a directory named "package_b" exists


  @pc-help
  Scenario: Test list packages
    Given a file named "partcad.yaml" with content:
      """
      name: //
      desc: Root Package
      dependencies:
        dfrobot:
          type: git
          onlyInRoot: true
          url: https://github.com/partcad/partcad-robotics-part-vendor-dfrobot
      """
    And a file named "package_a/partcad.yaml" with content:
      """
      desc: Package A
      sketches:
        circle_a:
          desc: Circle A
          type: basic
          radius: 5
      """
    And a file named "package_b/partcad.yaml" with content:
      """
      desc: Package B
      sketches:
        circle_b:
          desc: Circle B
          type: basic
          radius: 10
      """
    When I run "pc --no-ansi list packages -r"
    Then the command should exit with a status code of "0"
    # the root package is not presented, because it has nothing in it
    And STDERR should not contain "Root Package"
    And STDERR should contain "Package A"
    And STDERR should contain "Package B"
    And STDERR should contain "DFRobot"
    When I run "pc --no-ansi list packages -r //"
    Then the command should exit with a status code of "0"
    # the root package is not presented, because it has nothing in it
    And STDERR should not contain "Root Package"
    And STDERR should contain "Package A"
    And STDERR should contain "Package B"
    And STDERR should contain "DFRobot"
    When I run "pc --no-ansi list packages -r //dfrobot"
    Then the command should exit with a status code of "0"
    And STDERR should not contain "Root Package"
    And STDERR should not contain "Package A"
    And STDERR should not contain "Package B"
    And STDERR should contain "DFRobot"
    When I run "pc --no-ansi list packages ///package_a"
    Then the command should exit with a status code of "0"
    And STDERR should not contain "Root Package"
    And STDERR should contain "Package A"
    And STDERR should not contain "Package B"
    And STDERR should not contain "DFRobot"
    When I run "pc --no-ansi list packages -r //nonexistent"
    Then the command should exit with a non-zero status code
    And STDERR should not contain "Root Package"
    And STDERR should not contain "Package A"
    And STDERR should not contain "Package B"
    And STDERR should not contain "DFRobot"
    When I run "pc --no-ansi list packages //"
    Then the command should exit with a status code of "0"
    And STDERR should contain "Root Package"
    And STDERR should not contain "Package A"
    And STDERR should not contain "Package B"
    And STDERR should not contain "DFRobot"
    When I run "pc --no-ansi list packages"
    Then the command should exit with a status code of "0"
    And STDERR should contain "Root Package"
    And STDERR should not contain "Package A"
    And STDERR should not contain "Package B"
    And STDERR should not contain "DFRobot"


  @pc-help
  Scenario: Test list sketches
    Given a file named "partcad.yaml" with content:
      """
      name: //
      desc: Root Package
      dependencies:
        dfrobot:
          type: git
          onlyInRoot: true
          url: https://github.com/partcad/partcad-robotics-part-vendor-dfrobot
      """
    And a file named "package_a/partcad.yaml" with content:
      """
      desc: Package A
      sketches:
        circle_a:
          desc: Circle A
          type: basic
          radius: 5
      """
    And a file named "package_b/partcad.yaml" with content:
      """
      desc: Package B
      sketches:
        circle_b:
          desc: Circle B
          type: basic
          radius: 10
      """
    When I run "pc --no-ansi list sketches -r"
    Then the command should exit with a status code of "0"
    And STDERR should contain "Circle A"
    And STDERR should contain "Circle B"
    And STDERR should not contain "Rubber Wheel"
    When I run "pc --no-ansi list sketches -r //"
    Then the command should exit with a status code of "0"
    And STDERR should contain "Circle A"
    And STDERR should contain "Circle B"
    And STDERR should not contain "Rubber Wheel"
    When I run "pc --no-ansi list sketches -r //dfrobot"
    Then the command should exit with a status code of "0"
    And STDERR should not contain "Circle A"
    And STDERR should not contain "Circle B"
    # And STDERR should contain "Rubber Wheel" # not a sketch
    When I run "pc --no-ansi list sketches -r //package_a"
    Then the command should exit with a status code of "0"
    And STDERR should contain "Circle A"
    And STDERR should not contain "Circle B"
    And STDERR should not contain "Rubber Wheel"
    When I run "pc --no-ansi list sketches //package_a"
    Then the command should exit with a status code of "0"
    And STDERR should contain "Circle A"
    And STDERR should not contain "Circle B"
    And STDERR should not contain "Rubber Wheel"
    When I run "pc --no-ansi list sketches //"
    Then the command should exit with a status code of "0"
    And STDERR should not contain "Circle A"
    And STDERR should not contain "Circle B"
    And STDERR should not contain "Rubber Wheel"


  @pc-help
  Scenario: Test list parts
    Given a file named "partcad.yaml" with content:
      """
      name: //
      desc: Root Package
      dependencies:
        dfrobot:
          type: git
          onlyInRoot: true
          url: https://github.com/partcad/partcad-robotics-part-vendor-dfrobot
      """
    And a file named "package_a/partcad.yaml" with content:
      """
      desc: Package A
      sketches:
        circle_a:
          desc: Circle A
          type: basic
          radius: 5
      parts:
        part_a:
          desc: Part A
          type: extrude
          sketch: circle_a
          depth: 5
      """
    And a file named "package_b/partcad.yaml" with content:
      """
      desc: Package B
      sketches:
        circle_b:
          desc: Circle B
          type: basic
          radius: 10
      parts:
        part_b:
          desc: Part B
          type: extrude
          sketch: circle_b
          depth: 10
      """
    When I run "pc --no-ansi list parts -r"
    Then the command should exit with a status code of "0"
    And STDERR should contain "Part A"
    And STDERR should contain "Part B"
    And STDERR should contain "Rubber Wheel"
    When I run "pc --no-ansi list parts -r //"
    Then the command should exit with a status code of "0"
    And STDERR should contain "Part A"
    And STDERR should contain "Part B"
    And STDERR should contain "Rubber Wheel"
    When I run "pc --no-ansi list parts -r //dfrobot"
    Then the command should exit with a status code of "0"
    And STDERR should not contain "Part A"
    And STDERR should not contain "Part B"
    And STDERR should contain "Rubber Wheel"
    When I run "pc --no-ansi list parts -r //package_a"
    Then the command should exit with a status code of "0"
    And STDERR should contain "Part A"
    And STDERR should not contain "Part B"
    And STDERR should not contain "Rubber Wheel"
    When I run "pc --no-ansi list parts ///package_a"
    Then the command should exit with a status code of "0"
    And STDERR should contain "Part A"
    And STDERR should not contain "Part B"
    And STDERR should not contain "Rubber Wheel"
    When I run "pc --no-ansi list parts //"
    Then the command should exit with a status code of "0"
    And STDERR should not contain "Part A"
    And STDERR should not contain "Part B"
    And STDERR should not contain "Rubber Wheel"




  @pc-help
  Scenario: Test list packages
    Given a file named "partcad.yaml" with content:
      """
      name: //corp_x/project_y
      desc: Root Package
      dependencies:
        dfrobot:
          type: git
          onlyInRoot: true
          url: https://github.com/partcad/partcad-robotics-part-vendor-dfrobot
      """
    And a file named "package_a/partcad.yaml" with content:
      """
      desc: Package A
      sketches:
        circle_a:
          desc: Circle A
          type: basic
          radius: 5
      """
    And a file named "package_b/partcad.yaml" with content:
      """
      desc: Package B
      sketches:
        circle_b:
          desc: Circle B
          type: basic
          radius: 10
      """
    When I run "pc --no-ansi list packages -r"
    Then the command should exit with a status code of "0"
    And STDERR should not contain "Root Package"
    And STDERR should contain "Package A"
    And STDERR should contain "Package B"
    And STDERR should not contain "DFRobot"
    When I run "pc --no-ansi list packages -r //"
    Then the command should exit with a status code of "0"
    And STDERR should not contain "Root Package"
    And STDERR should contain "Package A"
    And STDERR should contain "Package B"
    And STDERR should not contain "DFRobot"
    When I run "pc --no-ansi list packages -r //dfrobot"
    Then the command should exit with a status code of "0"
    And STDERR should not contain "Root Package"
    And STDERR should not contain "Package A"
    And STDERR should not contain "Package B"
    And STDERR should contain "DFRobot"
    When I run "pc --no-ansi list packages //corp_x/project_y/package_a"
    Then the command should exit with a status code of "0"
    And STDERR should not contain "Root Package"
    And STDERR should contain "Package A"
    And STDERR should not contain "Package B"
    And STDERR should not contain "DFRobot"
    When I run "pc --no-ansi list packages -r //nonexistent"
    Then the command should exit with a non-zero status code
    And STDERR should not contain "Root Package"
    And STDERR should not contain "Package A"
    And STDERR should not contain "Package B"
    And STDERR should not contain "DFRobot"
    When I run "pc --no-ansi list packages //"
    Then the command should exit with a status code of "0"
    And STDERR should contain "Root Package"
    And STDERR should not contain "Package A"
    And STDERR should not contain "Package B"
    And STDERR should not contain "DFRobot"
    When I run "pc --no-ansi list packages"
    Then the command should exit with a status code of "0"
    And STDERR should contain "Root Package"
    And STDERR should not contain "Package A"
    And STDERR should not contain "Package B"
    And STDERR should not contain "DFRobot"


  @pc-help
  Scenario: Test list sketches
    Given a file named "partcad.yaml" with content:
      """
      name: //corp_x/project_y
      desc: Root Package
      dependencies:
        dfrobot:
          type: git
          onlyInRoot: true
          url: https://github.com/partcad/partcad-robotics-part-vendor-dfrobot
      """
    And a file named "package_a/partcad.yaml" with content:
      """
      desc: Package A
      sketches:
        circle_a:
          desc: Circle A
          type: basic
          radius: 5
      """
    And a file named "package_b/partcad.yaml" with content:
      """
      desc: Package B
      sketches:
        circle_b:
          desc: Circle B
          type: basic
          radius: 10
      """
    When I run "pc --no-ansi list sketches -r"
    Then the command should exit with a status code of "0"
    And STDERR should contain "Circle A"
    And STDERR should contain "Circle B"
    And STDERR should not contain "Rubber Wheel"
    When I run "pc --no-ansi list sketches -r //"
    Then the command should exit with a status code of "0"
    And STDERR should contain "Circle A"
    And STDERR should contain "Circle B"
    And STDERR should not contain "Rubber Wheel"
    When I run "pc --no-ansi list sketches -r //dfrobot"
    Then the command should exit with a status code of "0"
    And STDERR should not contain "Circle A"
    And STDERR should not contain "Circle B"
    # And STDERR should contain "Rubber Wheel" # not a sketch
    When I run "pc --no-ansi list sketches -r //corp_x/project_y/package_a"
    Then the command should exit with a status code of "0"
    And STDERR should contain "Circle A"
    And STDERR should not contain "Circle B"
    And STDERR should not contain "Rubber Wheel"
    When I run "pc --no-ansi list sketches //package_a"
    Then the command should exit with a status code of "0"
    And STDERR should contain "Circle A"
    And STDERR should not contain "Circle B"
    And STDERR should not contain "Rubber Wheel"
    When I run "pc --no-ansi list sketches //"
    Then the command should exit with a status code of "0"
    And STDERR should not contain "Circle A"
    And STDERR should not contain "Circle B"
    And STDERR should not contain "Rubber Wheel"


  @pc-help
  Scenario: Test list parts
    Given a file named "partcad.yaml" with content:
      """
      name: //corp_x/project_y
      desc: Root Package
      dependencies:
        dfrobot:
          type: git
          onlyInRoot: true
          url: https://github.com/partcad/partcad-robotics-part-vendor-dfrobot
      """
    And a file named "package_a/partcad.yaml" with content:
      """
      desc: Package A
      sketches:
        circle_a:
          desc: Circle A
          type: basic
          radius: 5
      parts:
        part_a:
          desc: Part A
          type: extrude
          sketch: circle_a
          depth: 5
      """
    And a file named "package_b/partcad.yaml" with content:
      """
      desc: Package B
      sketches:
        circle_b:
          desc: Circle B
          type: basic
          radius: 10
      parts:
        part_b:
          desc: Part B
          type: extrude
          sketch: circle_b
          depth: 10
      """
    When I run "pc --no-ansi list parts -r"
    Then the command should exit with a status code of "0"
    And STDERR should contain "Part A"
    And STDERR should contain "Part B"
    And STDERR should not contain "Rubber Wheel"
    When I run "pc --no-ansi list parts -r //"
    Then the command should exit with a status code of "0"
    And STDERR should contain "Part A"
    And STDERR should contain "Part B"
    And STDERR should not contain "Rubber Wheel"
    When I run "pc --no-ansi list parts -r //dfrobot"
    Then the command should exit with a status code of "0"
    And STDERR should not contain "Part A"
    And STDERR should not contain "Part B"
    And STDERR should contain "Rubber Wheel"
    When I run "pc --no-ansi list parts -r //corp_x/project_y/package_a"
    Then the command should exit with a status code of "0"
    And STDERR should contain "Part A"
    And STDERR should not contain "Part B"
    And STDERR should not contain "Rubber Wheel"
    When I run "pc --no-ansi list parts //corp_x/project_y/package_a"
    Then the command should exit with a status code of "0"
    And STDERR should contain "Part A"
    And STDERR should not contain "Part B"
    And STDERR should not contain "Rubber Wheel"
    When I run "pc --no-ansi list parts //"
    Then the command should exit with a status code of "0"
    And STDERR should not contain "Part A"
    And STDERR should not contain "Part B"
    And STDERR should not contain "Rubber Wheel"
