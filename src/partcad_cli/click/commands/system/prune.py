#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

import partcad as pc
from partcad import docker_prune, runtime


@click.option(
    "--stale",
    is_flag=True,
    default=False,
    help="Remove only what is out of date: images built for another PartCAD release, and containers nothing is using.",
)
@click.command(help="Remove the containers and images PartCAD created")
@click.pass_obj
def cli(cli_ctx, stale: bool) -> None:
    """Clean up after the ``docker`` sandbox.

    Only what carries PartCAD's labels, and that is the whole point: a machine
    running PartCAD is a machine somebody also uses for other things, and a
    command that removed an image it did not put there is one nobody dares run
    twice. An unlabelled image -- a third-party one whose author did not adopt
    the convention -- is left alone and has to be removed by hand.
    """
    with pc.telemetry.set_context(cli_ctx.otel_context):
        with pc.logging.Process("Prune", "global"):
            if not runtime.docker_available():
                pc.logging.info("No container runtime here, so there is nothing of PartCAD's to remove.")
                return

            import docker

            client = docker.from_env()

            # Containers first. An image cannot be removed while a container
            # made from it exists, so the other order removes nothing and says
            # so once per image.
            containers = docker_prune.managed_containers(client, stale_only=stale)
            for container in containers:
                name = docker_prune.name_of(container)
                with pc.logging.Action("Container", name):
                    try:
                        container.remove(force=True)
                        pc.logging.info("Removed container: %s" % name)
                    except Exception as e:
                        pc.logging.warning("Could not remove container %s: %s" % (name, e))

            images = docker_prune.managed_images(client, stale_only=stale, version=pc.__version__)
            for image in images:
                name = docker_prune.name_of(image)
                with pc.logging.Action("Image", name):
                    try:
                        client.images.remove(image.id, force=False)
                        pc.logging.info("Removed image: %s" % name)
                    except Exception as e:
                        # Most often "still in use", which is a container this
                        # run did not choose -- a running one under `--stale`.
                        # Not a failure: the user asked for what is safe to
                        # remove, and this is the answer to that.
                        pc.logging.warning("Kept image %s: %s" % (name, e))

            if not containers and not images:
                pc.logging.info("Nothing to remove%s." % (" that is out of date" if stale else " that PartCAD created"))
