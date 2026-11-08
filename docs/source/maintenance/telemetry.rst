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

.. _user-location:

Country, Language, Currency and Location
========================================

A store, a catalog or anything else a plugin is a client of is a different thing
in different places: another range, other prices in other money, pages in
another language, the shop round the corner. Four options say where the user is:

  .. code-block:: yaml

    # ~/.partcad/config.yaml
    country: NL              # ISO 3166-1 alpha-2, or PC_COUNTRY
    language: en             # ISO 639-1, or PC_LANGUAGE
    currency: EUR            # ISO 4217, or PC_CURRENCY
    location: "52.37,4.89"   # latitude,longitude in degrees, or PC_LOCATION

``location`` can also be written ``{latitude: 52.37, longitude: 4.89}``, and in
the ``user`` section as ``user.location``.

None of them has to be written down. ``country`` is the ``countryCode`` of the
user's address, else the country of the locale PartCAD was started in
(``nl_NL.UTF-8`` is the Netherlands); ``language`` is the locale's language; and
``currency`` is the country's. A process started with no locale in its
environment -- an editor opened from the Dock or the Start menu -- asks the
operating system instead: the language and region chosen in Windows' or macOS'
settings, so English with the region set to the Netherlands is ``en_NL``.
``location`` is never worked out from any of that: it is the user's to give, or
not -- typed in, or asked of this computer's location service when the user has
allowed it (below).

They are worked out by the client -- ``pc``, ``pc mcp`` -- on the machine of
whoever runs the command, and handed to the daemon with the rest of the
configuration. The daemon uses what it is handed and nothing of its own, so a
command is answered for where its user is, wherever the daemon was started. (The
editor extension sends no configuration: the daemon it starts on the user's own
machine works them out there.)

A plugin is told the country, the state and city of the address, the language
and the currency (see :ref:`providers`), never the name, the street, the ZIP code
or the location. A store choosing between its shops asks PartCAD which is
nearest, and PartCAD answers with a shop. ``pc config`` and
``pc system status env`` report whether a location is set, not where it is.

.. _user-location-access:

Whether any of it is wanted
---------------------------

Where the user is matters for two things only: ordering the manufacturing of
parts and assemblies, and handling manufacturing orders yourself. Two more
options say whether either is wanted:

  .. code-block:: yaml

    # ~/.partcad/config.yaml
    manufacturingOrders: [place, handle]   # or [] -- or PC_MANUFACTURING_ORDERS=place,handle
    locationAccess: false                  # or PC_LOCATION_ACCESS

``manufacturingOrders`` is what the user said they use PartCAD for: ``place``
(ordering manufacturing), ``handle`` (handling orders), both, or an empty list
(or ``none``) for "neither, I design". The option missing altogether means
nobody has asked yet.

``locationAccess`` says whether PartCAD may ask this computer's operating system
where it is. It is off unless the user turns it on, and with it off PartCAD never
asks. Each system has its own location service, and each asks the user for its
own permission the first time:

- **Windows**: the Windows location service (Settings > Privacy & security >
  Location, "Let desktop apps access your location"), through Windows
  PowerShell.
- **macOS**: Core Location (System Settings > Privacy & Security > Location
  Services), through ``CoreLocationCLI`` where one is installed and otherwise
  through ``osascript``, which macOS attributes to the application that started
  it -- the PartCAD IDE, the editor, the terminal.
- **Linux**: GeoClue, which most desktops carry (GNOME: Settings > Privacy >
  Location); the desktop's GeoClue agent asks the user.

What is kept of an answer is rounded to two decimals, about a kilometre: enough
to tell which shop is nearest, and not enough to find a front door. With
``locationAccess`` on, the IDE asks again once a day, when it starts, and writes
the ``location`` only when it has moved further than the service says its answer
can be off by -- a location service never gives the same answer twice, and
rewriting the file restarts the daemon that read it.

The PartCAD IDE and the VS Code extension ask all of this the first time they
start on a computer whose configuration has no ``manufacturingOrders``: a dialog
asks whether the user will order manufacturing or handle manufacturing orders,
and recommends leaving everything blank and off otherwise. The answers open a
form for the region, the address and the location, and are written into
``~/.partcad/config.yaml``. Because the question is asked of the file rather than
of the editor, one answer serves the IDE and every editor on the computer; the
form is "PartCAD: Region, Address and Location" in the command palette, any time
after.

The same, from a terminal:

  .. code-block:: shell

    pc system locale show                       # what is configured, and what is worked out
    pc system locale set --manufacturing-orders place --country NL --city Amsterdam
    pc system locale set --city ""              # an empty value removes the option
    pc system locale locate --save              # ask the location service, and keep the answer
    pc system locale settings                   # open this computer's location privacy settings

Every one of them runs on the computer it is typed on and never asks a daemon:
the configuration file, the location service and the user are all here.

