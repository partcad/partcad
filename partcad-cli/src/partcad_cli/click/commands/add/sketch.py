import rich_click as click  # import click
import partcad as pc
from pathlib import Path

from partcad.sketch_types import SketchTypes


@click.command(help="Add a sketch")
@click.option(
    "--desc",
    type=str,
    help="The part description (also used by LLMs).",
    required=False,
    show_envvar=True,
)
@click.option(
    "--ai",
    "provider",
    type=click.Choice(["google", "openai"]),
    help="Generative AI provider.",
    required=False,
    show_envvar=True,
)
@click.argument("kind_or_path", required=True)
@click.argument("maybe_path", required=False)
@click.pass_obj
def cli(ctx, desc, provider, kind_or_path, maybe_path):
    prj = ctx.get_project(pc.ROOT)
    with pc.logging.Process("AddSketch", prj.name):
        config = {}
        if desc:
            config["desc"] = desc

        all_kinds = SketchTypes.types()

        # Detect whether user passed only `path`
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
            matches = SketchTypes.get_formats_by_ext(ext)

            if len(matches) == 1:
                kind = matches[0].type
            elif len(matches) > 1:
                raise click.BadParameter(
                    f"Ambiguous extension '.{ext}' matches multiple kinds: "
                    f"{', '.join(f.type for f in matches)}. Please specify the kind explicitly."
                )
            else:
                raise click.BadParameter(
                    f"Could not infer sketch kind from extension '.{ext}'. "
                    "Please provide the 'kind' argument explicitly."
                )

        if provider:
            config["provider"] = provider
            fmt = SketchTypes.get_format(kind)
            if fmt and not path.lower().endswith(f".{fmt.ext}"):
                path = path.rsplit(".", 1)[0] + f".gen.{fmt.ext}"

        if prj.add_sketch(kind, path, config):
            Path(path).touch()
