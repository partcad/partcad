#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A package's shared parameters: one value per name, held once for every object declaring it.

A parameter declared with 'shared: true' is a parameter of the package rather
than of its object (see 'partcad_utils.parameters', which says what that means
and which declarations a package may not have together). This is where a
package keeps the value: one declaration dictionary per name -- the *holder* --
which becomes the declaration in the 'parameters:' of every object that shares
it. So it is literally one Python object, and whatever reads
'config["parameters"][name]["default"]' of any of them reads the package's value,
and whatever writes it writes it for all of them.

What the value is is settled when the holder is made, once per package and
context, from the same places a parameter's value always came from:

- the default the package declares, which all the shared declarations agree on;
- the user's configuration ('~/.partcad/config.yaml' 'parameters:', with
  '--extra-param' on top, and what 'pc login' saved there), read for the
  package as a whole rather than for one object: see
  'partcad_utils.parameters.shared_override'.

A value given for a single instance -- in an object's name ('repo;token=...') or
an enrich's 'with:' -- is not one of those places. Such a value describes one
object, and a shared parameter is the package's: letting it change the package
would make every other object's value depend on which object was asked for
first, and letting it apply to that instance alone would be the one thing
'shared' says cannot happen. So it is refused, unless it is the value the
package already has (see 'check_instance_value').

A changed configuration is a new context in a daemon (see 'context_create' in
the JSON-RPC service), and every cache keyed on an object's parameters keys on
the values in its declaration, which are the holder's: so a changed shared value
reaches every object sharing it, and every cache keyed on any of them.
"""

import copy
import threading
import typing

from partcad_utils import parameters as pc_parameters

from . import logging as pc_logging
from .config import declared_parameter_type, parameter_overrides


class SharedParameters:
    """The shared parameters of one package. See the module docstring."""

    def __init__(self, project):
        self.project = project
        # name -> the holder: the one declaration every sharing object has.
        self._holders: dict[str, dict] = {}
        # name -> the declaration the package writes, expanded: what a holder
        # is made from, since an object's own copy may already carry that
        # object's override by the time it is bound.
        self._declared: dict[str, dict] = {}
        # name -> the objects of the package declaring it, in declaration order.
        self._sharers: dict[str, list] = {}
        # name -> why the package's declarations of it are refused.
        self.refused: dict[str, str] = {}
        self._lock = threading.RLock()

    def load(self, sections: typing.Mapping) -> list:
        """Read what the package declares, and answer the problems with it.

        ``sections`` is {kind: {object: config}}, as for
        'partcad_utils.parameters.parameter_declarations'. Returns the
        'SharedProblem's found; the names they are about are not shared by
        anything here afterwards (see 'bind').
        """
        declarations = pc_parameters.parameter_declarations(sections)
        problems = pc_parameters.shared_parameter_problems(declarations)
        with self._lock:
            for problem in problems:
                self.refused.setdefault(problem.name, problem.message)
            for name, found in declarations.items():
                if name in self.refused or not any(pc_parameters.is_shared(d.declaration) for d in found):
                    continue
                self._declared.setdefault(name, found[0].declaration)
                sharers = self._sharers.setdefault(name, [])
                for declaration in found:
                    if declaration.object not in sharers:
                        sharers.append(declaration.object)
        return problems

    def names(self) -> list:
        """The names this package declares shared, as far as it has been read."""
        with self._lock:
            return sorted(set(self._declared) | set(self._holders))

    def sharers(self, name: str) -> list:
        """The objects of this package sharing 'name', as far as it has been read."""
        with self._lock:
            return list(self._sharers.get(name, ()))

    def holder(self, name: str, declaration: dict = None, object_name: str = None) -> typing.Optional[dict]:
        """The one declaration of the shared parameter 'name', made the first time it is asked for.

        ``declaration`` and ``object_name`` are those of the object asking,
        for a name the package's own 'partcad.yaml' did not declare -- an object
        an enrich made out of another package's, one a plugin-backed package
        listed -- which the first such object then declares for the package.
        None when there is nothing to make it from.
        """
        with self._lock:
            found = self._holders.get(name)
            if found is not None:
                if object_name is not None and object_name not in self._sharers.setdefault(name, []):
                    self._sharers[name].append(object_name)
                return found
            base = self._declared.get(name)
            if base is None:
                if declaration is None:
                    return None
                base = pc_parameters.normalize_parameters({name: copy.deepcopy(declaration)})[name]
            sharers = self._sharers.setdefault(name, [])
            if object_name is not None and object_name not in sharers:
                sharers.append(object_name)
            made = copy.deepcopy(base)
            made[pc_parameters.SHARED] = True
            self._resolve(name, made)
            self._holders[name] = made
            return made

    def _resolve(self, name: str, holder: dict) -> None:
        """Set 'holder' to what the user's configuration makes the shared parameter 'name'."""
        overrides = parameter_overrides(getattr(self.project.ctx, "user_config", None))
        found = pc_parameters.shared_override(self.project.name, name, self._sharers.get(name, ()), overrides)
        if found.conflict:
            pc_logging.error(found.conflict)
        if not found.found:
            return
        try:
            value = pc_parameters.coerce_parameter_value(
                declared_parameter_type(holder),
                found.value,
                name,
                found.source,
                item_type=pc_parameters.array_item_type(holder),
            )
        except (ArithmeticError, TypeError, ValueError) as e:
            pc_logging.error(
                "The override of the shared parameter '%s' of '%s' cannot be used: %s" % (name, found.source, e)
            )
            return
        # Held to the declaration's 'min', 'max' and 'enum' as any other
        # override is ('config.apply_user_parameter_overrides', which passes a
        # shared parameter over to this): said, and the declared default stands.
        outside = pc_parameters.value_problem(holder, value, name, found.source)
        if outside is not None:
            pc_logging.error("The override of the shared parameter '%s' is not used: %s" % (name, outside))
            return
        holder["default"] = value

    def bind(self, object_name: str, config) -> None:
        """Make each shared parameter 'config' declares the package's one declaration of it.

        In place, and idempotently. Nothing else writes the user's overrides into
        a shared declaration ('config.apply_user_parameter_overrides' passes over
        one), so what an object's normalizing leaves in the holder is what the
        package resolved. Raises ``ValueError`` for a declaration this package refuses -- one
        whose name 'load' found disagreeing, or one that does not agree with
        the shared parameter it would be bound to -- which the caller records
        against the object.
        """
        if not isinstance(config, dict):
            return
        declared = config.get("parameters")
        if not isinstance(declared, dict):
            return
        for name, declaration in list(declared.items()):
            if not pc_parameters.is_shared(declaration):
                continue
            refused = self.refused.get(name)
            if refused is not None:
                raise ValueError(refused)
            holder = self.holder(name, declaration, object_name)
            if holder is None or holder is declaration:
                continue
            # Not the default: this object's copy may carry an override of its
            # own by now, and the package's declared defaults were compared
            # as it loaded.
            keys = pc_parameters.differences(holder, declaration, ignore=("default",))
            if keys:
                raise ValueError(
                    "The shared parameter '%s' of '%s' is declared by '%s' differently from the package's (%s): "
                    "the shared declarations of a name are one parameter, and may differ only in 'desc'"
                    % (name, self.project.name, object_name, ", ".join("'%s'" % k for k in keys))
                )
            declared[name] = holder

    def values_for(self, object_name: str) -> dict:
        """{name: value} of the shared parameters 'object_name' declares, as the package has them.

        From what the package's 'partcad.yaml' declares, so nothing is made to
        answer it: what a cache keyed on an object's parameters adds for the
        ones it shares (see 'ProjectExternalRepository._plugin_overrides').
        """
        with self._lock:
            names = [name for name, sharers in self._sharers.items() if object_name in sharers]
        result = {}
        for name in sorted(names):
            holder = self.holder(name)
            if holder is not None:
                result[name] = holder.get("default")
        return result


def check_instance_value(declaration, value, param_name: str, object_name: str, package_name: str = None) -> None:
    """Raise ``ValueError`` if 'value' is given to one instance for a shared parameter and differs from it.

    'declaration' is the declaration the instance has, whose default is the
    package's value: the holder, or a copy of it.
    """
    if not pc_parameters.is_shared(declaration):
        return
    wanted = pc_parameters.coerce_parameter_value(
        declaration.get("type"),
        value,
        param_name,
        object_name,
        item_type=pc_parameters.array_item_type(declaration),
    )
    if wanted == declaration.get("default"):
        return
    if package_name is None and ":" in object_name:
        package_name = pc_parameters.package_of(object_name)
    package = package_name or "<package>"
    raise ValueError(
        "The parameter '%s' of '%s' is shared by its package, so it is one value for every object of the package "
        "declaring it, and cannot be set for one of them: set it for the package instead, under "
        "'parameters: %s:' in your configuration or with '--extra-param %s.%s=...'"
        % (param_name, object_name, package, package, param_name)
    )
