#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A stand-in for the IDE's viewer socket, for looking at what a show carries.

Listens where the Digital Thread listens, acknowledges every frame, and prints
the tree of each object shown - its nodes, their geometry, their placements and
what each declares about connections (see 'partcad.shape_envelope'). Run it, then
run 'pc ide view ...' in another shell.

It answers as a current IDE does - binary frames, and offers answered from the
geometry it was sent before (see 'partcad_ide_client.protocol') - so a second
show of the same object prints how little of it had to be sent. '--legacy'
answers as an IDE from before either, which is sent JSON frames.

Not a test and not part of the build: an eyeball on the wire.
"""

import argparse
import socket
import sys
import threading

from partcad_ide_client import protocol


def summarize(message, held):
    """Print the object's tree: its nodes, their geometry, their connections."""
    print(
        "show %r kind=%r package=%r keepCamera=%r"
        % (message.get("name"), message.get("kind"), message.get("package"), message.get("keepCamera"))
    )
    table = (message.get(protocol.KEY_OBJECT) or {}).get(protocol.KEY_GEOMETRY) or {}
    if table:
        sent = {digest: payload for digest, payload in table.items() if payload is not None}
        print(
            "  geometry: %d shape(s), %.1fKB of glTF; %d sent with the show, the rest sent ahead or held"
            % (
                len(table),
                sum(len(held.get(digest) or payload or b"") for digest, payload in table.items()) / 1024.0,
                len(sent),
            )
        )

    def walk(node, depth):
        indent = "  " + "  " * depth
        what = []
        gltf = node.get(protocol.KEY_GLTF)
        if gltf:
            what.append("%.1fKB of glTF" % (len(gltf) / 1024.0))
        location = node.get(protocol.KEY_LOCATION)
        if location:
            what.append("at %s" % (location[0],))
        print(
            "%s%s (%s)%s"
            % (
                indent,
                node.get("label") or node.get("name") or "?",
                node.get("name"),
                (" -- " + ", ".join(what)) if what else "",
            )
        )
        for port in node.get(protocol.KEY_PORTS) or []:
            print(
                "%s  port %s%s at %s%s"
                % (
                    indent,
                    port.get("name"),
                    (" of %s(%s)" % (port.get("interface"), port.get("instance"))) if port.get("interface") else "",
                    port[protocol.KEY_LOCATION][0],
                    (" drawn with %s" % port["sketch"]) if port.get("sketch") else "",
                )
            )
        for interface in node.get(protocol.KEY_INTERFACES) or []:
            print(
                "%s  interface %s(%s): %s"
                % (indent, interface.get("name"), interface.get("instance"), ", ".join(interface.get("ports") or []))
            )
        for reference, sketch in (node.get(protocol.KEY_SKETCHES) or {}).items():
            drawn = sketch.get(protocol.KEY_GLTF)
            print(
                "%s  sketch %s: %s"
                % (indent, reference, ("%.1fKB of glTF" % (len(drawn) / 1024.0)) if drawn else "nothing")
            )
        for child in node.get(protocol.KEY_ASSEMBLY) or []:
            walk(child, depth + 1)

    obj = message.get(protocol.KEY_OBJECT)
    if obj is None:
        print("  (no object)")
    else:
        walk(obj, 0)
    sys.stdout.flush()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=protocol.PARTCAD_IDE_PORT)
    parser.add_argument("--legacy", action="store_true", help="answer as an IDE from before binary frames")
    args = parser.parse_args()
    capabilities = None if args.legacy else [protocol.CAP_BINARY, protocol.CAP_OFFER]
    # What every connection was sent, as a window's store is: by digest.
    held = {}

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((protocol.PARTCAD_IDE_HOST, args.port))
    server.listen(4)
    print("listening on %s:%d" % (protocol.PARTCAD_IDE_HOST, args.port))
    sys.stdout.flush()

    while True:
        connection, _ = server.accept()
        # A thread each, because the client keeps its connection open for the life
        # of the process and one of those processes is the PartCAD daemon: serving
        # one connection at a time means the second workspace's daemon connects,
        # is never read from, and reports a timed-out show.
        threading.Thread(target=serve, args=(connection, capabilities, held), daemon=True).start()


def answer(message, held):
    """What a current IDE says to 'message' beyond the acknowledgement itself."""
    kind = message.get("type")
    if kind == protocol.MSG_OFFER:
        return {protocol.KEY_MISSING: [digest for digest in message[protocol.KEY_DIGESTS] if digest not in held]}
    if kind == protocol.MSG_GEOMETRY:
        held.update(message[protocol.KEY_GEOMETRY])
    if kind == protocol.MSG_SHOW:
        table = (message.get(protocol.KEY_OBJECT) or {}).get(protocol.KEY_GEOMETRY) or {}
        missing = [digest for digest, payload in table.items() if payload is None and digest not in held]
        if missing:
            return {"ok": False, protocol.KEY_MISSING: missing}
        held.update({digest: payload for digest, payload in table.items() if payload is not None})
    return {}


def serve(connection, capabilities, held):
    with connection:
        buffer = b""
        while True:
            chunk = connection.recv(1 << 20)
            if not chunk:
                return
            buffer += chunk
            while len(buffer) >= protocol.HEADER_LENGTH:
                kind, length = protocol.read_header(buffer[: protocol.HEADER_LENGTH])
                if len(buffer) < protocol.HEADER_LENGTH + length:
                    break
                message = protocol.decode_payload(
                    buffer[protocol.HEADER_LENGTH : protocol.HEADER_LENGTH + length], kind
                )
                buffer = buffer[protocol.HEADER_LENGTH + length :]
                if message.get("type") == protocol.MSG_SHOW:
                    summarize(message, held)
                else:
                    sent = message.get(protocol.KEY_GEOMETRY) or {}
                    print(
                        "%s (%s frame)%s"
                        % (
                            message.get("type"),
                            "binary" if kind == protocol.KIND_BINARY else "JSON",
                            (
                                ": %d shape(s), %.1fKB"
                                % (len(sent), sum(len(payload) for payload in sent.values()) / 1024.0)
                                if sent
                                else ""
                            ),
                        )
                    )
                    sys.stdout.flush()
                ack = {"type": protocol.MSG_ACK, "id": message.get("id"), "ok": True}
                if capabilities is not None:
                    ack[protocol.KEY_CAPABILITIES] = capabilities
                    ack.update(answer(message, held))
                connection.sendall(protocol.encode_frame(ack))


if __name__ == "__main__":
    main()
