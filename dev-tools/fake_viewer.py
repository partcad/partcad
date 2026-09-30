#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A stand-in for the IDE's viewer socket, for looking at what a show carries.

Listens where the PartCAD Viewer listens, acknowledges every frame, and prints
the tree of each object shown - its nodes, their geometry, their placements and
what each declares about connections (see 'partcad.shape_envelope'). Run it, then
run 'pc inspect ...' in another shell.

Not a test and not part of the build: an eyeball on the wire.
"""

import argparse
import socket
import sys
import threading

from partcad_ide_client import protocol


def summarize(message):
    """Print the object's tree: its nodes, their geometry, their connections."""
    print(
        "show %r kind=%r package=%r keepCamera=%r"
        % (message.get("name"), message.get("kind"), message.get("package"), message.get("keepCamera"))
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
    args = parser.parse_args()

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
        threading.Thread(target=serve, args=(connection,), daemon=True).start()


def serve(connection):
    with connection:
        buffer = b""
        while True:
            chunk = connection.recv(1 << 20)
            if not chunk:
                return
            buffer += chunk
            while len(buffer) >= protocol.HEADER_LENGTH:
                length = protocol.decode_header(buffer[: protocol.HEADER_LENGTH])
                if len(buffer) < protocol.HEADER_LENGTH + length:
                    break
                message = protocol.decode_payload(buffer[protocol.HEADER_LENGTH : protocol.HEADER_LENGTH + length])
                buffer = buffer[protocol.HEADER_LENGTH + length :]
                if message.get("type") == protocol.MSG_SHOW:
                    summarize(message)
                else:
                    print("%s" % message.get("type"))
                    sys.stdout.flush()
                connection.sendall(protocol.encode_frame({"type": protocol.MSG_ACK, "id": message.get("id")}))


if __name__ == "__main__":
    main()
