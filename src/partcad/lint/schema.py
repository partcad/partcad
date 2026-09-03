import json
import os
import aiofiles

from ..project import Project
from ..context import Context
from .. import logging as pc_logging
from partcad.cache_hash import CacheHash
from .lint import Linting, Severity, LintingReport

# Shared with every client's `pc lint --file`, which is why it is not in this
# package: the daemon checks a package's files when it walks the package graph,
# and a client checks the one file being edited in its own process. Two copies
# of that check would let an editor and CI disagree about a file.
from partcad_utils.assy_lint import (
    FLAVOR_ASSEMBLY,
    FLAVOR_SCENE,
    SEVERITY_WARNING,
    is_assy_file,
    schema_for_file,
    validate_source,
)


class YamlLinting(Linting):
    """Check the YAML documents of a package against the schemas that govern them.

    A `partcad.yaml` and an `.assy` are the same kind of document -- a Jinja2
    template that renders to YAML and then has to match a schema -- so they are
    checked by the same code, `partcad_utils.assy_lint.validate_source`, which
    masks the template before parsing and reports each finding at the source
    line and column it came from. What the two subclasses below differ in is
    only which files they walk and which schema each file gets.

    That sharing is the point rather than a convenience. `validate_source` is
    also what every client runs over the single file somebody is editing
    (`partcad_client.lint`, reached by `pc lint --file`), so a finding reads the
    same, at the same position, in the editor and in CI. A second implementation
    here -- handing the raw file to `yaml.safe_load` and reporting whatever
    `jsonschema` raised first -- is what that used to be, and it disagreed with
    the editor twice over: it stopped at one finding per file, and it called a
    templated `partcad.yaml` broken YAML.
    """

    def flavor(self, name: str, target: str) -> str:
        """What ``target`` is read as. Only an ASSY file has an answer."""
        return None

    def schema(self, name: str, target: str) -> dict:
        return schema_for_file(target, self.flavor(name, target))

    def get_hash(self, name: str, target: str) -> CacheHash:
        # The schema is half of what produced a finding: a cached result for an
        # unchanged file is only valid while the schema it was checked against
        # is the same one. The flavor is in here for the same reason and is not
        # implied by anything else in the hash: moving a file's declaration from
        # 'assemblies:' to 'scenes:' changes which schema it is checked against
        # without touching the file.
        hash = super().get_hash(name, target)
        hash.add_string(json.dumps(self.schema(name, target), sort_keys=True))
        hash.add_string(str(self.flavor(name, target)))
        return hash

    async def validate(self, ctx: Context, package: Project, target: str, lint_ctx: dict = {}) -> LintingReport:
        lint_result = LintingReport(package.name)

        # 'open' is inside the try as well: it is what raises when the entry is a
        # directory named '*.assy', or was removed between the listing and here,
        # and nothing above catches that - one unreadable entry would end the
        # whole 'pc lint' run instead of being reported as a failed check.
        try:
            async with aiofiles.open(target, mode="r") as file:
                raw = await file.read()
        except (OSError, UnicodeDecodeError) as err:
            lint_result.add(Severity.FAILED, f"Failed to read {os.path.basename(target)}: {err}")
            return lint_result

        try:
            diagnostics = validate_source(raw, self.schema(package.name, target))
        except Exception as exc:  # pylint: disable=broad-except
            pc_logging.debug(package.name, str(exc))
            lint_result.add(Severity.FAILED, f"Internal Error: Failed to check {os.path.basename(target)}")
            return lint_result

        for diagnostic in diagnostics:
            severity = Severity.WARNING if diagnostic.severity == SEVERITY_WARNING else Severity.FAILED
            lint_result.add(severity, diagnostic.format(os.path.basename(target)))

        return lint_result


class SchemaLinting(YamlLinting):
    """Check a package's own `partcad.yaml` against the configuration schema.

    One target per package, and it is the file that decides whether the package
    exists at all -- so it is checked as text, exactly as it is on disk, rather
    than through the loaded configuration. A `partcad.yaml` broken badly enough
    that the package will not load is precisely the one worth a finding, and by
    then there is no `Project` to ask.
    """

    def get_targets(self, ctx: Context, package: Project) -> list[str]:
        return [os.path.join(package.config_dir, "partcad.yaml")]


class AssySchemaLinting(YamlLinting):
    """Check every ASSY file of a package against the ASSY schema.

    This is the *package* half of ASSY checking: it needs the package graph to
    know which packages, and which of their files, to walk, which is what makes
    it daemon work. Checking a single file needs none of that and is done by the
    client itself (`partcad_client.lint`).

    The package graph is also what makes this half *exact* about which schema a
    file is checked against. A file an `assemblies:` entry points at is an
    assembly, one only a `scenes:` entry points at is a scene, and a scene is
    checked without `how` (see `partcad.scene`). A client editing the file has
    to guess at that; here the declaration is in hand.
    """

    def __init__(self, name: str) -> None:
        super().__init__(name)
        # (package name, target) -> the flavor its declaration makes it, filled
        # in by 'get_targets'. Kept here because the two methods that need it -
        # the hash and the check - are handed the target path and not the
        # package, and 'get_targets' is called for a package before either of
        # them runs against its targets.
        self._flavors: dict = {}

    def flavor(self, name: str, target: str) -> str:
        return self._flavors.get((name, target), FLAVOR_ASSEMBLY)

    def get_targets(self, ctx: Context, package: Project) -> list[str]:
        config_dir = package.config_dir
        if not os.path.isdir(config_dir):
            return []
        # Through the shared helper, which matches the extension case
        # insensitively: 'pc lint --file' and the extension already check a
        # 'Logo.ASSY', and the package walk skipping it is exactly the
        # editor/CI disagreement this module exists to prevent. It also excludes
        # the package's own 'partcad.yaml', which the checker knows a schema for
        # too and which 'SchemaLinting' above is the one to walk.
        targets = sorted(
            os.path.join(config_dir, f)
            for f in os.listdir(config_dir)
            if is_assy_file(f) and os.path.isfile(os.path.join(config_dir, f))
        )
        declared_by_assembly = self._declared_files(package, "assembly")
        declared_by_scene = self._declared_files(package, "scene")
        for target in targets:
            key = os.path.realpath(target)
            # An assembly wins: the file has to satisfy the full schema for that
            # assembly to be readable, whatever else also points at it.
            if key in declared_by_scene and key not in declared_by_assembly:
                self._flavors[(package.name, target)] = FLAVOR_SCENE
            else:
                self._flavors.pop((package.name, target), None)
        return targets

    @staticmethod
    def _declared_files(package: Project, kind: str) -> set:
        """The ASSY files this package's objects of 'kind' point at."""
        files = set()
        for name, config in (package.object_configs(kind) or {}).items():
            if not isinstance(config, dict) or config.get("type") != "assy":
                continue
            declared = config.get("path") or "%s.assy" % config.get("orig_name", name)
            files.add(os.path.realpath(os.path.join(package.config_dir, declared)))
        return files
