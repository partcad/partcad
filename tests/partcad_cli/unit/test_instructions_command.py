#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""'pc instructions' asks for the file and nothing else, and writes it whichever way it came.

The book's model is what the IDE draws; this command keeps only the file, and
every illustration in the model would have crossed the wire a second time
beside the copy inside the file. And the file is the daemon's bytes -- an
attachment from a daemon that sends them, base64 from one older than that (see
'partcad_utils.framing').
"""

import base64

import pytest
from click.testing import CliRunner

from partcad_cli.click.command import cli
from partcad_cli.click.commands import instructions

HTML = "<!DOCTYPE html><title>Ø</title>".encode("utf-8")


@pytest.mark.parametrize("attached", [True, False], ids=["bytes", "base64"])
def test_the_file_is_written_and_the_model_is_not_asked_for(monkeypatch, tmp_path, attached):
    calls = []

    def run(cli_ctx, method, params, needs_context=False):
        calls.append((method, params))
        content = HTML if attached else base64.b64encode(HTML).decode("ascii")
        return {"assembly": "//:top", "file": {"filename": "top.html", "extension": "html", "content": content}}

    monkeypatch.setattr(instructions, "run", run)

    result = CliRunner().invoke(cli, ["--no-ansi", "instructions", "-t", "html", "-O", str(tmp_path), "top"])

    assert result.exit_code == 0, result.output
    ((method, params),) = calls
    assert method == "assembly.guide"
    assert (params["format"], params["document"]) == ("html", False)
    assert (tmp_path / "top.html").read_bytes() == HTML
