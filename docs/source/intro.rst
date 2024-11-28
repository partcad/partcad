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
While it does not yet have all the features of a full PLM system,
it is on the way to becoming one.

It is currently addressing mechanical engineering workflows, but it will
address electrical and electronics engineering workflows as well in the future.

========
Overview
========

PartCAD can be perceived as consisting of four parts:

- PartCAD standards and conventions on how to maintain part and assembly data

- The public repository of data created and maintained by the community based
  on the PartCAD standards and conventions

- Tools that operate with public and private repositories for as
  long as they are maintained following the PartCAD standards and conventions

- Libraries and frameworks to programmatically interact with PartCAD data in
  public and private repositories

Detailed documentation on all of the above can be found in the 'Design' section.
