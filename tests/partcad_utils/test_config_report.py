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
    return dict(config_report.environment(entries))


# ---- the PC_ namespace -------------------------------------------------------


def test_only_partcad_variables_are_reported():
    reported = _env(PC_TAGS="build-machine", HOME="/root", AWS_SECRET_ACCESS_KEY=SECRET)

    assert reported == {"PC_TAGS": "build-machine"}


def test_the_variables_are_sorted():
    reported = _env(PC_OFFLINE="true", PC_CACHE_FILES="false", PC_TAGS="x")

    assert list(reported) == ["PC_CACHE_FILES", "PC_OFFLINE", "PC_TAGS"]


def test_an_environment_with_nothing_partcad_in_it_reports_nothing():
    assert _env(HOME="/root", PATH="/usr/bin") == {}


# ---- the auth-key pattern ----------------------------------------------------


def test_a_credential_is_named_but_never_printed():
    """The name is what says "this is configured"; the value is nobody's."""
    reported = _env(PC_REMOTE_SANDBOX_TOKEN=SECRET)

    assert reported == {"PC_REMOTE_SANDBOX_TOKEN": config_report.SCRUBBED}
    assert SECRET not in str(reported)


def test_every_word_the_pattern_knows_is_scrubbed():
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


def test_the_configuration_file_is_named_in_one_place(monkeypatch, tmp_path):
    """A report names the file the configuration was read from; reading it back
    from somewhere else is how a report becomes a lie."""
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))

    assert UserConfig.get_config_path() == str(home / ".partcad" / "config.yaml")
