@cli @pc-adhoc-convert
Feature: `pc adhoc convert` command

  Background:
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"
    And a file named "test.stl" with content:
      """
      solid test
        facet normal 0 0 0
          outer loop
            vertex 0 0 0
            vertex 1 0 0
            vertex 0 1 0
          endloop
        endfacet
      endsolid
      """

  Scenario: Convert STL to STEP
    When I run "partcad adhoc convert test.stl test.step --input stl --output step"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Converting test.stl (stl) to test.step (step)..."
    And STDOUT should contain "Conversion complete: test.step"

  Scenario: Infer input type and convert STL to STEP
    When I run "partcad adhoc convert test.stl test.step --output step"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Converting test.stl (stl) to test.step (step)..."
    And STDOUT should contain "Conversion complete: test.step"

  Scenario: Missing input file
    When I run "partcad adhoc convert nonexistent.stl test.step --input stl --output step"
    Then the command should exit with a status code of "1"
    And STDERR should contain "Error: [Errno 2] No such file or directory: 'nonexistent.stl'"

  Scenario: Unsupported output type
    When I run "partcad adhoc convert test.stl test.unknown --input stl --output unknown"
    Then the command should exit with a status code of "1"
    And STDERR should contain "Error during conversion: Unsupported export format: unknown"

  Scenario: Invalid input type
    When I run "partcad adhoc convert test.stl test.step --input unknown --output step"
    Then the command should exit with a status code of "1"
    And STDERR should contain "Cannot infer input type. Please specify --input explicitly."

  Scenario: Convert STL to STEP without specifying output filename
    When I run "partcad adhoc convert test.stl --output step"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Converting test.stl (stl) to test.step (step)..."
    And STDOUT should contain "Conversion complete: test.step"
    And a file named "test.step" should exist

  Scenario: Invalid STL file
    Given a file named "invalid.stl" with content:
      """
      solid InvalidSTL
        facet normal 0 0 0
          outer loop
            vertex 0 0 0
            vertex 1 0 0
            vertex 0 1 0
          endloop
        endfacet
      /* Missing 'endsolid' keyword */
      """
    When I run "partcad adhoc convert invalid.stl test.step --input stl --output step"
    Then the command should exit with a status code of "1"
    And STDERR should contain "Error during conversion: Failed to load the input part."
