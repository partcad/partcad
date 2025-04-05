@cli @pc-adhoc-convert @sketch
Feature: `pc adhoc convert sketch` command

  Background: Create temporary environment and a test sketch file
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"
    And a file named "circle.svg" with content:
      """
      <?xml version='1.0' encoding='utf-8'?>
      <svg width="101.0mm" height="98.266745mm" viewBox="-10.1 -9.826674 20.2 19.653349" version="1.1" xmlns="http://www.w3.org/2000/svg">
        <g transform="scale(1,-1)" stroke-linecap="round">
          <g fill="none" stroke="rgb(64,192,64)" stroke-width="0.2" id="Visible">
            <path d="M 7.071068,-8.093446 A 10.0,5.576189073395618 0.0 0,1 10.0,-4.150485" />
            <path d="M -10.0,-4.150485 A 10.0,5.576189073395618 0.0 0,1 7.071068,-8.093446" />
            <path d="M 7.071068,0.207524 A 10.0,5.576189073395618 0.0 0,1 10.0,4.150485" />
            <path d="M 10.0,4.150485 A 10.0,5.576189073395618 0.0 0,1 -10.0,4.150485" />
            <path d="M -10.0,4.150485 A 10.0,5.576189073395618 0.0 0,1 7.071068,0.207524" />
            <line x1="-10.0" y1="4.150485" x2="-10.0" y2="-4.150485" />
            <line x1="10.0" y1="4.150485" x2="10.0" y2="-4.150485" />
          </g>
          <g fill="none" stroke="rgb(32,64,32)" stroke-width="0.018" id="Hidden" stroke-dasharray="0.000457 0.054229">
            <path d="M 10.0,-4.150485 A 10.0,5.576189073395618 0.0 0,1 -10.0,-4.150485" />
          </g>
        </g>
      </svg>
      """

  Scenario: Convert SVG to DXF with explicit types
    When I run "pc adhoc convert sketch circle.svg circle.dxf --input svg --output dxf"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Converting"
    And STDOUT should contain "Conversion complete"
    And a file named "circle.dxf" should be created

  Scenario: Convert SVG to DXF with inferred types
    When I run "pc adhoc convert sketch circle.svg circle.dxf"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Converting"
    And STDOUT should contain "Conversion complete"

  Scenario: Convert SVG to DXF without output filename
    When I run "pc adhoc convert sketch circle.svg --output dxf"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Conversion complete"
    And a file named "circle.dxf" should be created

  Scenario: Missing input sketch file
    When I run "pc adhoc convert sketch sketch_missing.svg out.dxf"
    Then the command should exit with a status code of "2"

  Scenario: Unsupported sketch output type
    When I run "pc adhoc convert sketch circle.svg --input svg --output png"
    Then the command should exit with a status code of "2"

  Scenario: Invalid input sketch type
    When I run "pc adhoc convert sketch circle.svg circle.dxf --input unknown --output dxf"
    Then the command should exit with a status code of "2"

  Scenario: Invalid SVG file
    Given a file named "invalid.svg" with content:
      """
      <svg><badtag></svg>
      """
    When I run "pc adhoc convert sketch invalid.svg invalid.dxf --input svg --output dxf"
    Then the command should exit with a status code of "1"
    And STDOUT should contain "Failed to convert:"

  Scenario: Empty SVG file
    Given a file named "empty.svg" with content:
      """
      """
    When I run "pc adhoc convert sketch empty.svg empty.dxf --input svg --output dxf"
    Then the command should exit with a status code of "1"
    And STDOUT should contain "Failed to convert:"

  Scenario: Ambiguous sketch input extension
    Given a file named "unknown_format.unknown" with content:
      """
      """
    When I run "pc adhoc convert sketch unknown_format.unknown sketch.dxf"
    Then the command should exit with a status code of "1"
    And STDERR should contain "Cannot infer input sketch type. Please specify --input explicitly."

  Scenario: Overwrite existing sketch output file
    Given a file named "circle.dxf" with content:
      """
      Existing DXF content
      """
    When I run "pc adhoc convert sketch circle.svg circle.dxf --input svg --output dxf"
    Then the command should exit with a status code of "0"
    And STDOUT should contain "Converting"
    And STDOUT should contain "Conversion complete"
