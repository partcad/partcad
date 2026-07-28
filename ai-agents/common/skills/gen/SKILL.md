---
name: gen
description: Generate PartCAD geometry from a description, automatically deciding whether the request is a single part or a multi-part assembly and following the matching flow. Use for /pc:gen or when the user asks to generate, create, or model something in PartCAD without saying whether it is a part or an assembly.
---

# pc:gen

Entry point for PartCAD generation when the user has not said whether they want a
single **part** or an **assembly**. The text after the command (`$ARGUMENTS`) is
the description of what to build. Decide which it is, tell the user your choice,
then follow that flow — passing the same description through.

## Decide: part or assembly?

- **Part** → `/pc:gen-part`. One continuous piece of geometry — a bracket, a
  gear, a housing, a knob. Modeled as a single script, even when intricate.
- **Assembly** → `/pc:gen-assembly`. Several distinct components that fit or move
  relative to each other — a gearbox, a robot arm, a body with a lid, anything
  joined by fasteners.

Heuristics:

- One noun, "a"/"single", one manufacturing process, one printed/machined piece
  → **part**.
- Plurals, "with", "attached to", "... and a ...", moving joints, fasteners, or
  named sub-components → **assembly**.

If it is genuinely ambiguous, ask one short question. Otherwise proceed with your
best judgment and state which you picked — the user can redirect.

## Then

- Part → follow **`/pc:gen-part`**.
- Assembly → follow **`/pc:gen-assembly`** (which itself uses `/pc:gen-part` for
  any missing components).
