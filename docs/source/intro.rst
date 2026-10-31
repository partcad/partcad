Introduction
############

========
Overview
========

**PartCAD is the programming language for manufacturable things.**

A PartCAD package is a Git repository with a ``partcad.yaml`` in it. That file declares the things the
product is made of -- parts, as CAD scripts or CAD files; assemblies and scenes that place them; the
interfaces they mate through; the materials they are made of; the requirements they have to meet. PartCAD
renders, tests, simulates, analyses and documents what is declared there, and produces the bill of
materials, the sourcing and the assembly instructions from that same source.

Everything is text. So a product is versioned, reviewed, branched and merged the way software is, by people
and by AI agents alike -- and nothing in the chain from a requirement to a purchase order is a binary nobody
can diff.

What PartCAD works with
=======================

* **Parts** written as code (`CadQuery <https://github.com/CadQuery/cadquery>`_,
  `build123d <https://github.com/gumyr/build123d>`_, `OpenSCAD <https://openscad.org/>`_,
  `Chili3D <https://github.com/xiangechen/chili3d>`_, `SDF <https://github.com/fogleman/sdf>`_) or read from
  a file (STEP, BREP, STL, 3MF, OBJ, glTF, KiCad PCBs, FreeCAD documents), plus whatever format a plugin
  package adds.
* **Assemblies and scenes** in Assembly YAML, URDF or a STEP file, with interfaces and mating as objects of
  their own rather than coordinates written out by hand.
* **Outputs**: the CAD formats above, Gazebo and MuJoCo worlds, 2D projections, dimensioned drawings,
  Markdown documentation, and PDF or HTML instruction books.
* **Engineering**: finite element, modal, thermal and fluid analysis (``pc cae``), simulation in MuJoCo or
  Gazebo (``pc sim``), 2.5D toolpaths (``pc cam``), and materials and manufacturing methods that carry
  through into the bill of materials.
* **Supply chain**: a build-or-buy decision per line item, stock-based procurement for the parts that are
  made rather than bought, and ordering from the command line.
* **AI agents**: Agent Skills for Claude Code and Cursor, an MCP server (``pc mcp``), and plain-text
  ``--no-ansi`` output on every command so that an agent parses text rather than progress bars.
* **Caching** in memory, on disk, on a memcached server and in an S3 bucket, so that a team or a CI fleet
  renders each model once.

:doc:`/supported` has the full list, including what is accepted but not yet delivered.

What PartCAD is not
===================

It is not a drawing tool, and it does not want to be. It is the layer *underneath* the drawing tools: the
specification of a manufacturable product, in a form a human, a CI job and an AI model can each read, change
and check. Which drawing tool produced a part is the part's business; PartCAD's business is that the product
made of it can be built, sourced and audited.

Keeping that specification on your own machines, in Git, and portable between CAD tools and manufacturers is
the point of the whole exercise. :doc:`/digital_thread/use_cases` has the shapes this takes in practice.

=====================
What a package holds
=====================

PartCAD includes tools to package product information:

- Optional (but highly recommended) **high-level requirements** (texts and drawings)
- Optional **detailed design** (mechanical outline, PCB schematics, software architecture)
- Implementation (**mechanical CAD files, PCB layout, software artifacts**)
- Optionally, the following data can be provided to augment or complement the output:

  - Additional manufacturing process requirements and instructions
  - Additional product validation instructions
  - **Maintenance instructions**

- Or any other product related metadata

Such packages are **modular and reusable**, allowing one to build not only on top of the CAD files of
previous products, but to **build on top of their manufacturing processes** as well.

======================
What PartCAD produces
======================

As a result of maintaining the product information using PartCAD, the following outputs can be generated
and, if necessary, collected and managed using PartCAD tools:

- **Product documentation** (markdown, html or PDF)
- Design validation results
- Product **bill of materials** (mechanical, electronics, software)
- Sourcing information **for all components**
- Manufacturing **process specification** (including required equipment if any)
- Manufacturing **instructions** (sufficiently documented to be reproduced by anyone without inquiring any
  additional information)
- Product **validation** instructions
- Product validation **results** (given access to an experimental product and the required tools)
- Input data for software components to visualize the product on your website, with a 3D viewer, a
  configurator, manufacturing/assembly instructions and more

The full list of formats read and written, and of the analyses, simulations and manufacturing steps
PartCAD runs, is in :doc:`/supported`.

===============================
Product development and testing
===============================

Once product information is packaged, it can be versioned and used for iterative improvements or to produce
PartCAD outputs either by human or AI actors. To achieve that, PartCAD integrates with third-party tools.
Below are just some examples of what third-party integrations can be used for:

- AI tools can be used to **update the mechanical design and implementation automatically** based on the
  current state of the requirements
- A legacy CAD tool can be used manually to update the implementation
- AI tools can be used to validate the design and implementation to identify product requirement or best
  practices (e.g. to reduce manufacturing complexity) violations
- **A web interface of an online store or an API of an additive manufacturer** can be used to source and
  manufacture parts
- Simulation tools (potentially in conjunction with AI tools) can be used to validate that the product
  design matches the product requirements
- AI tools can be used to review the product implementation for correctness, safety or compliance
- Manufacturing processes are **verified for completeness** (e.g. tools requirements are specified for all
  operations)
- Manufacturing instructions are **verified for correctness** (e.g. the provided manufacturing steps can
  actually be successfully and safely performed, and fit within the capabilities of the selected
  manufacturing tools)

Some of the iterative improvements or tests can be achieved using PartCAD built-in features. However, the
use of third-party tools is **recommended for unlocking cutting edge innovations and features**.

==============================
Supply chains based on PartCAD
==============================

By letting the user easily switch between third-party engineering tools or manufacturers without having to
migrate product data, PartCAD creates a competitive environment for service providers to **drive the costs
down**.

Whenever you select third-party tools (if any) to use in your workflows, you ultimately decide (and make it
transparent or auditable) **how secure your supply chain is and how exposed your product information is**.
If you opt for on-prem tools only, all your product information remains on-prem too. It makes PartCAD an
ultimate solution for achieving data sovereignty for those willing to keep their product data private. **In
the age of cloud data harvesting (especially for AI training), it makes PartCAD a better alternative to any
cloud-based PDM, PLM or BOM solution**.

==================================
Operations using PartCAD (planned)
==================================

PartCAD also works on the following supplementary products, to enable operations without any use of
third-party tools. Neither is part of this repository yet.

- A CRM for part manufacturing and assembly shops for businesses of any size (from skilled individuals
  working in their garage to the biggest factories) to **immediately start taking orders** for manufacturable
  products maintained using PartCAD
- An inventory tool to manage the list of parts and final products in stock, as well as to track and manage
  all in-progress or completed orders, to **immediately bring supply chains up and to scale them up while
  keeping all data private on-prem** and not incurring any costs (for cloud services and alike)

=======
History
=======

PartCAD was initially just an internal library in the
`OpenVMP project <https://github.com/openvmp/openvmp>`_
to maintain the blueprints of OpenVMP robots in a way that allows reconfiguring
the blueprints based on the specific needs (parameters), and allows to maintain
the bill of materials and all the necessary data to purchase the required parts.

The OpenVMP project has surfaced the need for an open source Product Lifecycle
Management (PLM) system that would use Git for collaboration on the designs
themselves, the supplementary documentation and supplier information
(and integration).
To address that need PartCAD was published as a standalone framework to be used
by any project.
