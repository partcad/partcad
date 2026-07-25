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
        # Do not instantiate anything eagerly. Objects are created on demand by
        # the getters when first requested, so that a package backed by a large
        # remote repository does not materialize its entire contents up front.
        pass

    def _enumerate_object_configs(self, kind):
        # A bare plugin package exposes nothing; concrete subclasses (e.g.
        # 'ProjectExternalRepository') override this to enumerate their data.
        return {}

    def _fetch_object_config(self, kind, name):
        return None
