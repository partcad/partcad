# https://partcad.atlassian.net/browse/PC-164
@wip @PC-164
Feature: Supply quote generation
  As a PartCAD user
  I want to generate supply quotes
  So that I can estimate costs for my projects

  Scenario: Generate quote for available parts
    Given I have a project with standard parts
    When I run "partcad supply quote --format json"
    Then the command should succeed
    And the output should contain valid pricing information
    And the JSON response should include:
      | Field       | Type    |
      | unit_price  | number  |
      | quantity    | integer |
      | total_price | number  |
      | currency    | string  |
    And the response should be in JSON format

  Scenario: Handle quote for unavailable parts
    Given I have a project with custom parts
    When I run "partcad supply quote"
    Then the command should succeed with warnings
    And the output should indicate which parts cannot be quoted
    And the warning message should include the part identifiers
    And available parts should still be quoted correctly
  #    And the response should include a summary of:
  #      | quoted_parts_count    |
  #      | unquoted_parts_count  |
  #      | total_available_price |

  Scenario: Validate JSON quote format
    Given I have a project with standard parts
    When I run "pc supply quote --format json"
    Then the command should succeed
    And the output should be valid JSON
    And the JSON should contain required fields:
      | field       |
      | total_price |
      | currency    |
      | parts_list  |

  Scenario: Handle network failure
    Given the supply service is unreachable
    When I run "pc supply quote"
    Then the command should fail gracefully
    And the error message should indicate connectivity issues

  Scenario: Quote exceeds budget threshold
    Given I have a project with expensive parts
    And I set budget threshold to "1000"
    When I run "pc supply quote --check-budget"
    Then the command should succeed with warnings
    And the output should indicate budget exceeded
