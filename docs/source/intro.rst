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
