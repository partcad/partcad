#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Package-level parameters: a declaration that says 'shared: true' is one value for its whole package.

Held here: the rule a package's declarations follow (all of a name shared, or
none; shared ones agree but for 'desc'), as PartCAD refuses a package that
breaks it and as 'pc lint' reports it; one value seen by every sharing object,
whether set through the user's configuration or saved by 'pc login'; caches
keyed on it following it; a value for one instance refused; and a package that
shares nothing behaving as it always did.
"""

import pytest
import yaml

import partcad as pc
import partcad.logging as pc_logging
from partcad.project_external_repository import ProjectExternalRepository
from partcad.shared_parameters import check_instance_value
from partcad_utils import parameters
from partcad_utils.assy_lint import CODE_PARAMETERS, PARTCAD_SCHEMA, get_schema, validate_source
from partcad_utils.user_config import UserConfig, save_parameter_overrides

TOKEN = {"type": "string", "shared": True, "default": "none"}

# A package of plugins for one website: a repository and a provider that need
# the same token, and an unrelated parameter of each that is not shared.
SITE = """\
repositories:
  site_repo:
    type: basic
    parameters:
      token:
        type: string
        shared: true
        desc: The token the repository signs its requests with
        default: none
      formats: {type: string, default: step}
providers:
  site_store:
    type: store
    parameters:
      token:
        type: string
        shared: true
        desc: The token the store signs its orders with
        default: none
      formats: {type: string, default: stl}
"""


@pytest.fixture(autouse=True)
def _no_errors_left_behind():
    yield
    pc_logging.reset_errors()


def _package(tmp_path, text, user_config=None, scripts=("site_repo", "site_store")):
    (tmp_path / "partcad.yaml").write_text(text)
    # The plugins' scripts: empty, since nothing here runs them.
    for script in scripts:
        (tmp_path / ("%s.py" % script)).write_text("")
    ctx = pc.Context(str(tmp_path), user_config=user_config or UserConfig())
    return ctx, ctx.get_project("//")


def _caller(parameters_section):
    caller = UserConfig()
    for key, values in parameters_section.items():
        caller.parameter_config[key] = values
    return caller


def _token(project):
    repo = project.get_repository_config("site_repo")["parameters"]["token"]
    store = project.get_provider_config("site_store")["parameters"]["token"]
    return repo, store


# ---- the rule, as both ends read it ----------------------------------------


def _problems(sections):
    return parameters.shared_parameter_problems(parameters.parameter_declarations(sections))


def test_all_declarations_of_a_name_say_shared_or_none_does():
    found = _problems(
        {
            "repository": {"site_repo": {"parameters": {"token": TOKEN}}},
            "provider": {"site_store": {"parameters": {"token": {"type": "string", "default": "none"}}}},
        }
    )
    assert [problem.name for problem in found] == ["token"]
    assert "declared 'shared: true' by the repository 'site_repo', and not by the provider 'site_store'" in (
        found[0].message
    )
    assert {d.object for d in found[0].declarations} == {"site_repo", "site_store"}


@pytest.mark.parametrize(
    "other, differs",
    [
        ({**TOKEN, "default": "other"}, "'default'"),
        ({**TOKEN, "type": "int", "default": 1}, "'default', 'type'"),
        ({**TOKEN, "enum": ["none", "x"]}, "'enum'"),
    ],
)
def test_shared_declarations_agree_on_everything_but_desc(other, differs):
    found = _problems(
        {
            "repository": {"site_repo": {"parameters": {"token": TOKEN}}},
            "provider": {"site_store": {"parameters": {"token": other}}},
        }
    )
    assert len(found) == 1
    assert "declared differently" in found[0].message and "(%s)" % differs in found[0].message


def test_shared_declarations_may_differ_in_desc_and_in_how_they_are_written():
    assert (
        _problems(
            {
                "repository": {"site_repo": {"parameters": {"size": {"type": "int", "default": 3, "shared": True}}}},
                "part": {"bolt": {"parameters": {"size": {"default": 3, "type": "int", "shared": True, "desc": "M"}}}},
            }
        )
        == []
    )


def test_names_nobody_shares_are_not_compared():
    """'size' meaning two things in two objects is what a parameter that is not shared is for."""
    assert (
        _problems(
            {
                "part": {"bolt": {"parameters": {"size": 3}}, "nut": {"parameters": {"size": "M3"}}},
                "sketch": {"outline": {"parameters": {"size": {"type": "float", "shared": False}}}},
            }
        )
        == []
    )


def test_an_interface_s_freedom_of_movement_is_not_a_value_to_share():
    found = parameters.parameter_declarations(
        {"interface": {"slot": {"parameters": {"moveX": [0, 10, 0], "size": {"type": "int", "shared": True}}}}}
    )
    assert sorted(found) == ["size"]


# ---- what the user's configuration sets it to ------------------------------


def test_an_override_through_any_sharing_object_sets_it():
    found = parameters.shared_override("//site", "token", ["repo", "store"], {"//site:store": {"token": "abc"}})
    assert found == parameters.SharedValue(True, "abc", "//site:store")


def test_the_package_s_own_entry_sets_it():
    found = parameters.shared_override("//site", "token", ["repo", "store"], {"//site": {"token": "abc"}})
    assert found == parameters.SharedValue(True, "abc", "//site")


def test_an_object_s_entry_is_more_specific_than_the_package_s():
    found = parameters.shared_override(
        "//site", "token", ["repo", "store"], {"//site": {"token": "old"}, "//site:repo": {"token": "new"}}
    )
    assert (found.value, found.source) == ("new", "//site:repo")


def test_object_entries_that_disagree_are_not_guessed_between():
    found = parameters.shared_override(
        "//site",
        "token",
        ["repo", "store"],
        {"//site": {"token": "package"}, "//site:repo": {"token": "a"}, "//site:store": {"token": "b"}},
    )
    assert (found.value, found.source) == ("package", "//site")
    assert "'//site:repo', '//site:store'" in found.conflict
    nothing = parameters.shared_override(
        "//site", "token", ["repo", "store"], {"//site:repo": {"token": "a"}, "//site:store": {"token": "b"}}
    )
    assert not nothing.found and nothing.conflict


def test_entries_that_spell_one_value_differently_agree():
    found = parameters.shared_override(
        "//site", "size", ["repo", "store"], {"//site:repo": {"size": "4"}, "//site:store": {"size": 4}}
    )
    assert found.found and not found.conflict


# ---- a package as PartCAD loads it -----------------------------------------


def test_every_sharing_object_has_the_one_value(tmp_path):
    _, project = _package(tmp_path, SITE, _caller({"//:site_store": {"token": "abc"}}))

    repo, store = _token(project)
    # Set through the store, seen by the repository: one declaration, held once.
    assert repo is store
    assert repo["default"] == "abc"
    # What is not shared stays each object's own.
    assert project.get_repository_config("site_repo")["parameters"]["formats"]["default"] == "step"
    assert project.get_provider_config("site_store")["parameters"]["formats"]["default"] == "stl"


def test_a_change_to_the_value_is_seen_by_every_sharing_object(tmp_path):
    _, project = _package(tmp_path, SITE)
    repo, store = _token(project)
    assert repo["default"] == "none"

    store["default"] = "changed"
    assert project.get_repository_config("site_repo")["parameters"]["token"]["default"] == "changed"


def test_the_package_entry_of_the_user_s_configuration_sets_it(tmp_path):
    _, project = _package(tmp_path, SITE, _caller({"//": {"token": "for-the-package"}}))
    assert [declaration["default"] for declaration in _token(project)] == ["for-the-package"] * 2


def test_an_extra_param_through_one_object_wins_over_the_package_entry(tmp_path):
    caller = _caller({"//": {"token": "from-the-file"}})
    _, project_before = _package(tmp_path, SITE, caller)
    assert _token(project_before)[0]["default"] == "from-the-file"

    object_id, key, value = parameters.parse_override("//:site_repo.token=from-the-command-line")
    caller.parameter_config[object_id] = {key: value}
    _, project = _package(tmp_path, SITE, caller)
    assert [declaration["default"] for declaration in _token(project)] == ["from-the-command-line"] * 2


def test_a_login_through_one_plugin_logs_in_every_plugin_sharing_it(tmp_path):
    """What 'pc login' saves for a shared parameter is the package's, and serves the plugin it did not run."""
    config = tmp_path / "config.yaml"
    # An earlier login, through the store, before the token was shared.
    config.write_text("parameters:\n  //:site_store:\n    token: stale\n    session: kept\n")
    package = tmp_path / "package"
    package.mkdir()

    # What the CLI does with the daemon's answer ('pc login //:site_repo').
    save_parameter_overrides("//:site_repo", {"token": "fresh", "user": "me"}, str(config), "//", ["token"])

    saved = yaml.safe_load(config.read_text())["parameters"]
    assert saved == {
        "//": {"token": "fresh"},
        "//:site_store": {"session": "kept"},
        "//:site_repo": {"user": "me"},
    }
    _, project = _package(package, SITE, UserConfig.from_dict(yaml.safe_load(config.read_text())))
    assert [declaration["default"] for declaration in _token(project)] == ["fresh", "fresh"]


def test_the_daemon_says_which_logged_in_values_are_shared(tmp_path, monkeypatch):
    """'plugin.login' names the package and the shared parameters, which is what the client saves by."""
    from partcad_service_json_rpc.core import operations

    ctx, project = _package(tmp_path, SITE)
    repository = project.get_repository("site_repo")

    async def login(browser, check=False, non_interactive=False, values=None):
        return {"parameters": {"token": "abc", "formats": "stl"}, "message": "logged in"}

    monkeypatch.setattr(repository, "login", login)

    class Session:
        partcad = pc

    monkeypatch.setattr(operations, "_ctx", lambda session, params: ctx)
    answer = operations.plugin_login(Session(), {"plugin": "//:site_repo"})
    assert answer["package"] == "//" and answer["shared"] == ["token"]
    assert answer["parameters"] == {"token": "abc", "formats": "stl"}


def test_declarations_that_disagree_are_refused_as_the_package_loads(tmp_path):
    _, project = _package(
        tmp_path,
        SITE.replace(
            "default: none\n      formats: {type: string, default: stl}",
            "default: x\n      formats: {type: string, default: stl}",
        ),
    )

    for kind, name in (("repository", "site_repo"), ("provider", "site_store")):
        reason = project.get_broken_object_reason(kind, name)
        assert "The shared parameter 'token' is declared differently" in reason
    assert project.get_repository_config("site_repo") is None
    assert project.get_provider_config("site_store") is None
    assert pc_logging.had_errors


def test_a_value_for_one_instance_is_refused_unless_it_is_the_package_s():
    holder = dict(TOKEN)
    check_instance_value(holder, "none", "token", "//site:repo")
    with pytest.raises(ValueError, match="shared by its package.*'parameters: //site:'"):
        check_instance_value(holder, "mine", "token", "//site:repo")


def test_a_parametrized_instance_cannot_set_a_shared_parameter(tmp_path):
    _, project = _package(
        tmp_path,
        "sketches:\n"
        "  outline:\n"
        "    type: basic\n"
        "    circle: 1.5\n"
        "    parameters:\n"
        "      size: {type: float, default: 3.0, shared: true}\n"
        "      depth: {type: float, default: 1.0}\n",
        scripts=(),
    )
    assert project.get_sketch("outline;depth=2.0", quiet=True) is not None
    assert project.get_sketch("outline;size=3", quiet=True) is not None, "the package's value is no change"
    with pytest.raises(ValueError, match="'size' of 'outline;size=4' is shared by its package.*'parameters: //:'"):
        project.get_sketch("outline;size=4", quiet=True)


# ---- caches -----------------------------------------------------------------


def test_the_repository_cache_key_follows_the_shared_value(tmp_path):
    """Logging in through the store changes what the repository answers, and so its cache key."""
    (tmp_path / "partcad.yaml").write_text(SITE)
    for script in ("site_repo", "site_store"):
        (tmp_path / ("%s.py" % script)).write_text("")

    def key(section):
        ctx = pc.Context(str(tmp_path), user_config=_caller(section))
        ctx.get_project("//")
        served = ProjectExternalRepository(ctx, "//ext", str(tmp_path / "ext"), plugin_ref="//:site_repo")
        return served._plugin_overrides()

    before = key({})
    through_the_store = key({"//:site_store": {"token": "abc"}})
    for_the_package = key({"//": {"token": "abc"}})
    assert before != through_the_store
    assert through_the_store == for_the_package, "one value, however it was set"
    assert key({"//": {"token": "other"}}) != for_the_package


# ---- nothing shared, nothing changed ---------------------------------------


def test_a_parameter_that_is_not_shared_is_each_object_s_own(tmp_path):
    text = SITE.replace("        shared: true\n", "")
    _, project = _package(tmp_path, text, _caller({"//:site_store": {"token": "abc"}, "//": {"token": "pkg"}}))

    repo, store = _token(project)
    assert repo is not store
    assert (repo["default"], store["default"]) == ("none", "abc")
    assert project.shared_parameters.names() == []


# ---- what 'pc lint' says ----------------------------------------------------


def test_lint_reports_every_declaration_of_a_name_that_disagrees():
    config = SITE.replace(
        "        shared: true\n        desc: The token the store", "        desc: The token the store"
    )
    found = [d for d in validate_source(config, get_schema(PARTCAD_SCHEMA)) if d.code == CODE_PARAMETERS]
    assert len(found) == 2
    lines = config.split("\n")
    assert all(lines[d.line][d.column :].startswith("token:") for d in found)
    assert "and not by the provider 'site_store'" in found[0].message


def test_lint_accepts_a_package_that_shares_a_parameter():
    assert validate_source(SITE, get_schema(PARTCAD_SCHEMA)) == []
