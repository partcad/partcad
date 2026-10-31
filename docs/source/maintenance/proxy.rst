.. _proxy-configuration:

###########
Using Proxy
###########


On many networks a proxy is not a preference but the only route out. PartCAD
reads the usual environment variables, and everything it downloads goes through
them: packages imported from a git repository, packages imported from a
tarball, and the individual files an object pulls with ``fileFrom: url``.

  .. code-block:: bash

    export HTTPS_PROXY=http://proxy.example.com:3128
    export NO_PROXY=git.internal.example.com,localhost

    pc update

``HTTPS_PROXY`` covers ``https://`` remotes and ``HTTP_PROXY`` covers ``http://``
ones; the lowercase spellings work equally. ``NO_PROXY`` exempts the hosts it
names, which is what an internal git server reachable only *without* the proxy
needs. A proxy that wants credentials takes them in the URL
(``http://user:password@proxy.example.com:3128``).

Nothing has to be configured in PartCAD for any of this. A proxy that should
apply to git imports alone -- rather than to everything this shell runs -- can be
set as a git configuration option instead, and it takes precedence over the
environment:

  .. code-block:: yaml

    # ~/.partcad/config.yaml
    git:
      config:
        "http.proxy": "http://proxy.example.com:3128"

Note that a proxy re-terminating TLS presents its own certificate, which has to
be trusted or every fetch fails to verify it. That is a property of the machine
rather than of PartCAD: point ``SSL_CERT_FILE`` (and ``REQUESTS_CA_BUNDLE``) at
the proxy's CA bundle, or install it into the system trust store.
