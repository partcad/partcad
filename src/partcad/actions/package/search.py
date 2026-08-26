from partcad.context import Context
from partcad.project import Project
from partcad.actions.common import _search


def search_packages(ctx: Context, package: str, recursive: bool, keyword: str) -> list[Project]:
    return _search(
        ctx,
        package,
        recursive,
        keyword,
        lambda project: [project]
    )
