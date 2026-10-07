Configuration
#############

Most users need to create a single package, containing one or more parts, and maybe an assembly.
That is achieved by creating a configuration file (``partcad.yaml``) that defines the package and
declares all parts and assemblies it contains.
PartCAD aims to maintain three ways to manage the configuration files:

- Manual configuration file edits.

  PartCAD aims to maintain a simple and intuitive syntax for configuration files.
  It is currently expected that PartCAD users edit the configuration file manually
  immediately or after a few hours of using PartCAD, as the other ways to maintain
  the configuration files are not mature enough yet to meet the needs of advanced users.

- Command line interface.

  PartCAD aims to provide a command line interface for all possible configuration changes
  to any section or field.
  However, there is currently a very limited set of commands implemented: mostly the very
  first operations a new PartCAD user would need.

- Graphical user interface.

  PartCAD aims to provide a Visual Studio Code plugin with a graphical interface to
  allow changes to any configuration file sections or fields.
  However, there is currently a very limited set of operations implemented: mostly the very
  first operations a new PartCAD user would need.

The complete syntax of configuration files is described below.

.. toctree::
   :maxdepth: 2

   config_package.rst
   config_objects.rst
   config_geometry.rst
   config_parts.rst
   config_making.rst
   config_product.rst
   config_plugins.rst
   config_output.rst
