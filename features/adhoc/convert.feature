@cli @pc-adhoc-convert
Feature: `pc adhoc convert` command

  Background: Create temporary environment and create the test file
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"
    And a file named "test.stl" with content:
      """
      solid
       facet normal -1.000000e+00  0.000000e+00  0.000000e+00
         outer loop
           vertex -5.000000e+00 -5.000000e+00  5.000000e+00
           vertex -5.000000e+00  5.000000e+00 -5.000000e+00
           vertex -5.000000e+00 -5.000000e+00 -5.000000e+00
         endloop
       endfacet
       facet normal -1.000000e+00  0.000000e+00  0.000000e+00
         outer loop
           vertex -5.000000e+00 -5.000000e+00  5.000000e+00
           vertex -5.000000e+00  5.000000e+00  5.000000e+00
           vertex -5.000000e+00  5.000000e+00 -5.000000e+00
         endloop
       endfacet
       facet normal  1.000000e+00  0.000000e+00  0.000000e+00
         outer loop
           vertex  5.000000e+00 -5.000000e+00  5.000000e+00
           vertex  5.000000e+00 -5.000000e+00 -5.000000e+00
           vertex  5.000000e+00  5.000000e+00 -5.000000e+00
         endloop
       endfacet
       facet normal  1.000000e+00 -0.000000e+00  0.000000e+00
         outer loop
           vertex  5.000000e+00 -5.000000e+00  5.000000e+00
           vertex  5.000000e+00  5.000000e+00 -5.000000e+00
           vertex  5.000000e+00  5.000000e+00  5.000000e+00
         endloop
       endfacet
       facet normal  0.000000e+00 -1.000000e+00 -0.000000e+00
         outer loop
           vertex  5.000000e+00 -5.000000e+00  5.000000e+00
           vertex -5.000000e+00 -5.000000e+00 -5.000000e+00
           vertex  5.000000e+00 -5.000000e+00 -5.000000e+00
         endloop
       endfacet
       facet normal -0.000000e+00 -1.000000e+00  0.000000e+00
         outer loop
           vertex  5.000000e+00 -5.000000e+00  5.000000e+00
           vertex -5.000000e+00 -5.000000e+00  5.000000e+00
           vertex -5.000000e+00 -5.000000e+00 -5.000000e+00
         endloop
       endfacet
       facet normal  0.000000e+00  1.000000e+00  0.000000e+00
         outer loop
           vertex  5.000000e+00  5.000000e+00  5.000000e+00
           vertex  5.000000e+00  5.000000e+00 -5.000000e+00
           vertex -5.000000e+00  5.000000e+00 -5.000000e+00
         endloop
       endfacet
       facet normal  0.000000e+00  1.000000e+00  0.000000e+00
         outer loop
           vertex  5.000000e+00  5.000000e+00  5.000000e+00
           vertex -5.000000e+00  5.000000e+00 -5.000000e+00
           vertex -5.000000e+00  5.000000e+00  5.000000e+00
         endloop
       endfacet
       facet normal -0.000000e+00  0.000000e+00 -1.000000e+00
         outer loop
           vertex  5.000000e+00  5.000000e+00 -5.000000e+00
           vertex -5.000000e+00 -5.000000e+00 -5.000000e+00
           vertex -5.000000e+00  5.000000e+00 -5.000000e+00
         endloop
       endfacet
       facet normal  0.000000e+00 -0.000000e+00 -1.000000e+00
         outer loop
           vertex  5.000000e+00  5.000000e+00 -5.000000e+00
           vertex  5.000000e+00 -5.000000e+00 -5.000000e+00
           vertex -5.000000e+00 -5.000000e+00 -5.000000e+00
         endloop
       endfacet
       facet normal  0.000000e+00  0.000000e+00  1.000000e+00
         outer loop
           vertex  5.000000e+00  5.000000e+00  5.000000e+00
           vertex -5.000000e+00  5.000000e+00  5.000000e+00
           vertex -5.000000e+00 -5.000000e+00  5.000000e+00
         endloop
       endfacet
       facet normal  0.000000e+00  0.000000e+00  1.000000e+00
         outer loop
           vertex  5.000000e+00  5.000000e+00  5.000000e+00
           vertex -5.000000e+00 -5.000000e+00  5.000000e+00
           vertex  5.000000e+00 -5.000000e+00  5.000000e+00
         endloop
       endfacet
      endsolid
      """

  Scenario: Convert STL to STEP
    When I run "pc adhoc convert test.stl test.step --input stl --output step"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Converting test.stl (stl) to test.step (step)..."
    And STDOUT should contain "Conversion complete: test.step"

  Scenario: Infer input type and convert STL to STEP
    When I run "pc adhoc convert test.stl test.step --output step"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Converting test.stl (stl) to test.step (step)..."
    And STDOUT should contain "Conversion complete: test.step"

  Scenario: Missing input file
    When I run "pc adhoc convert nonexistent.stl test.step"
    Then the command should exit with a status code of "2"
    And STDOUT should contain "Path 'nonexistent.stl' does not exist."

  Scenario: Unsupported output type
    When I run "pc adhoc convert test.stl --input stl --output unknown"
    Then the command should exit with a status code of "2"
    And STDOUT should contain "Invalid value for '--output': 'unknown'"

  Scenario: Invalid input type
    When I run "pc adhoc convert test.stl test.step --input unknown --output step"
    Then the command should exit with a status code of "2"
    And STDOUT should contain "Invalid value for '--input': 'unknown'"

  Scenario: Convert STL to STEP without specifying output filename
    When I run "pc adhoc convert test.stl --output step"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Converting test.stl (stl) to test.step (step)..."
    And STDOUT should contain "Conversion complete: test.step"
    And a file named "test.step" should be created

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
    When I run "pc adhoc convert invalid.stl test.step --input stl --output step"
    Then the command should exit with a status code of "1"
    And STDOUT should contain "Failed to convert:"

  Scenario: Handle empty input file
    Given a file named "empty.stl" with content:
      """
      """
    When I run "pc adhoc convert empty.stl empty.step --input stl --output step"
    Then the command should exit with a status code of "1"
    And STDOUT should contain "Failed to convert:"

  Scenario: Ambiguous input file extension
    Given a file named "test.unknown" with content:
      """
      """
    When I run "pc adhoc convert test.unknown test.step"
    Then the command should exit with a status code of "1"
    And STDOUT should contain "Cannot infer input type. Please specify --input explicitly."

  Scenario: Overwrite existing output file
    Given a file named "test.step" with content:
      """
      Existing STEP content
      """
    When I run "pc adhoc convert test.stl test.step --input stl --output step"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Converting test.stl (stl) to test.step (step)..."
    And STDOUT should contain "Conversion complete: test.step"
