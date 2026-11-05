.. _plugin-login:

##########
Logging in
##########

A plugin that is a client of somebody else's service -- a repository serving a model site's catalog, a
provider ordering from a store -- needs the user's credentials for it, and they are the user's, not the
package's. ``login`` is how a plugin gets them: an optional api of **every kind of plugin PartCAD runs a script
for** (``basic`` repositories, ``manufacturer`` and ``store`` providers, and an ``enrich`` of any of them, which
runs the script it enriches with its own parameters), asked by ``pc login <package>:<plugin>``.

.. code-block:: shell

  pc login //pub/universe/grabcad:grabcad_repo

What it does is up to the plugin. What most do is check the credentials they were given and, when the site no
longer takes them, ask PartCAD to open the user's browser on the site's sign-in, with PartCAD's extension in it
to pick up what signing in leaves behind. Whatever they return is saved in the user's configuration file as
their overrides of the plugin's parameters, so every later request hands them to the plugin.

The script
==========

PartCAD runs the script with ``__name__ == "login"``, as it runs ``get`` or ``quote``, with two globals:

``request``
  As for any api. ``request["parameters"]`` holds the plugin's parameters with the user's overrides applied --
  so the credentials an earlier ``pc login`` saved, or the user set by hand or with ``--extra-param``.

``partcad_login``
  PartCAD's callback. ``partcad_login.open_browser(...)`` opens the user's browser and returns what it
  captured, ``{name: value}``; ``partcad_login.interactive`` is false under ``pc login --check``, when
  ``open_browser`` raises ``partcad_login.NotInteractive`` instead of opening anything.

and answers ``output = {"result": {"parameters": {...}, "message": "..."}}`` -- the parameters to save, and one
line for the user -- or raises. A script with no ``login`` branch answers ``{}``, and ``pc login`` says the plugin
has no login.

.. code-block:: python

  def login(request, partcad_login):
      token = request["parameters"].get("token")
      if token and whoami(token):                       # still good: keep it
          return {"parameters": {"token": token}, "message": "Already logged in"}
      got = partcad_login.open_browser(
          url="https://example.com/login",
          title="Example",
          capture=[{"name": "token", "cookie": {"url": "https://example.com/", "name": "session"}}],
          done_when={"fetch": {"url": "https://example.com/api/me", "status": 200}},
          guide=[{"url": "https://example.com/login*", "selector": "input[type=email]", "text": "Sign in"}],
      )
      if not whoami(got["token"]):
          raise RuntimeError("the site did not take what the login captured")
      return {"parameters": {"token": got["token"]}, "message": "Logged in"}

  if __name__ == "login":
      output = {"result": login(request, partcad_login)}

**The callback is replayed.** The plugin runs where every plugin runs, in a sandbox on the daemon, which may be
another machine; the browser belongs on the screen of whoever typed ``pc login``. So ``open_browser`` does not
return the first time it is called. It raises ``partcad_login.BrowserNeeded`` -- not an ``Exception``, so a
plugin's ``except Exception`` lets it through -- carrying what the browser is to do; ``pc login`` does it, and
runs ``login`` again from the top with the result, when the same call returns it. The n-th call returns the n-th
result. A ``login`` therefore has to be the same up to each call, and must do nothing before one that must not
happen twice -- which checking credentials and building a URL are not.

What the browser is asked
=========================

``open_browser(url, capture, title=None, guide=None, require="all", done_when=None, timeout=600)``:

``url``
  Where the browser goes, once the extension has been handed the rest.

``capture``
  What to bring back, a list of ``{"name": ..., <source>: {...}}`` with exactly one source each:

  - ``cookie``: ``{"url", "name"}`` -- read with the browser's cookie API, HttpOnly cookies included;
  - ``localStorage`` / ``sessionStorage``: ``{"origin", "key"}``;
  - ``dom``: ``{"url", "selector", "property"}`` -- off the first element matching ``selector`` on a page at
    ``url`` (``textContent`` by default, or ``value``, or an ``attribute``);
  - ``redirect``: ``{"url", "param"}`` -- from the query or the fragment of an address matching ``url``, which
    is how an OAuth implicit grant hands its token over; the page need not load;
  - ``ask``: ``{"label", "secret"}`` -- an input in the extension's banner, for something the user copies.

  Any source may add ``match``, a regular expression the value has to match to count, so that what a visitor
  has is never taken for what a signed-in user has.
``require``
  ``"all"`` or ``"any"`` of the captures.
``done_when``
  ``{"url": ...}``, ``{"selector": ...}`` or ``{"fetch": {"url", "status"}}``: what must also hold before the
  capture is sent -- the last asks the site, from the browser, with the user's own session. Without it, the
  banner's **Done** button is the signal.
``guide``
  Steps, each ``{"url", "selector", "contains", "text"}``. On a page at ``url``, the first step whose ``selector``
  matches a visible element -- one whose text matches ``contains`` too, a case-insensitive regular expression,
  when the step has one: a site's "Log in" is often a button nothing but its text tells apart -- is shown: the
  element spotlighted, the rest of the page greyed out, a pointer at it and the ``text`` beside it. Clicks still
  pass through. ``done_when``'s ``selector`` takes a ``contains`` too.
``timeout``
  How many seconds ``pc login`` waits for the browser.

URL patterns are globs over the whole address, ``*`` matching anything.

The browser and the extension
=============================

``pc login`` opens the user's default browser -- as Windows, macOS or Linux record it -- in a profile of
PartCAD's own (``~/.partcad/browser/<browser>``; where a snap or flatpak lets it write, for one of those), never
the everyday one, and the extension lives only there: it can read any site's cookies, which is what it is for, and
that is a power to keep to the window it was opened for. The profile is kept, so a site signed in to once stays
signed in. A Chromium-family browser is given the unpacked extension over its DevTools pipe (Google Chrome no
longer honours ``--load-extension``), and Firefox over WebDriver BiDi as a temporary add-on; a browser that can be
given neither is passed over for one that can, and with none, ``pc login`` prints the address of a page where the
values are pasted by hand.

The browser starts on a page ``pc login``'s listener serves on ``127.0.0.1``, which hands the extension what the
plugin asked for; the extension reports back to that listener alone, and closes the window. The listener only
answers its own address, and only for the random token each step is given.

The extension is built and published from the ``browsers/`` directory of the PartCAD repository.
