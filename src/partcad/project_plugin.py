#
# PartCAD, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-03-24
#
# Licensed under Apache License, Version 2.0.
#

from .project import Project


class ProjectPlugin(Project):
    """A package whose contents are not stored on disk as a 'partcad.yaml'.

    Unlike a local package, a plugin-backed package does not know its objects at
    construction time: enumerating them may be expensive (e.g. a remote
    repository). It therefore defers everything - it does not populate the
    object configs and does not instantiate any objects up front. The generic
    accessors on 'Project' (object_config / object_configs / object_names) drive
    the lazy fetch through the '_enumerate_object_configs' / '_fetch_object_config'
    hooks, which concrete subclasses override to talk to their data source.
    """

    def __init__(self, ctx, name, path, config_obj=None, inherited_config=None):
        super().__init__(ctx, name, path, config_obj=config_obj, inherited_config=inherited_config)
        self.is_local = False

    def _initial_object_configs(self, kind):
        # Nothing is known at construction time; enumerate on demand.
        return None

    def _instantiate_objects(self):
        # Not even the kinds a local package creates as it loads (see
        # 'Project.LAZY_OBJECT_KINDS' for the ones nobody creates eagerly).
        # Those are materials, interfaces, mates and the plugins, and each of
        # them would first have to be enumerated from the repository - which is
        # a query per kind, made while loading the package, to be told 'none' by
        # every package that holds no such thing. They are created on demand by
        # the getters instead, like everything else here.
        pass

    def _enumerate_object_configs(self, kind):
        # A bare plugin package exposes nothing; concrete subclasses (e.g.
        # 'ProjectExternalRepository') override this to enumerate their data.
        return {}

    def _fetch_object_config(self, kind, name):
        return None
