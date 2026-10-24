Introduction
############

==========
Background
==========

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

========
Overview
========

PartCAD can be perceived as consisting of four parts:

- PartCAD standards and conventions on how to maintain product information

- The public repository of products created and maintained by the community based
  on the PartCAD standards and conventions

- Tools that operate with public and private repositories for as
  long as they are maintained following the PartCAD standards and conventions

- Libraries and frameworks to programmatically interact with product information in
  public and private PartCAD repositories

Detailed documentation on all of the above can be found in the 'Design' section.

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
PartCAD runs, is in :doc:`supported`.

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
