#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

from .config import Configuration
from .shape_config import ShapeConfiguration


class SceneConfiguration(Configuration, ShapeConfiguration):
    """How a package declares a scene, normalized.

    The same shape of declaration as an assembly's, with one default of its
    own: a scene is not manufacturable unless it says so. A scene states where
    things are -- a workcell, a table, a simulation world -- and nothing in it
    is a product to be made, so the manufacturability checks ('pc test') and
    the assembly instruction book have nothing to say about one. A scene that
    really is a deliverable declares 'manufacturable: true' and gets both back.

    Set here rather than left to 'ShapeFactory.__init__', which fills the key
    in from the package: the package-wide answer is about the products the
    package publishes, and a scene is not one of them.
    """

    def __init__(self, name, config=None):
        super().__init__(name, config)

    @staticmethod
    def normalize(name, config, object_name):
        if isinstance(config, str):
            # This is a short form alias
            config = {"type": "alias", "source": config}

        config.setdefault("manufacturable", False)

        config = Configuration.normalize(name, config, object_name)
        return ShapeConfiguration.normalize(name, config)
