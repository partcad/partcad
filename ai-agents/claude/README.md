# PartCAD for Claude Code

The `pc` plugin teaches Claude Code to design, check and hand off mechanical
parts and assemblies with [PartCAD](https://partcad.org), which documents
manufacturable products as code: parts and sketches made by CAD scripts
(build123d, CadQuery, OpenSCAD) or read from files (STEP, STL, ...), assemblies
and scenes that place them, and the requirements each is held to.

It brings PartCAD's skills and one MCP server.

- `/pc:setup` puts PartCAD's `pc` command on this machine, and the PartCAD
  extension into Visual Studio Code or VSCodium when the session runs there.
- `/pc:init` creates a package; `/pc:gen` generates a part, an assembly, a
  scene or a sketch from a description, and `/pc:gen-part`, `/pc:gen-assembly`,
  `/pc:gen-scene` and `/pc:gen-sketch` each of those directly. They settle
  dimensions on measured sketches first, and check what they built by rendering
  it from several angles. `/pc:gen-landscape` builds a piece of the real world,
  from public elevation and map data, as a scene to test things in.
- `/pc:validate` holds an object to its requirements; `/pc:add-interfaces`
  gives a part ports so others mate to it; `/pc:sim-assembly-fea` turns a
  simulation into a stress analysis of one part.
- `/pc:render`, `/pc:export`, `/pc:convert`, `/pc:describe` and `/pc:search`
  draw, write out, convert, describe and find objects.
- `/pc:rfq-pack`, `/pc:quote-pack` and `/pc:change-impact` hand a design to
  the people who buy, quote and inspect: a request for quotation, the basis of
  a customer quote, and a draft engineering change notice, each a folder with a
  manifest naming the commit behind every file — what Claude for Manufacturing
  reads from PartCAD.
- The `partcad` MCP server, `pc mcp`, lets the agent list, inspect, render,
  qualify and export the objects of the project it is working in.

## Getting it

```text
/plugin marketplace add partcad/partcad@plugin-dist
/plugin install pc@partcad
/pc:setup
```

The plugin is versioned with PartCAD itself: a release publishes both.
[The documentation](https://partcad.readthedocs.io/) covers PartCAD, and the
[repository](https://github.com/partcad/partcad) its source, under the Apache
License 2.0.
