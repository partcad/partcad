@cli
Feature: `pc init` command

  Background:
    Given I am in "/tmp/sandbox/behave" directory
    And I have temporary $HOME in "/tmp/sandbox/home"

  @pc-init @requires-network
  Scenario: Initialize new package as public
    Given a file named "partcad.yaml" does not exist
    When I run "pc --no-ansi init"
    Then the command should exit with a status code of "0"
    And STDERR should not contain "PartCAD configuration file is not found"
    # The public index, tracking its released branch and pinned to the commit
    # that branch is at now -- which moves, so the commit cannot be written
    # down here.
    And STDERR should match the regex ".*Pinned pub to [0-9a-f]{40}, the tip of 'main'"
    And a file named "partcad.yaml" should contain "url: https://github.com/partcad/partcad-index.git"
    And a file named "partcad.yaml" should contain "track: main"
    And a file named "partcad.yaml" should contain "revision: "

  @pc-init
  Scenario: Initialize new package as public with no network
    # Creating a package does not need the network: the index is left
    # tracking its branch, unpinned, and 'pc update' pins it later.
    Given a file named "partcad.yaml" does not exist
    When I run "pc --no-ansi --offline init"
    Then the command should exit with a status code of "0"
    And STDERR should contain "Not pinning pub: PartCAD is configured to work offline"
    And a file named "partcad.yaml" should have YAML content:
      """
      partcad: ">=\\d+\\.\\d+\\.\\d+"
      dependencies:
        pub:
          type: git
          url: https://github.com/partcad/partcad-index.git
          track: main
      sketches:
      parts:
      assemblies:
      """

  @pc-init @private
  Scenario: Initialize new package as private
    Given a file named "partcad.yaml" does not exist
    When I run "pc --no-ansi init -p"
    Then the command should exit with a status code of "0"
    And a file named "partcad.yaml" should have YAML content:
      """
      private: true
      partcad: ">=\\d+\\.\\d+\\.\\d+"
      dependencies:
      sketches:
      parts:
      assemblies:
      """
    And the package should be marked as private

  @pc-init @launch-configuration
  Scenario: Add the "Render" command to the editor's launch configuration
    Given a file named "partcad.yaml" does not exist
    When I run "pc --no-ansi init"
    Then the command should exit with a status code of "0"
    And a file named ".vscode/launch.json" should be created
    And the file ".vscode/launch.json" should hold the "Render" run command
    And STDERR should contain "Added the 'Render' command"

  @pc-init @agent-skills
  Scenario: Install the AI agent skills the repository's agent will need
    Given a file named "partcad.yaml" does not exist
    When I run "pc --no-ansi init"
    Then the command should exit with a status code of "0"
    # Claude Code gets the plugin, which is what puts the skills in one
    # namespace: "/pc:init" rather than "/init".
    And a file named ".claude/skills/pc/.claude-plugin/plugin.json" should be created
    And a file named ".claude/skills/pc/skills/init/SKILL.md" should be created
    # Cursor has no plugin, so the prefix is the namespace.
    And a file named ".cursor/skills/pc-init/SKILL.md" should be created
    And a file named ".cursor/skills/init/SKILL.md" should not exist
    And the skill "pc-init" should be named after its directory
    # GitHub Copilot, Codex, Gemini CLI, Zed, OpenCode and Devin all read this
    # one directory, so it is written once, for all of them.
    And a file named ".agents/skills/pc-init/SKILL.md" should be created
    And STDERR should contain "Installed the 'pc' plugin"
    # And the project instructions nearly every agent reads first.
    And a file named "AGENTS.md" should be created
    And STDERR should contain "Wrote the PartCAD section"
    # And the MCP server the skills' agent can drive PartCAD through.
    And a file named ".mcp.json" should be created
    And a file named ".cursor/mcp.json" should be created
    And STDERR should contain "Added the PartCAD MCP server"

  @pc-init @agent-skills @mcp
  Scenario: Install the skills without the MCP server
    Given a file named "partcad.yaml" does not exist
    When I run "pc --no-ansi init --no-mcp"
    Then the command should exit with a status code of "0"
    And a file named ".cursor/skills/pc-init/SKILL.md" should be created
    And a file named ".mcp.json" should not exist
    And a file named ".cursor/mcp.json" should not exist

  @pc-init @agent-skills @agents
  Scenario: Install the skills for every agent PartCAD knows
    Given a file named "partcad.yaml" does not exist
    When I run "pc --no-ansi init --skills-only --agents all"
    Then the command should exit with a status code of "0"
    And a file named ".kiro/skills/pc-init/SKILL.md" should be created
    And a file named ".codex/config.toml" should be created
    And a file named ".gemini/settings.json" should be created
    And a file named ".zed/settings.json" should be created
    And a file named ".devin/mcp_config.json" should be created
    And a file named ".kiro/settings/mcp.json" should be created
    And a file named "opencode.json" should be created

  @pc-init @agent-skills
  Scenario: Install the skills without touching AGENTS.md
    Given a file named "partcad.yaml" does not exist
    When I run "pc --no-ansi init --no-instructions"
    Then the command should exit with a status code of "0"
    And a file named ".cursor/skills/pc-init/SKILL.md" should be created
    And a file named "AGENTS.md" should not exist

  @pc-init @agent-skills @mcp
  Scenario: Have the agents start the MCP server from the PartCAD image
    # What "pc init" does by default when it runs in that image, whose user has
    # no "pc" outside it, and what anyone can ask for.
    Given a file named "partcad.yaml" does not exist
    When I run "pc --no-ansi init --mcp-via docker"
    Then the command should exit with a status code of "0"
    And a file named ".mcp.json" should contain "ghcr.io/partcad/partcad"
    And a file named ".mcp.json" should contain "partcad-home:/home/pc/.partcad"
    And a file named ".cursor/mcp.json" should contain "${workspaceFolder}:${workspaceFolder}"
    And a file named ".mcp.json" should not contain "docker.sock"
    And the MCP server "partcad" in ".mcp.json" should serve "."
    And the MCP server "partcad" in ".cursor/mcp.json" should serve "."

  @pc-init @agent-skills @mcp @roots
  Scenario: Give every PartCAD root in a repository an MCP server of its own
    # One "pc mcp" serves one PartCAD root, and a repository can hold several.
    # The files are at the repository's root, which is what an editor opens;
    # each entry names its root relative to it. The second root's "pc init"
    # used to replace the first root's entry, and found "Render" taken.
    Given a directory named ".git" exists
    And a directory named "hw" exists
    And a directory named "tools/jigs" exists
    When I run "pc --no-ansi --offline -p hw init"
    Then the command should exit with a status code of "0"
    And a file named "hw/partcad.yaml" should be created
    When I run "pc --no-ansi --offline -p tools/jigs init"
    Then the command should exit with a status code of "0"
    And there should be 2 MCP servers in ".mcp.json"
    And the MCP server "partcad" in ".mcp.json" should serve "hw"
    And the MCP server "partcad-tools-jigs" in ".mcp.json" should serve "tools/jigs"
    And there should be 2 MCP servers in ".cursor/mcp.json"
    And the MCP server "partcad-tools-jigs" in ".cursor/mcp.json" should serve "tools/jigs"
    And the file ".vscode/launch.json" should hold the "Render" run command
    And the file ".vscode/launch.json" should hold the "Render (tools/jigs)" run command
    And a file named "hw/.mcp.json" should not exist
    # Run again from the top, where there is no package: every root below is
    # served, and none twice.
    When I run "pc --no-ansi init --skills-only"
    Then the command should exit with a status code of "0"
    And there should be 2 MCP servers in ".mcp.json"
    And there should be 2 MCP servers in ".cursor/mcp.json"

  @pc-init @agent-skills @mcp @roots
  Scenario: A subpackage is served by its root's MCP server
    Given a directory named ".git" exists
    And a directory named "hw/motor" exists
    When I run "pc --no-ansi --offline -p hw init"
    Then the command should exit with a status code of "0"
    When I run "pc --no-ansi --offline -p hw/motor init"
    Then the command should exit with a status code of "0"
    And there should be 1 MCP servers in ".mcp.json"
    And the MCP server "partcad" in ".mcp.json" should serve "hw"
    And the file ".vscode/launch.json" should hold the "Render (hw/motor)" run command

  @pc-init @agent-skills @mcp @editor-folder
  Scenario: Write the agents' files into the folder the editor opens
    # A folder holding several repositories: no agent reads a repository's
    # files from there, so they go where the editor does read them.
    Given a directory named "robot/.git" exists
    And a directory named "robot/hw" exists
    When I run "pc --no-ansi --offline -p robot/hw init --editor-folder ."
    Then the command should exit with a status code of "0"
    And the MCP server "partcad" in ".mcp.json" should serve "robot/hw"
    And the MCP server "partcad" in ".cursor/mcp.json" should serve "robot/hw"
    And a file named ".cursor/skills/pc-init/SKILL.md" should be created
    And the file ".vscode/launch.json" should hold the "Render" run command
    And a file named "robot/.mcp.json" should not exist

  @pc-init @agent-skills @mcp @editor-folder
  Scenario: In a terminal of the editor, write into the folder its window has open
    # The PartCAD extension tells each workspace folder's terminals which
    # folder that is, which "pc init" cannot otherwise know.
    Given a directory named "robot/.git" exists
    And a directory named "robot/hw" exists
    And the editor extension says the window has "." open
    When I run "pc --no-ansi --offline -p robot/hw init"
    Then the command should exit with a status code of "0"
    And the MCP server "partcad" in ".mcp.json" should serve "robot/hw"
    And the file ".vscode/launch.json" should hold the "Render" run command
    And a file named "robot/.mcp.json" should not exist

  @pc-init @agent-skills @mcp @editor-folder
  Scenario: A folder the editor has open but the package is not in is not written into
    # A terminal keeps its folder after it "cd"s out of it.
    Given a directory named "robot/.git" exists
    And a directory named "robot/hw" exists
    And the editor extension says the window has "notes" open
    When I run "pc --no-ansi --offline -p robot/hw init"
    Then the command should exit with a status code of "0"
    And STDERR should contain "is not inside it"
    And the MCP server "partcad" in "robot/.mcp.json" should serve "hw"
    And a file named "notes/.mcp.json" should not exist

  @pc-init @agent-skills @skills-only
  Scenario: Install the skills into a repository that has a package already
    # The package this would have created exists, which is the usual reason to
    # want this: the skills came from the "pc init" that created it, and a newer
    # PartCAD has newer ones.
    Given a file named "partcad.yaml" does not exist
    When I run "pc --no-ansi init"
    Then the command should exit with a status code of "0"
    When I run "pc --no-ansi init --skills-only"
    Then the command should exit with a status code of "0"
    And STDERR should not contain "File already exists"
    And a file named ".cursor/skills/pc-init/SKILL.md" should be created

  @pc-init @agent-skills @skills-only
  Scenario: Install the skills where there is no package at all
    Given a file named "partcad.yaml" does not exist
    When I run "pc --no-ansi init --skills-only"
    Then the command should exit with a status code of "0"
    And a file named ".claude/skills/pc/.claude-plugin/plugin.json" should be created
    And a file named "partcad.yaml" should not exist
    And a file named ".vscode/launch.json" should not exist

  @pc-init @agent-skills @agents
  Scenario: Install the skills for one agent only
    Given a file named "partcad.yaml" does not exist
    When I run "pc --no-ansi init --agents cursor"
    Then the command should exit with a status code of "0"
    And a file named ".cursor/skills/pc-init/SKILL.md" should be created
    And a directory named ".claude" should not exist

  @pc-init @agent-skills @agents @failure
  Scenario: Ask for an agent PartCAD does not know
    # A typo that installs nothing looks exactly like an agent that is not
    # supported yet, so it is an error rather than a quiet no-op.
    When I run "pc --no-ansi init --skills-only --agents kursor"
    Then the command should exit with a status code of "1"
    And STDERR should contain "Unknown agent(s): kursor"
    And a directory named ".cursor" should not exist

  @pc-init @agent-skills @skills-only @failure
  Scenario: Ask for the skills and for no skills at once
    When I run "pc --no-ansi init --skills-only --no-skills"
    Then the command should exit with a status code of "1"
    And STDERR should contain "ask for opposite things"
    And a directory named ".cursor" should not exist

  @pc-init @agent-skills
  Scenario: Create a package without them
    Given a file named "partcad.yaml" does not exist
    When I run "pc --no-ansi init --no-skills"
    Then the command should exit with a status code of "0"
    And a file named "partcad.yaml" should be created
    And a directory named ".claude" should not exist
    And a directory named ".cursor" should not exist

  @pc-init @option-private @failure
  Scenario: Fail initializing package when `partcad.yaml`already exists
    Given a file named "partcad.yaml" does not exist
    When I run "pc --no-ansi init -p"
    Then a file named "partcad.yaml" should be created
    When I run "pc --no-ansi init -p"
    Then the command should exit with a status code of "1"
    And STDERR should contain "File already exists: partcad.yaml"
    And STDERR should contain "Failed creating 'partcad.yaml'!"

  @wip @pc-init @failure
  Scenario: Fail initializing package with insufficient permissions
    Given I am in "/tmp/sandbox/behave" directory
    And the directory has read-only permissions
    When I run "pc --no-ansi init"
    Then the command should exit with a status code of "1"
    And STDERR should contain "Permission denied"

  @wip @pc-init @failure
  Scenario: Fail initializing with malformed existing YAML
    Given a file named "partcad.yaml" with content:
      """
      invalid:
        - yaml:
      content:
      """
    When I run "pc --no-ansi init"
    Then the command should exit with a status code of "1"
    And STDERR should contain "Invalid YAML format"
