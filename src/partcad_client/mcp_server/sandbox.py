#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Which files an agent may name through `pc mcp`.

An agent's tool call is input from a model, and a model can be talked into
anything by the text it reads -- a README in a dependency, a description in a
catalog. So a path in a tool call is checked before it is used: it has to lie
inside the workspace, or inside a directory the user named with
``--allow-path``, and not inside a hidden directory there (``.git``, ``.env``,
an editor's settings). ``--allow-any-path`` turns the check off, for the user
who wants that and says so.

The check resolves the path first -- symlinks and ``..`` included -- so a link
inside the workspace pointing out of it is outside it. It is a check on what the
agent *names*, not a jail: the daemon still reads whatever a package's own
configuration points at, which is the package author's business and not the
agent's.
"""

import os
from pathlib import Path
from typing import Iterable


class OutsideScope(ValueError):
    """A path an agent named that is not one it may use."""


class PathScope:
    """The directories an agent's paths must lie in.

    ``roots[0]`` is the workspace, which is also what a relative path is
    relative to.
    """

    def __init__(self, roots: Iterable[str], unrestricted: bool = False):
        self.roots = [Path(root).resolve() for root in roots]
        self.unrestricted = unrestricted

    @property
    def base(self) -> Path:
        return self.roots[0]

    def describe(self) -> str:
        if self.unrestricted:
            return "any path (--allow-any-path)"
        return ", ".join(str(root) for root in self.roots)

    def check(self, path: str) -> Path:
        """The absolute, resolved form of ``path``, or :class:`OutsideScope`.

        Relative to the workspace, because that is what an agent working in it
        means -- and never to this process's working directory, which is
        whatever the client happened to start it in.
        """
        if not isinstance(path, str) or not path.strip():
            raise OutsideScope("A path has to be a non-empty string, not %r" % (path,))
        candidate = Path(os.path.expanduser(path))
        if not candidate.is_absolute():
            candidate = self.base / candidate
        resolved = candidate.resolve()
        if self.unrestricted:
            return resolved
        for root in self.roots:
            try:
                relative = resolved.relative_to(root)
            except ValueError:
                continue
            hidden = next((part for part in relative.parts if part.startswith(".")), None)
            if hidden is not None:
                raise OutsideScope(
                    "%s is or is inside '%s', which is hidden and this agent may not use" % (path, hidden)
                )
            return resolved
        raise OutsideScope(
            "%s is outside the folders this agent may use (%s); the user can allow another one by starting the "
            "server with `pc mcp --allow-path DIR`" % (path, self.describe())
        )

    def relative(self, path: Path) -> str:
        """``path`` as the agent should be shown it: relative to the workspace when it is in it."""
        try:
            return path.relative_to(self.base).as_posix()
        except ValueError:
            return str(path)
