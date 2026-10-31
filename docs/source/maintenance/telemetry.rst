#########
Telemetry
#########


Public Repositories
===================

By default PartCAD collects telemetry data to improve the user experience and to help
understand how the tool is being used. The data collected includes the
following:

- What commands are being run?
- How much time is consumed by each step?
- What errors and exceptions are being raised?

PartCAD uses `OpenTelemetry <https://opentelemetry.io/>`_ to collect telemetry data.
You can disable telemetry by setting the following configuration:

  .. code-block:: yaml

    # ~/.partcad/config.yaml
    telemetry:
      type: none

Alternatively, you can disable telemetry by setting the following environment variable:

  .. code-block:: bash

    PC_TELEMETRY_TYPE="none"

You can also change telemetry settings using CLI:

  .. code-block:: bash

    pc system set telemetry type none
    # or, if you want to collect data about PartCAD performance in your organization:
    pc system set telemetry type sentry
    pc system set telemetry env <you-org-name>
    pc system set telemetry sentryDsn <your-sentry-dsn>

How deep the traces go is a separate setting. By default PartCAD reports the
operations it names for itself -- the process a command is, and the action each
object it works on is -- and nothing below them:

  .. code-block:: bash

    pc system set telemetry detail actions   # the default
    pc system set telemetry detail methods

``methods`` adds a span for every instrumented method underneath those, which is
what a trace needs to answer "where inside this did the time go". It is
expensive in a way that is easy to miss: creating one part passes through a
dozen instrumented methods, so a package of eight thousand of them costs a
quarter of a million spans to list. Turn it on while you are looking at
something, not for good.

``pc system telemetry info`` reports both settings.

Private Repositories
====================

If you are systemically using PartCAD in your organization then it makes sense
to collect your own telemetry data to understand how the tool is being
used in your organization, and to learn how to improve your organization performance.

The only OpenTelemetry backend provider currently supported is `Sentry <https://sentry.io/>`_.
Create an organization account on Sentry and obtain a DSN key.

  .. code-block:: yaml

    # ~/.partcad/config.yaml
    telemetry:
      type: sentry
      sentryDsn: "<your-sentry-dsn>"

Other OpenTelemetry backend providers can be supported on request.


Personally Identifiable Information
===================================


The user section in ``~/.partcad/config.yaml`` defines the default personal
and contact details used throughout the system. These details include
the user's name, email, phone number, company, and address information.

  .. code-block:: yaml

    # ~/.partcad/config.yaml
    user:
        firstName: <...>
        lastName: <...>
        email: <...>
        phone: <...>
        company: <...>
        line1: <...>
        line2: <(optional)>
        countryCode: US
        stateCode: <...>
        zipCode: <...>
        city: <...>

Address Configuration
=====================

Users can override any details from the user section
by specifying shippingAddress and billingAddress separately.

  .. code-block:: yaml

    # ~/.partcad/config.yaml
    user: # Default user details (includes firstName, lastName, email, phone, company, address, etc.)

    shippingAddress:  # Optional, overrides user details for shipping
        firstName: <(optional)>
        lastName: <(optional)>
        phone: <(optional)>
        company: <(optional)>
        line1: <(optional)>
        line2: <(optional)>
        countryCode: <(optional)>
        stateCode: <(optional)>
        zipCode: <(optional)>
        city: <(optional)>

    billingAddress:  # Optional, overrides user details for billing
        firstName: <(optional)>
        lastName: <(optional)>
        phone: <(optional)>
        company: <(optional)>
        line1: <(optional)>
        line2: <(optional)>
        countryCode: <(optional)>
        stateCode: <(optional)>
        zipCode: <(optional)>
        city: <(optional)>

**Override Behavior**

- If shippingAddress is not specified, the system will use the user details for shipping.
- If billingAddress is not specified, the system will use the user details for billing.
- If shippingAddress or billingAddress is provided, it completely replaces the corresponding fields from user.

This setup allows full customization of shipping and billing details,
supporting scenarios where items need to be sent to different recipients or addresses.
