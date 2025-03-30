import rich_click as click  # import click
from pathlib import Path
import partcad as pc
from partcad.assembly_types import AssemblyTypes


@click.command(help="Add an assembly")
@click.argument("kind_or_path", required=True)
@click.argument("maybe_path", required=False)
@click.pass_obj
def cli(ctx, kind_or_path, maybe_path):
    prj = ctx.get_project(pc.ROOT)
    all_kinds = AssemblyTypes.types()

    if kind_or_path not in all_kinds and maybe_path is None:
        path = kind_or_path
        kind = None
    else:
        kind = kind_or_path
        path = maybe_path

    if not path:
        raise click.UsageError("Missing required argument 'path'.")

    if kind and kind not in all_kinds:
        raise click.BadParameter(
            f"Invalid kind '{kind}'. Must be one of: {', '.join(all_kinds)}"
        )

    if not kind:
        ext = Path(path).suffix.lstrip(".")
        matches = AssemblyTypes.yaml_based.get_formats_by_ext(ext)

        if len(matches) == 1:
            kind = matches[0].type
        elif len(matches) > 1:
            raise click.BadParameter(
                f"Ambiguous extension '.{ext}' matches multiple kinds: "
                f"{', '.join(f.type for f in matches)}. Please specify the kind explicitly."
            )
        else:
            raise click.BadParameter(
                f"Could not infer assembly kind from extension '.{ext}'. "
                "Please provide the 'kind' argument explicitly."
            )

    if prj.add_assembly(kind, path):
        Path(path).touch()
