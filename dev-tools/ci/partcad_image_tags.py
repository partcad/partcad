#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The tags of the PartCAD image, `ghcr.io/partcad/partcad`, on a release.

`publish-image` in `deploy.yml` pushes one immutable tag per release,
`<version>`, and two that move, `<major>.<minor>` and `latest`. Pushing them in
one `docker buildx build` was not enough: a push can stop after the version tag
and before the other two, and a re-run then found the version published, did
nothing, and succeeded with both aliases still on the previous release. So the
build pushes the version tag alone, and this moves the aliases onto it -- from
its digest, never by building again -- on every run, the re-run included:

    partcad_image_tags.py published IMAGE VERSION     # "true" or "false"
    partcad_image_tags.py aliases IMAGE VERSION       # move them where the rule says
    partcad_image_tags.py aliases IMAGE VERSION --check
                                                      # fail unless they are where it says

**The rule for an alias is the one `publish-plugin-dist` follows for its
branch: never backwards.** An alias that is absent, or carries an older release
than this one, is moved to this one; one that already carries it is left; one
that carries a *newer* release is left too, and said so -- that is a re-run of
an older release's run, which, as `publish-mcp-registry` does with a version
the registry already has, finds its work done by somebody else and stops. It
does not fail, unlike the branch, because the alias is not what this job exists
to publish: the version tag is, and it is there. Which release an alias carries
is read from the label every image of it has, `org.opencontainers.image.version`
(the Dockerfile sets it from `PARTCAD_VERSION`), and compared the way `sort -V`
compares, as the branch's check does. An alias whose release cannot be read is
an error rather than a guess, and so is any answer from the registry other than
"<the tag itself>: not found": treating a refused or timed-out inspection as an
absent tag is how `latest` would be moved backwards by a network hiccup. That
includes a "not found" about something else. With `--format`, buildx resolves
the tag and then fetches the manifests and configurations it references, and a
missing one of those fails as "could not fetch content descriptor <digest> ...
from remote: not found" -- about a tag that exists. Only containerd's resolver
puts the reference first ("<ref>: not found"), so that is the one read as absent.

`--check` is the same decision with nothing written, run without credentials:
the version tag and every alias must be pullable by anybody, and every alias
where the rule puts it.

Everything goes through `docker buildx imagetools`, which a GitHub runner has
without `setup-buildx-action`; the `docker` it runs is `PC_DOCKER` when set.
`tests/dev_tools/test_partcad_image_tags.py` runs it against a registry kept in
a dictionary.
"""

import argparse
import json
import os
import re
import subprocess
import sys

VERSION_LABEL = "org.opencontainers.image.version"
PLATFORMS = ("linux/amd64", "linux/arm64")


class TagError(Exception):
    """Something the rule cannot decide, or the registry would not answer."""


def docker_run(argv):
    """Run `docker <argv>`, returning (exit status, stdout, stderr)."""
    done = subprocess.run(
        [os.environ.get("PC_DOCKER", "docker")] + list(argv),
        capture_output=True,
        text=True,
        check=False,
    )
    return done.returncode, done.stdout, done.stderr


def version_key(version):
    """`version` as `sort -V` orders it, for the releases PartCAD makes: dotted numbers."""
    if not re.fullmatch(r"\d+(\.\d+)*", version or ""):
        raise TagError("'%s' is not a release this compares; it expects dotted numbers" % version)
    return tuple(int(part) for part in version.split("."))


def aliases_of(version):
    """The tags that move to `version`: its `<major>.<minor>`, and `latest`."""
    parts = version.split(".")
    if len(parts) < 3:
        raise TagError("'%s' has no patch number to drop for its <major>.<minor>" % version)
    return [".".join(parts[:2]), "latest"]


class Registry:
    """The image's tags, as `docker buildx imagetools` sees them."""

    def __init__(self, image, run=docker_run):
        self.image = image
        self.run = run

    def _inspect(self, ref, template):
        status, out, err = self.run(["buildx", "imagetools", "inspect", ref, "--format", template])
        if status != 0:
            # The tag itself, and not content it references (see the module's
            # docstring). `ref` is fully qualified, which is how buildx prints
            # it back.
            if re.search(r"(?:^|\s)%s: not found\b" % re.escape(ref), err):
                return None
            raise TagError("could not inspect %s: %s" % (ref, (err or out).strip()))
        try:
            return json.loads(out)
        except ValueError as e:
            raise TagError("%s inspected as something that is not JSON: %s" % (ref, e))

    def digest(self, tag):
        """The digest `<image>:<tag>` resolves to, or None when there is no such tag."""
        manifest = self._inspect("%s:%s" % (self.image, tag), "{{json .Manifest}}")
        if manifest is None:
            return None
        digest = manifest.get("digest")
        if not digest:
            raise TagError("%s:%s has no digest" % (self.image, tag))
        return digest

    def platforms(self, tag):
        """The platforms of `<image>:<tag>`'s images, as `os/arch`."""
        manifest = self._inspect("%s:%s" % (self.image, tag), "{{json .Manifest}}")
        if manifest is None:
            return set()
        found = set()
        for entry in manifest.get("manifests") or []:
            platform = entry.get("platform") or {}
            if platform.get("os") and platform.get("architecture"):
                found.add("%s/%s" % (platform["os"], platform["architecture"]))
        return found

    def release(self, tag):
        """The release `<image>:<tag>` is of, read from the label every one of its images carries."""
        ref = "%s:%s" % (self.image, tag)
        image = self._inspect(ref, "{{json .Image}}")
        if image is None:
            raise TagError("%s disappeared while it was being read" % ref)
        # One configuration for a single image, and one per platform, keyed by
        # platform, for a list of them -- which is what this image is.
        configs = [image] if "config" in image else list(image.values())
        versions = {((c.get("config") or {}).get("Labels") or {}).get(VERSION_LABEL) for c in configs}
        if len(versions) != 1 or None in versions or "" in versions:
            raise TagError(
                "%s does not say which release it is (%s labels: %s); move it by hand with "
                "'docker buildx imagetools create -t %s %s@<digest>'"
                % (ref, VERSION_LABEL, sorted(str(v) for v in versions), ref, self.image)
            )
        return versions.pop()

    def point(self, tag, digest):
        """Make `<image>:<tag>` the manifest `<image>@<digest>` is: a new tag on it, no build."""
        ref = "%s:%s" % (self.image, tag)
        status, out, err = self.run(["buildx", "imagetools", "create", "--tag", ref, "%s@%s" % (self.image, digest)])
        if status != 0:
            raise TagError("could not point %s at %s: %s" % (ref, digest, (err or out).strip()))


def decide(version, digest, alias_digest, alias_release):
    """What to do with one alias: "move", "keep" (it is this release) or "newer" (leave it).

    `alias_digest` is None for an alias that does not exist; `alias_release` is
    called for the release it carries only when that is needed.
    """
    if alias_digest is None:
        return "move"
    if alias_digest == digest:
        return "keep"
    carried = alias_release()
    if version_key(carried) > version_key(version):
        return "newer"
    # Older, or this release under another digest -- which only a version tag
    # overwritten by hand makes; the version tag is the one that is true.
    return "move"


def plan(registry, version):
    """The version tag's digest, and (alias, decision) for each alias."""
    version_key(version)
    digest = registry.digest(version)
    if digest is None:
        raise TagError(
            "%s:%s is not published, so there is nothing to point its aliases at" % (registry.image, version)
        )
    decisions = []
    for alias in aliases_of(version):
        decisions.append(
            (alias, decide(version, digest, registry.digest(alias), lambda alias=alias: registry.release(alias)))
        )
    return digest, decisions


def published(registry, version):
    return registry.digest(version) is not None


def move_aliases(registry, version, out=print):
    digest, decisions = plan(registry, version)
    for alias, decision in decisions:
        ref = "%s:%s" % (registry.image, alias)
        if decision == "move":
            registry.point(alias, digest)
            out("%s now points at %s (%s)." % (ref, version, digest))
        elif decision == "keep":
            out("%s points at %s already." % (ref, version))
        else:
            out(
                "::notice::%s carries %s, which is newer than %s, and is left there."
                % (ref, registry.release(alias), version)
            )
    # Read back, so that a create that said it worked and did not is a failure
    # here rather than a stale "latest" found by a user.
    _, after = plan(registry, version)
    wrong = [alias for alias, decision in after if decision == "move"]
    if wrong:
        raise TagError("%s did not move to %s" % (", ".join(wrong), version))


def check(registry, version, out=print):
    """Fail unless the version tag has both platforms and every alias is where the rule puts it."""
    problems = []
    try:
        digest, decisions = plan(registry, version)
    except TagError as e:
        raise TagError("%s -- if the package is private, make it public: %s" % (e, settings_url(registry.image)))
    missing = sorted(set(PLATFORMS) - registry.platforms(version))
    if missing:
        problems.append("%s:%s has no %s image" % (registry.image, version, ", ".join(missing)))
    for alias, decision in decisions:
        ref = "%s:%s" % (registry.image, alias)
        if decision == "move":
            problems.append("%s is not %s (%s)" % (ref, version, digest))
        elif decision == "keep":
            out("%s is %s (%s)." % (ref, version, digest))
        else:
            out("%s is a newer release, %s, which is where it belongs." % (ref, registry.release(alias)))
    if problems:
        raise TagError("; ".join(problems))
    out("%s:%s is %s, for %s." % (registry.image, version, digest, ", ".join(PLATFORMS)))


def settings_url(image):
    owner, _, name = image.split("/", 1)[-1].partition("/")
    return "https://github.com/orgs/%s/packages/container/%s/settings" % (owner, name)


def main(argv=None, run=docker_run, out=print, err=None):
    err = err or (lambda line: print(line, file=sys.stderr))
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("published", "aliases"):
        command = sub.add_parser(name)
        command.add_argument("image")
        command.add_argument("version")
        if name == "aliases":
            command.add_argument("--check", action="store_true", help="change nothing; fail unless they are right")
    args = parser.parse_args(argv)
    registry = Registry(args.image, run)
    try:
        if args.command == "published":
            out("true" if published(registry, args.version) else "false")
        elif args.check:
            check(registry, args.version, out)
        else:
            move_aliases(registry, args.version, out)
    except TagError as e:
        err("::error::%s" % e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
