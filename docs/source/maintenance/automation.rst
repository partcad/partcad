##########
Automation
##########


PartCAD allows you to set CLI options and override user configurations specified in
``~/.partcad/config.yaml`` using environment variables. This can be particularly
useful for setting configurations dynamically or in environments where modifying
configuration files is not feasible.

Generally, all of PartCAD's environment variables are prefixed with ``PC``.

For CLI options, the environment variable prefix depends on the command being
used. You can use the `--help` option to determine the corresponding environment
variable for each CLI option.

    Here are some examples:

      .. code-block:: bash

        # Equivalent to: pc add part --desc "testing" scad test.scad
        PC_ADD_PART_DESC="testing" pc add part scad test.scad

Note that, these environment variables will be overridden if the CLI option is specified.

For user configurations, the environment variables are of the format ``PC_`` followed by the
configuration option name in upper snake case (camelCase word boundaries become underscores).
For example, to override the ``pythonSandbox`` configuration, you would set the environment
variable ``PC_PYTHON_SANDBOX``.

Note that environment variable names are case-sensitive. Always use uppercase letters
for the ``PC`` prefix and the rest of the variable name, as shown in the examples above.

In this case, these environment variables will take precedence over the values specified in
``~/.partcad/config.yaml``.


Parameter Configuration
=======================


The configuration file (``~/.partcad/config.yaml``) allows users to define
reusable parameters, which can be accessed dynamically within the provider configurations.

In ``~/.partcad/config.yaml``, parameters are stored under a parameters section.

Example:

  .. code-block:: yaml

    # ~/.partcad/config.yaml
    parameters:
      object_id:
        <parameter name>: <parameter value>


Object IDs are used to reference different
types of objects within a package, such as sketches, parts,
assemblies, scenes, interfaces, and providers.


Accessing Parameters in Providers
=================================

In the providers section, parameters can be referenced dynamically
using a function ``get_from_config()``, ensuring that sensitive
or reusable values (e.g., API keys, URLs) do not need to be
hardcoded multiple times.

Example:

  .. code-block:: yaml

    # ~/.partcad/config.yaml
    providers:
      <provider name>:
        type: <store|manufacturer|enrich>
        url: <...>
        parameters:
          url:
            type: string
            default: {{ get_from_config() }}
