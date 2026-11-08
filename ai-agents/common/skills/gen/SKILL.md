---
name: gen
description: Generate PartCAD geometry from a description, automatically deciding whether the request is a single part, a multi-part assembly, a scene (an arrangement of objects - a room, an interior, a workcell, a world), or a 2D sketch and following the matching flow. Use for /pc:gen or when the user asks to generate, create, or model something in PartCAD without saying whether it is a part, an assembly, a scene, or a sketch.
---

# pc:gen

Entry point for PartCAD generation when the user has not said whether they want a
single **part**, an **assembly**, a **scene**, or a 2D **sketch**. The text after
the command (`$ARGUMENTS`) is the description of what to build. Decide which it is, tell the
user your choice, then follow that flow — passing the same description through.

## Decide: part, assembly, scene, or sketch?

- **Part** → `/pc:gen-part`. One continuous piece of 3D geometry — a bracket, a
  gear, a housing, a knob. Modeled as a single script, even when intricate.
- **Assembly** → `/pc:gen-assembly`. Several distinct 3D components that fit or
  move relative to each other — a gearbox, a robot arm, a body with a lid,
  anything joined by fasteners.
- **Scene** → `/pc:gen-scene`. Objects arranged where they stand rather than
  put together into a product — a room, a building interior, an office floor, a
  workcell, a table laid out, a world to simulate something in.
- **Sketch** → `/pc:gen-sketch`. A 2D profile, outline, or blueprint — a gasket
  shape, a plate outline, a cross-section to be extruded later.

Heuristics:

- "2D", "profile", "outline", "sketch", "cross-section", "blueprint", "trace
  this drawing" → **sketch**.
- One noun, "a"/"single", one manufacturing process, one printed/machined piece
  → **part**.
- Plurals, "with", "attached to", "... and a ...", moving joints, fasteners, or
  named sub-components → **assembly**.
- A place or a setting — "a room", "an apartment", "an office", "a kitchen", "a
  workcell", "a garden", "on the Moon", "in orbit" — or things "standing",
  "laid out" or "arranged" somewhere → **scene**. A product *in* such a place
  is still an assembly, which the scene then places.

If it is genuinely ambiguous, ask one short question. Otherwise proceed with your
best judgment and state which you picked — the user can redirect.

A physical claim in the description — it stands, it does not tip, it floats, it
holds a load, it works under water or on the Moon — is part of the request, not
decoration: carry it into the part, assembly or scene flow, which makes the
result ready to simulate and checks the claim with `pc sim`.

## Then

- Sketch → follow **`/pc:gen-sketch`**.
- Part → follow **`/pc:gen-part`**.
- Assembly → follow **`/pc:gen-assembly`** (which itself uses `/pc:gen-part` for
  any missing components).
- Scene → follow **`/pc:gen-scene`** (which models its objects as `basic`
  primitives, and uses `/pc:gen-part` and `/pc:gen-assembly` where more detail
  is called for).

All four settle the dimensions before they model: `/pc:gen-sketch` measures
the targets out of whatever the input is — a description, a drawing, a photo, a
3D file — and iterates a sketch until it measures the same, and the part,
assembly and scene flows run it on temporary sketches first, then measure their
own result against the same numbers. Pass every reference image, drawing or
file the user gave through to the flow you pick: those are what the dimensions
are measured from.

The part, assembly and scene flows write down what the object is required to
be as its `requirements:` before judging the result against them, and
`/pc:validate` gives a verdict on every one of them afterwards.
