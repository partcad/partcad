#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What a status report may say, and what it may never say.

`pc config`, `pc system status config|env` and their `pc daemon status ...`
counterparts all print through `partcad_utils.config_report`, which is the whole
point of it being there: the client and the daemon are not the same machine once
a daemon can be remote, and two copies of a redaction rule are one copy that
stops redacting.
"""

from partcad_utils import config_report
from partcad_utils.user_config import UserConfig

# A value distinctive enough that an assertion over the whole report finds it
# wherever it leaked to.
SECRET = "s3cr3t-do-not-print"


def _env(**entries):
    """The report `environment()` produces for a made-up process environment.

    Passed in rather than monkeypatched onto `os.environ`, so that a test states
    the whole environment it is asking about -- including what is *not* in it,
    which is half of what these assertions are.
    """
    return dict(config_report.environment(entries))


# ---- the PC_ namespace -------------------------------------------------------


def test_only_partcad_variables_are_reported():
    """Everything else in a process environment belongs to somebody else."""
    reported = _env(PC_TAGS="build-machine", HOME="/root", AWS_SECRET_ACCESS_KEY=SECRET)

    assert reported == {"PC_TAGS": "build-machine"}


def test_the_variables_are_sorted():
    """So that two reports of the same environment can be diffed against each other."""
    reported = _env(PC_OFFLINE="true", PC_CACHE_FILES="false", PC_TAGS="x")

    assert list(reported) == ["PC_CACHE_FILES", "PC_OFFLINE", "PC_TAGS"]


def test_an_environment_with_nothing_partcad_in_it_reports_nothing():
    """The empty answer the commands turn into "No PC_* environment variables are set"."""
    assert _env(HOME="/root", PATH="/usr/bin") == {}


# ---- the auth-key pattern ----------------------------------------------------


def test_a_credential_is_named_but_never_printed():
    """The name is what says "this is configured"; the value is nobody's."""
    reported = _env(PC_REMOTE_SANDBOX_TOKEN=SECRET)

    assert reported == {"PC_REMOTE_SANDBOX_TOKEN": config_report.SCRUBBED}
    assert SECRET not in str(reported)


def test_every_word_the_pattern_knows_is_scrubbed():
    """One case per alternative, so that editing the pattern cannot quietly drop one.

    Spelled with a made-up PC_SOMETHING_* name rather than a real option: what is
    under test is the rule, and a rule that only works on the names that happen
    to exist today is a rule that stops working when the next one is added.
    """
    for name in (
        "PC_SOMETHING_TOKEN",
        "PC_SOMETHING_TOKENS",
        "PC_SOMETHING_SECRET",
        "PC_SOMETHING_SECRETS",
        "PC_SOMETHING_PASSWORD",
        "PC_SOMETHING_PASSWD",
        "PC_SOMETHING_KEY",
        "PC_SOMETHING_KEYS",
        "PC_KEY_SOMETHING",
        "PC_SOMETHING_CREDENTIAL",
        "PC_SOMETHING_CREDENTIALS",
        "PC_SOMETHING_AUTH",
        "PC_AUTH_SOMETHING",
    ):
        assert _env(**{name: SECRET}) == {name: config_report.SCRUBBED}, name


def test_a_name_that_merely_contains_the_letters_is_not_a_credential():
    """Matched between underscores, so 'MONKEY' is not a key and 'NAMESPACE' is
    not a password. A rule that hides settings is a rule people turn off."""
    reported = _env(PC_MONKEY_BARS="fine", PC_CACHE_REMOTE_NAMESPACE="partcad")

    assert reported == {"PC_CACHE_REMOTE_NAMESPACE": "partcad", "PC_MONKEY_BARS": "fine"}


def test_the_sentry_dsn_is_reported_as_it_is():
    """PartCAD's own default DSN is a literal in user_config.py and `pc config`
    prints whichever is in effect, so hiding it here would only hide, from the
    report people paste into a bug, where their telemetry went."""
    dsn = "https://abc123@o1.ingest.sentry.io/2"

    assert _env(PC_TELEMETRY_SENTRY_DSN=dsn) == {"PC_TELEMETRY_SENTRY_DSN": dsn}


def test_every_partcad_variable_the_source_names_is_classified_deliberately():
    """The PC_* names PartCAD binds today, and which side of the line each is on.

    Written out rather than derived, so that a new option whose name says it
    carries a credential cannot arrive unnoticed: adding one here is how
    somebody states which it is.
    """
    credentials = {"PC_REMOTE_SANDBOX_TOKEN"}
    settings = {
        "PC_CACHE_REMOTE_NAMESPACE",
        "PC_CACHE_REMOTE_SERVER",
        "PC_CACHE_S3_BUCKET",
        "PC_CONTAINER_ALLOWED_COMMANDS",
        "PC_INTERNAL_STATE_DIR",
        "PC_LOG_LEVEL",
        "PC_OFFLINE",
        "PC_PYTHON_SANDBOX",
        "PC_REMOTE_SANDBOX",
        "PC_TAGS",
        "PC_TELEMETRY_SENTRY_DSN",
        "PC_TELEMETRY_TYPE",
        "PC_THREADS_MAX",
        "PC_USE_DOCKER",
    }

    assert {name for name in credentials if config_report.is_auth_key(name)} == credentials
    assert not {name for name in settings if config_report.is_auth_key(name)}


# ---- the resolved configuration ----------------------------------------------


def test_the_remote_sandbox_token_is_reported_as_set_and_never_printed(monkeypatch, tmp_path):
    """The configuration half of the same rule, which names its secrets one by one."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PC_REMOTE_SANDBOX_TOKEN", SECRET)

    printed = dict(config_report.resolved_options(UserConfig()))

    assert printed["remote_sandbox_token"] == "<set>"
    assert SECRET not in str(printed)


def test_git_credentials_are_scrubbed_but_the_hosts_they_are_for_are_not(monkeypatch, tmp_path):
    """Which host has credentials configured is the question somebody debugging
    a private dependency is asking; the password is not part of the answer."""
    home = tmp_path / "home"
    (home / ".partcad").mkdir(parents=True)
    (home / ".partcad" / "config.yaml").write_text(
        "git:\n"
        "  auth:\n"
        "    github.com:\n"
        "      username: octocat\n"
        "      password: %s\n"
        "    gitlab.com:\n"
        "      sshKey: ~/.ssh/id_work\n"
        "      sshKeyPassphrase: %s\n" % (SECRET, SECRET)
    )
    monkeypatch.setenv("HOME", str(home))

    printed = dict(config_report.resolved_options(UserConfig()))

    assert printed["git_auth"] == {
        "github.com": {"username": "octocat", "password": config_report.SCRUBBED},
        "gitlab.com": {"sshKey": "~/.ssh/id_work", "sshKeyPassphrase": config_report.SCRUBBED},
    }
    assert SECRET not in str(printed)


def test_personal_information_is_reported_as_fields_and_never_as_values(monkeypatch, tmp_path):
    """A name and a postal address are the whole of what the 'user' section is.

    Which fields are configured is the diagnostic somebody wants -- "why does my
    BOM have no address on it" -- and none of the values is any part of it. This
    output is what people paste into bug reports and screen recordings.
    """
    home = tmp_path / "home"
    (home / ".partcad").mkdir(parents=True)
    (home / ".partcad" / "config.yaml").write_text(
        "user:\n"
        "  name: Ada Lovelace\n"
        "  email: ada@example.com\n"
        "  shippingAddress:\n"
        "    street: 12 Marylebone Road\n"
        "    city: London\n"
    )
    monkeypatch.setenv("HOME", str(home))

    printed = dict(config_report.resolved_options(UserConfig()))
    pii = printed["pii_config"]

    # The field names survive; every value, nested ones included, does not.
    assert set(pii) >= {"name", "email", "shippingAddress"}
    assert pii["name"] == config_report.SCRUBBED
    assert pii["email"] == config_report.SCRUBBED
    assert pii["shippingAddress"]["street"] == config_report.SCRUBBED
    assert pii["shippingAddress"]["city"] == config_report.SCRUBBED
    for leaked in ("Ada Lovelace", "ada@example.com", "Marylebone", "London"):
        assert leaked not in str(printed), leaked


def test_personal_information_nobody_configured_says_so(monkeypatch, tmp_path):
    """Why this is not a "<set>"/"<not set>" secret.

    PIIConfig populates 'shippingAddress' and 'billingAddress' whether or not
    anything was configured, so the section is always truthy -- a report keyed
    off that alone would claim personal information is on file for a machine
    that has never been told any.
    """
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    pii = dict(config_report.resolved_options(UserConfig()))["pii_config"]

    assert pii == {"shippingAddress": {}, "billingAddress": {}}


def test_the_configuration_file_is_named_in_one_place(monkeypatch, tmp_path):
    """A report names the file the configuration was read from; reading it back
    from somewhere else is how a report becomes a lie."""
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))

    assert UserConfig.get_config_path() == str(home / ".partcad" / "config.yaml")
