@cli @pc-adhoc-convert @part
Feature: `pc adhoc convert` command

  Background: Setup test environment
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

  Scenario: Convert STL to STEP explicitly
    When I run "pc adhoc convert part test.stl test.step --input stl --output step"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Converting"
    And STDOUT should contain "Conversion complete"

  Scenario: Convert STL to STEP by inferring types
    When I run "pc adhoc convert part test.stl test.step"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Converting"

  Scenario: Convert with only input file (auto-named output)
    When I run "pc adhoc convert part test.stl --output step"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Conversion complete"
    And a file named "test.step" should be created

  Scenario: Fail on unknown input type
    When I run "pc adhoc convert part test.stl test.step --input unknown --output step"
    Then the command should exit with a status code of "2"
    And STDOUT should contain "Invalid value for '--input'"

  Scenario: Fail on unknown output type
    When I run "pc adhoc convert part test.stl test.step --input stl --output unknown"
    Then the command should exit with a status code of "2"
    And STDOUT should contain "Invalid value for '--output'"

  Scenario: Fail when input file is missing
    When I run "pc adhoc convert part missing.stl test.step"
    Then the command should exit with a status code of "2"
    And STDOUT should contain "Path 'missing.stl' does not exist."

  Scenario: Fail on empty file
    Given a file named "empty.stl" with content:
      """
      """
    When I run "pc adhoc convert part empty.stl empty.step --input stl --output step"
    Then the command should exit with a status code of "1"
    And STDOUT should contain "Failed to convert"

  Scenario: Fail on ambiguous file extension
    Given a file named "unknown.format" with content:
      """
      nothing here
      """
    When I run "pc adhoc convert part unknown.format"
    Then the command should exit with a status code of "1"
    And STDOUT should contain "Cannot infer input type"

  Scenario: Overwrite existing output file
    Given a file named "test.step" with content:
      """
      Existing STEP content
      """
    When I run "pc adhoc convert part test.stl test.step --input stl --output step"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Conversion complete"

  Scenario: Fail on invalid STL file
    Given a file named "invalid.stl" with content:
      """
      solid missing_end
        facet normal 0 0 0
          outer loop
            vertex 0 0 0
            vertex 1 0 0
            vertex 0 1 0
          endloop
        endfacet
      """
    When I run "pc adhoc convert part invalid.stl test.step --input stl --output step"
    Then the command should exit with a status code of "1"
    And STDOUT should contain "Failed to convert"
