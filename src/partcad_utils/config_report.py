#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""How a resolved configuration and a process environment are reported.

Two reports, and five commands that print one of them: `pc config` and
`pc system status config|env` in the client, `pc daemon status config|env` on
the far side of the daemon boundary. The client and the daemon are not the same
machine once a daemon can be remote, which is the whole reason both halves
exist; what must not differ is *what a report says*, and in particular what it
leaves out.

So the answer lives here, in the package both sides already share, rather than
once in the CLI and once in ``core/operations.py``. Two copies of a redaction
rule are one copy that stops redacting.
"""

import os
import re

# What is printed in place of a value that must not be printed. Deliberately not
# an empty string and not the value's own length: the reader of a status report
# is asking "is this configured, and with what shape", and a blank tells them
# neither.
SCRUBBED = "<scrubbed>"

# Configuration options whose value is a secret rather than a setting. These are
# reported as whether they are set and never as what they are: this output is
# what people paste into bug reports and screen recordings, and a shared secret
# that runs commands on another machine is not a thing to put in either.
#
# Named one by one rather than matched on the spelling: a rule like "anything
# ending in key" would hide 'cacheRemoteNamespace' keys and the git signing key
# that people legitimately need to read back, and would go on hiding things
# nobody meant to hide as options are added. The environment below is the one
# place a pattern is right, and the comment there says why.
SECRET_OPTIONS = ("remote_sandbox_token",)

# The 'user' section is personally identifiable information in its entirety --
# a name, an email address, a shipping address, a billing address -- so unlike
# every other option below, none of its values is reportable. What a report can
# say about it is which fields are configured, which is what somebody asking
# "why does my BOM have no address on it" actually needs.
#
# Not an entry in SECRET_OPTIONS, whose answer is "<set>"/"<not set>": PIIConfig
# populates 'shippingAddress' and 'billingAddress' whether or not anything was
# configured, so the section is *always* truthy and "<set>" would be a wrong
# answer on a machine that has never configured any of it.
PII_OPTION = "pii_config"

# The fields of a 'git.auth' entry that are credentials, by their configuration
# names. The entry itself is reported -- which hosts have credentials configured
# is exactly what somebody debugging a private dependency needs to see, and it
# is the question 'GitCallbacks' fails with an answer to -- but a password or a
# passphrase in it is not. 'username' and 'sshKey' stay readable: "the wrong
# account" and "the wrong key file" are the two things that report is for.
SECRET_GIT_AUTH_FIELDS = ("password", "sshKeyPassphrase")

# The prefix PartCAD's own environment variables carry, and the only one a
# report enumerates. One PartCAD variable does not have it --
# IGNORE_BUNDLED_OPENSCAD, which is a property of a standalone bundle rather
# than of a run, so a user sets it once in their shell -- and reporting the
# prefix is still the right rule: every other name in a process environment
# belongs to somebody else, and a status report that dumps an arbitrary
# environment is a status report nobody can paste anywhere.
ENV_PREFIX = "PC_"

# The word an environment variable's name carries when its value authenticates
# this process to something else. Matched between underscores so that a name
# merely containing the letters -- PC_MONKEY_SOMETHING -- is not mistaken for
# one, and applied only within the PC_ namespace above, which is PartCAD's own:
# a pattern over names PartCAD chose is a pattern that cannot surprise it.
#
# 'DSN' is deliberately absent. PartCAD's only PC_*_DSN is
# PC_TELEMETRY_SENTRY_DSN, and a Sentry DSN is a publishable client key rather
# than a credential -- PartCAD's own default one is a literal in
# 'user_config.py', and `pc config` prints whichever is in effect. Scrubbing it
# here would hide, from the report people paste into a bug, the one telemetry
# setting that says where their reports went.
AUTH_KEY_PATTERN = re.compile(
    r"(?:^|_)(?:TOKENS?|SECRETS?|PASSWORDS?|PASSWD|KEYS?|CREDENTIALS?|AUTH)(?:_|$)",
    re.IGNORECASE,
)


def is_auth_key(name: str) -> bool:
    """Whether an environment variable's name says its value authenticates."""
    return bool(AUTH_KEY_PATTERN.search(name))


def resolved_options(config):
    """Every option the configuration resolved, whatever shape it is kept in.

    'vars()' alone is not that. An option kept as a *property* -- which is how
    'pythonSandbox' notices being assigned, so that '--python-sandbox' counts as
    a decision and a startup default does not -- keeps its value in a private
    attribute and its name on the class. So it dropped out of the command whose
    whole job is to say what the configuration resolved to.
    """
    for key, value in vars(config).items():
        if not callable(value) and not key.startswith("_"):
            yield key, option_value(key, value)
    for key, member in vars(type(config)).items():
        if isinstance(member, property) and not key.startswith("_"):
            yield key, option_value(key, getattr(config, key))


def option_value(key, value):
    """The value, or as much of it as a report may carry."""
    if key in SECRET_OPTIONS:
        return "<set>" if value else "<not set>"
    if key == "git_auth":
        return _git_auth(value)
    if key == PII_OPTION:
        return _fields_only(value)
    return value


def _git_auth(value):
    """A 'git.auth' mapping with its credentials taken out.

    Returned as plain data rather than as the configuration view it came from,
    because the view reads through to the live configuration -- scrubbing a copy
    is the only way to scrub it at all.
    """
    try:
        entries = dict(value.to_dict() if hasattr(value, "to_dict") else value)
    except Exception:  # pylint: disable=broad-except  # pragma: no cover
        # A shape nothing here recognizes is one nothing here can redact.
        return SCRUBBED
    reported = {}
    for host, entry in entries.items():
        if not isinstance(entry, dict):
            reported[host] = SCRUBBED
            continue
        reported[host] = {
            field: (SCRUBBED if field in SECRET_GIT_AUTH_FIELDS else field_value)
            for field, field_value in entry.items()
        }
    return reported


def _fields_only(value):
    """A mapping reported as which of its fields are configured, and nothing else.

    Every value is replaced, one level down as well, so a nested address is not
    the hole this leaves. A field that resolved to nothing says so rather than
    being scrubbed: "not configured" is not a thing to hide, and it is usually
    the answer somebody is looking for.
    """
    try:
        entries = dict(value.to_dict() if hasattr(value, "to_dict") else value)
    except Exception:  # pylint: disable=broad-except  # pragma: no cover
        # A shape nothing here recognizes is one nothing here can redact.
        return SCRUBBED
    return {field: _field_value(field_value) for field, field_value in entries.items()}


def _field_value(value):
    if isinstance(value, dict):
        return {field: _field_value(field_value) for field, field_value in value.items()}
    return SCRUBBED if value else "<not set>"


def environment(environ=None):
    """The PartCAD variables of a process environment, sorted, secrets scrubbed.

    ``environ`` defaults to this process's own, which is what makes the same
    function answer for the client and for the daemon: each side calls it in the
    process whose environment is being asked about.
    """
    environ = os.environ if environ is None else environ
    for name in sorted(environ):
        if name.startswith(ENV_PREFIX):
            yield name, (SCRUBBED if is_auth_key(name) else environ[name])
