Contributing
############

Everyone can contribute to the development of PartCAD,
which lowers the entry barrier to the design and manufacturing world
and speeds up innovation for humanity.

Find below some of the ways to contribute.

=====================
Contribute to PartCAD
=====================

By improving PartCAD itself, you can improve the framework and platform
capabilities for all of its users, no matter whether they are using public
packages or working on hermetic private repositories.

Ideas and Feedback
==================

Share your ideas and feedback on
`our Discord server <https://discord.gg/h5qhbHtygj>`_.

Participate in Decision Making
==============================

`Become a PartCAD supporter <https://patreon.com/PartCAD>`_ to vote for
prioritization of different development tracks and for other decisions.

Your contributions are used exclusively to fund the development process,
not to pay back venture capitalists, and ensure PartCAD remains independent.

For larger contributions
(accompanied with a request to develop a particular feature or not),
please, reach out to
`the team <mailto:support@partcad.org>`_ directly.
We also accept contributions in the form of GPUs and other AI-capable hardware.
We are committed to never produce a single gram of CO2 by pointlessly peforming
cryptographic operations for the purpose of financial speculations or taking
advantage of cryptography challenged.

Develop Features
================

Send a pull request to
`the PartCAD's main Github repository <https://github.com/partcad/partcad/>`_.

Engage with the community on
`PartCAD's Discord channel <https://discord.gg/h5qhbHtygj>`_
if you need help deciding what could be the best project for you to work on.

Documentation and Tutorials
===========================

Currently, our team is short on skills required to document PartCAD well.
Join us and bring the word to the world!
You can make a huge impact on lots of people by simply creating a simple post
or a basic video tutorial.

=======================================
Contribute to PartCAD Public Repository
=======================================

Assemblies
==========

Migrate your products to PartCAD by creating and publishing Assembly YAML files
for your products. Eliminate the need to develop and maintain a custom way to
store and to publish assembly instructions and bills of materials.
Enable the use or your assemblies in other PartCAD projects.

Start by creating a package (in a dedicated git repository)
for all products by your company or community.
Then add parametrized assembly declarations to the package.

The best way to write Assembly YAML files is to use PartCAD VS Code extension
and use code completion features: select the part you want to add in the
explorer view on the left and, then,
start typing '- part: ' in the Assembly YAML file editor as if you were to add
a new part to the assembly. After you typed "- pa", a code completion suggestion
will show up, offering to add the complete YAML block which adds the selected
part to the assembly.

Parts
=====

Publish your parts in the PartCAD Public Repository to enable their use (and
purchase if applicable) by other PartCAD users.

Start by creating a package (in a dedicated git repository)
for all parts and assemblies created by your company
or community, if you didn't do that yet.
Then add part declarations to the package.

If CAD files already exist for these parts, then you should probably start by
using those CAD files first. You can always migrate to Code-CAD technologies
(such as OpenSCAD, CadQuery or build123d) later. However you might want to host
the CAD files separately from the package's git repository
(and have PartCAD fetch them using `fileFrom: url`,
even if they are hosted in another git repository)
so that you do not blow up the repository size and
slow your projects down in perpetuity by a temporary use of legacy CAD files.

After that declare the location of ports.
This will enable connecting parts to each other, instead of placing them using
absolute and relative coordinates and ensuring they remain properly co-located
using finger-crossing guarantees.
Whenever possible, use interfaces and mating declarations insteaf of pure ports,
so that it's easier for PartCAD (including AIs using PartCAD) to determine
which parts are meant to be connected to which parts, and how exactly they need
to be connected.

Interfaces
==========

The most challenging step of adding parts is to declare all the ports.
This effort can be significantly reduced for all PartCAD users globally
by extending the library of standard interfaces.

Does your part have a port of the kind also found in many other parts?
Consider declaring a reusable interface.

Providers
=========

Advertise your online store and manufacturing services by integrating your API
with PartCAD.

Decide which one is more appropriate for your business:
``store`` or ``manufacturer``. Then see an existing provider implementation of
that kind as a reference. Alternatively, reach out to the PartCAD team to get
help with the implementation. Be at the forefront of the next industrial
revolution together with PartCAD!

Help a Friend
=============

Do you know an opensource project that maintains assembly instructions or doing
something else that can be radically improved by using PartCAD?

Do you know a business that uses legacy tools and struggles to scale
collaboration in the era of Git?

Do you know a local additive manufacturing shop that can use more local
customers?

Do you know a collection of parts that the community can really benefit from if
only these parts and corresponding assembly ideas were easily discoverable?

Help them migrate to PartCAD!
