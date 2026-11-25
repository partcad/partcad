#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Finding FieldCraft, talking to it, and reading what it wrote.

Everything the four analysis scripts share that is about FieldCraft rather than
about the physics: where `fieldcraft-cli` is (or fetching the release this
package pins), how the part's gmsh mesh becomes a FieldCraft model, how a list
of engine commands is run, and how the answer comes back -- the replies of the
commands, and the fields of the solved step as a VTK XML file.

**Why FieldCraft is driven over MCP.** `fieldcraft-cli run <script.json>` runs a
list of engine commands and prints only the model summary; the replies of the
commands -- what the solve found, the ports of a flow, the frequencies -- are
not printed. `fieldcraft-cli mcp` serves the same engine over the Model Context
Protocol on stdin/stdout, and its `batch` tool runs a list of commands and
answers with every reply. It is FieldCraft's documented machine interface
(`docs/mcp.md` in its repository), so a session here is a few JSON-RPC lines:
`initialize`, `notifications/initialized`, then `tools/call` of `batch`, as
many times as the analysis needs. File access is confined to the case
directory (`--automation-read-root`, `--automation-write-root`).

**Where it is.** `fieldcraft-cli` is looked for in what `PARTCAD_FIELDCRAFT_BIN`
names (the executable or the directory holding it), then on `PATH`, then where
the release packages put it. Failing that, and unless `download` is off, the
release `FIELDCRAFT_VERSION` is fetched from GitHub once, its SHA-256 checked
against the one pinned here, and unpacked under `~/.partcad/tools/` (or
`PARTCAD_FIELDCRAFT_CACHE`): FieldCraft is one self-contained executable per
platform, so unlike every other solver PartCAD drives it needs neither a
container nor an installation.

**The mesh.** FieldCraft reads ASCII MSH 4.1 (`mesh.import.orphan`), with each
physical group becoming a set of the same name: a surface group a set of
element faces, the volume group a set of elements. `cae_support.mesh()` meshes
the part with the faces each port covers named; `write_msh()` writes what it
made as MSH 4.1 (the helper writes 2.2, which FieldCraft refuses).

**Units.** Every model is `m-kg-s-N-Pa` with temperatures in Celsius: the mesh is
in metres, as `cae_support.mesh()` scales it, and the material constants are SI,
as PartCAD hands them over.
"""

import hashlib
import json
import os
import platform
import queue
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import urllib.request
import xml.etree.ElementTree as ElementTree
import zipfile

# The meta-wrapper's directory is on 'sys.path' when PartCAD runs a script, and
# 'cae_support' lives there: what every implementation does around its solver.
import cae_support as support  # noqa: E402

ERROR = "error"
WARNING = "warning"
INFO = "info"

M2_PER_MM2 = 1e-6
MM_PER_M = 1000.0

BIN_ENV = "PARTCAD_FIELDCRAFT_BIN"
CACHE_ENV = "PARTCAD_FIELDCRAFT_CACHE"

# The release this package was written against and is tested with. A newer
# FieldCraft found on this machine is used as it is; one fetched is always this.
FIELDCRAFT_VERSION = "0.8.1"
RELEASES = "https://github.com/tangency-labs/fieldcraft/releases/download/v%s/" % FIELDCRAFT_VERSION

# What to fetch on each platform FieldCraft publishes a command line for, and
# the SHA-256 its release's `SHA256SUMS.txt` states for it. The Linux archive
# carries the desktop app as well; only `bin/fieldcraft-cli` is unpacked.
DOWNLOADS = {
    ("Linux", "x86_64"): (
        "fieldcraft-%s-linux-x86_64.tar.gz" % FIELDCRAFT_VERSION,
        "987be64ed96f168d6e7224a8b3ddcac02aa3c17f448f6490c88b3868378e1708",
    ),
    ("Darwin", "arm64"): (
        "fieldcraft-cli-%s-macos-aarch64.zip" % FIELDCRAFT_VERSION,
        "cfd560b544137e9ad706c7581bedf29c1514ac08282ee5baec7f4d157b223a40",
    ),
    ("Windows", "AMD64"): (
        "fieldcraft-%s-windows-x64.zip" % FIELDCRAFT_VERSION,
        "c30910c67ba0d91477829c187583a9d7add5ede04391505ee531fb6ea3eac323",
    ),
}

# Where the release packages put the command line, besides PATH.
DIRECTORIES = (
    "/opt/fieldcraft/bin",
    "/usr/local/bin",
    "/usr/bin",
    "/Applications/FieldCraft.app/Contents/MacOS",
    "C:\\Program Files\\FieldCraft",
)

EXECUTABLE = "fieldcraft-cli.exe" if os.name == "nt" else "fieldcraft-cli"

# What a model is typed in: SI, with temperatures in Celsius as PartCAD states them.
UNITS = {"command": "model.units", "params": {"system": "m-kg-s-N-Pa", "temperature": "°C"}}

# The names the mesh's groups are imported under: the solid, and every surface
# no condition claimed (the walls of a duct).
BODY = "body"
REST = "rest"

# What a session writes beside the case: the commands it sent, as a script.
SCRIPT = "case.json"

_found = None


# --------------------------------------------------------------------------- #
# Finding it                                                                  #
# --------------------------------------------------------------------------- #


def _flag(value, default=True):
    """A yes or a no, however a configuration wrote it."""
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def _executable(path):
    return path if path and os.path.isfile(path) and os.access(path, os.X_OK) else None


def cache_dir():
    """Where a fetched release is kept: one directory per version."""
    root = os.environ.get(CACHE_ENV) or os.path.join(os.path.expanduser("~"), ".partcad", "tools")
    return os.path.join(root, "fieldcraft-%s" % FIELDCRAFT_VERSION)


def find_fieldcraft(request=None):
    """The path of `fieldcraft-cli`, fetching the pinned release when nothing else has one."""
    global _found
    if _found is not None:
        return _found

    searched = []
    named = os.environ.get(BIN_ENV)
    if named:
        candidate = os.path.join(named, EXECUTABLE) if os.path.isdir(named) else named
        if not _executable(candidate):
            raise support.ToolMissing("%s names no fieldcraft-cli executable: %s" % (BIN_ENV, named))
        _found = candidate
        return _found

    on_path = shutil.which("fieldcraft-cli")
    if on_path:
        _found = on_path
        return _found
    searched.append("PATH")

    for directory in DIRECTORIES:
        candidate = _executable(os.path.join(directory, EXECUTABLE))
        if candidate:
            _found = candidate
            return _found
        searched.append(directory)

    cached = _executable(os.path.join(cache_dir(), EXECUTABLE))
    if cached:
        _found = cached
        return _found
    searched.append(cache_dir())

    if _flag((request or {}).get("download"), default=True):
        _found = download()
        return _found

    raise support.ToolMissing(_missing_message(searched))


def _missing_message(searched):
    return (
        "FieldCraft is not available on this %s-%s machine, and 'download' is off. Two ways to have it: "
        "download the command line from https://github.com/tangency-labs/fieldcraft/releases (FieldCraft %s or "
        "later) and put fieldcraft-cli on PATH or point %s at it -- or let this package fetch release %s by "
        "leaving 'download' on. Searched: %s"
        % (platform.system(), platform.machine(), FIELDCRAFT_VERSION, BIN_ENV, FIELDCRAFT_VERSION, ", ".join(searched))
    )


def download(urlopen=None):
    """Fetch the pinned release for this platform, check it, and unpack fieldcraft-cli; return its path."""
    key = (platform.system(), platform.machine())
    if key not in DOWNLOADS:
        raise support.ToolMissing(
            "FieldCraft %s publishes no command line for %s-%s (it does for %s). Build it from "
            "https://github.com/tangency-labs/fieldcraft and point %s at it."
            % (FIELDCRAFT_VERSION, key[0], key[1], ", ".join("%s-%s" % k for k in DOWNLOADS), BIN_ENV)
        )
    name, digest = DOWNLOADS[key]
    target = cache_dir()
    os.makedirs(target, exist_ok=True)
    opener = urlopen or urllib.request.urlopen
    with tempfile.TemporaryDirectory(dir=target) as work:
        archive = os.path.join(work, name)
        try:
            with opener(RELEASES + name, timeout=600) as response, open(archive, "wb") as f:
                shutil.copyfileobj(response, f, 1 << 20)
        except Exception as e:
            raise support.ToolMissing(
                "FieldCraft %s could not be fetched from %s: %s. Install it by hand and point %s at it."
                % (FIELDCRAFT_VERSION, RELEASES + name, e, BIN_ENV)
            )
        found = sha256_of(archive)
        if found != digest:
            raise support.ToolFailed(
                "%s does not have the SHA-256 this package pins (%s, found %s): refusing to run it"
                % (name, digest, found)
            )
        unpacked = os.path.join(work, EXECUTABLE)
        _extract(archive, EXECUTABLE, unpacked)
        os.chmod(unpacked, 0o755)
        final = os.path.join(target, EXECUTABLE)
        # Atomic: two analyses fetching at once each move a whole file into place.
        os.replace(unpacked, final)
    return final


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _extract(archive, member_name, destination):
    """Copy the one member called 'member_name' (at any depth) out of a .tar.gz or a .zip."""
    if archive.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            for member in z.namelist():
                if member.rstrip("/").split("/")[-1] == member_name:
                    with z.open(member) as source, open(destination, "wb") as f:
                        shutil.copyfileobj(source, f, 1 << 20)
                    return
    else:
        with tarfile.open(archive, "r:gz") as t:
            for member in t.getmembers():
                if member.isfile() and member.name.split("/")[-1] == member_name:
                    source = t.extractfile(member)
                    with source, open(destination, "wb") as f:
                        shutil.copyfileobj(source, f, 1 << 20)
                    return
    raise support.ToolFailed("%s holds no %s" % (os.path.basename(archive), member_name))


# --------------------------------------------------------------------------- #
# Talking to it                                                               #
# --------------------------------------------------------------------------- #


class Session:
    """One `fieldcraft-cli mcp --headless` process, confined to a case directory.

    Used as a context manager. 'batch()' runs a list of `{command, params}` and
    returns the reply of each; a command that fails ends the batch and raises
    'support.ToolFailed' naming it and FieldCraft's reason.
    """

    PROTOCOL = "2025-06-18"

    def __init__(self, work, request=None, executable=None, timeout=None):
        self.work = os.path.abspath(work)
        self.timeout = float(timeout or (request or {}).get("solve_timeout") or 3600)
        self.executable = executable or find_fieldcraft(request)
        self.log = os.path.join(self.work, "log.fieldcraft")
        self._id = 0
        self._process = None
        self._lines = queue.Queue()
        # Every command sent, as the script `fieldcraft-cli run` reads, kept in
        # the case directory: what to replay, or to draw with `fieldcraft-cli
        # snapshot`, when a case kept with PARTCAD_FIELDCRAFT_CASE is debugged.
        self.script = []

    def __enter__(self):
        env = dict(os.environ)
        # One answer on every machine: the fluid solver's CPU backend is double
        # precision and deterministic, the GPU one single precision.
        env.setdefault("FIELDCRAFT_SOLVE_BACKEND", "cpu")
        self._stderr = open(self.log, "w")
        self._process = subprocess.Popen(
            [
                self.executable,
                "mcp",
                "--headless",
                "--automation-read-root",
                self.work,
                "--automation-write-root",
                self.work,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._stderr,
            cwd=self.work,
            env=env,
        )
        self._reader = threading.Thread(target=self._read, args=(self._process.stdout,), daemon=True)
        self._reader.start()
        try:
            self.request("initialize", {"protocolVersion": self.PROTOCOL, "capabilities": {}, "clientInfo": _client()})
            self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        except BaseException:
            # A context manager whose __enter__ raises is never exited.
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *_exc):
        process, self._process = self._process, None
        if process is None:
            return
        try:
            try:
                process.stdin.close()
            except OSError:
                pass
            process.wait(timeout=30)
        except Exception:
            process.kill()
            process.wait()
        finally:
            self._reader.join(timeout=5)
            process.stdout.close()
            self._stderr.close()

    def _read(self, stream):
        for line in stream:
            self._lines.put(line)
        self._lines.put(None)

    def _send(self, message):
        data = (json.dumps(message) + "\n").encode("utf-8")
        try:
            self._process.stdin.write(data)
            self._process.stdin.flush()
        except (BrokenPipeError, OSError):
            raise support.ToolFailed("fieldcraft-cli stopped before it was asked anything:\n%s" % self._tail())

    def request(self, method, params):
        """Send one JSON-RPC request and return its result, or raise with what went wrong."""
        self._id += 1
        number = self._id
        self._send({"jsonrpc": "2.0", "id": number, "method": method, "params": params})
        while True:
            try:
                line = self._lines.get(timeout=self.timeout)
            except queue.Empty:
                self._process.kill()
                raise support.ToolFailed(
                    "fieldcraft-cli said nothing for %d s ('solve_timeout'), so it was stopped:\n%s"
                    % (self.timeout, self._tail())
                )
            if line is None:
                raise support.ToolFailed(
                    "fieldcraft-cli stopped (exit %s) before answering:\n%s" % (self._process.wait(), self._tail())
                )
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if message.get("id") != number:
                continue
            if "error" in message:
                raise support.ToolFailed("fieldcraft-cli refused '%s': %s" % (method, message["error"].get("message")))
            return message.get("result")

    def batch(self, commands):
        """Run engine commands in order; return each one's reply."""
        self.script.extend(commands)
        with open(os.path.join(self.work, SCRIPT), "w") as f:
            json.dump(self.script, f, indent=1, ensure_ascii=False)
        result = self.request("tools/call", {"name": "batch", "arguments": {"commands": commands}})
        return parse_batch(result, commands)

    def _tail(self, lines=15):
        try:
            self._stderr.flush()
            with open(self.log, errors="replace") as f:
                text = f.read().strip()
        except OSError:
            return ""
        return "\n".join(text.splitlines()[-lines:])


def _client():
    try:
        import partcad

        version = partcad.__version__
    except Exception:
        version = "unknown"
    return {"name": "partcad-cae-fieldcraft", "version": version}


def parse_batch(result, commands):
    """The replies of a `batch` tool call, or 'ToolFailed' naming the command that failed and why."""
    content = (result or {}).get("content") or []
    text = "".join(block.get("text", "") for block in content if block.get("type") == "text")
    try:
        answer = json.loads(text)
    except ValueError:
        answer = None
    if not isinstance(answer, dict):
        raise support.ToolFailed("FieldCraft answered the batch with: %s" % (text.strip() or "nothing"))
    if result.get("isError") or not answer.get("ok", False):
        failed = answer.get("failed") or {}
        index = failed.get("index")
        command = failed.get("command") or (commands[index]["command"] if isinstance(index, int) else "?")
        raise support.ToolFailed("FieldCraft refused '%s': %s" % (command, failed.get("error") or text.strip()))
    return answer.get("results") or []


def run(work, commands, request=None, session=None):
    """Run one batch in a session of its own (or the one given); return the replies."""
    if session is not None:
        return session.batch(commands)
    with Session(work, request) as opened:
        return opened.batch(commands)


# --------------------------------------------------------------------------- #
# The mesh                                                                    #
# --------------------------------------------------------------------------- #


def mesh_part(request, groups, work, order=2, rest=None):
    """Mesh the part with gmsh and write it as FieldCraft reads it; return the mesh and the file's path."""
    mesh = support.mesh(request, groups, size=float(request.get("mesh_size", 0.05)), order=order, rest=rest)
    path = os.path.join(work, "part.msh")
    write_msh(path, mesh)
    return mesh, path


# gmsh's element types this writes back, by how many nodes a volume element has.
_SURFACE_TRIANGLE = 2


def write_msh(path, mesh):
    """Write a 'cae_support.Mesh' as ASCII MSH 4.1: the solid, and a surface group per boundary group.

    Every node is classified on the one volume entity; each boundary group is a
    surface entity of its own carrying first-order triangles. FieldCraft matches
    a boundary triangle to the volume element face with the same corners, so a
    quadratic mesh's boundary is named by its corners alone -- and a face in two
    groups is two triangles, one in each entity, which is how a face both held
    and loaded is said.
    """
    tags = [int(tag) for tag in mesh.node_tags]
    coordinates = mesh.coordinates
    groups = [(name, triangles) for name, triangles in mesh.groups.items() if len(triangles)]
    volume_elements = sum(len(element_tags) for _type, element_tags, _nodes in mesh.volumes)
    if not tags or not volume_elements:
        raise support.ToolFailed("gmsh made no volume elements of the part")

    low = [min(float(p[axis]) for p in coordinates) for axis in range(3)]
    high = [max(float(p[axis]) for p in coordinates) for axis in range(3)]
    box = " ".join(repr(v) for v in low + high)

    lines = ["$MeshFormat", "4.1 0 8", "$EndMeshFormat"]
    lines.append("$PhysicalNames")
    lines.append(str(len(groups) + 1))
    for number, (name, _triangles) in enumerate(groups, start=1):
        lines.append('2 %d "%s"' % (number, name))
    lines.append('3 %d "%s"' % (len(groups) + 1, BODY))
    lines.append("$EndPhysicalNames")

    lines.append("$Entities")
    lines.append("0 0 %d 1" % len(groups))
    for number in range(1, len(groups) + 1):
        lines.append("%d %s 1 %d 0" % (number, box, number))
    lines.append("1 %s 1 %d 0" % (box, len(groups) + 1))
    lines.append("$EndEntities")

    lines.append("$Nodes")
    lines.append("1 %d %d %d" % (len(tags), min(tags), max(tags)))
    lines.append("3 1 0 %d" % len(tags))
    lines.extend(str(tag) for tag in tags)
    lines.extend("%r %r %r" % (float(p[0]), float(p[1]), float(p[2])) for p in coordinates)
    lines.append("$EndNodes")

    blocks = []
    next_tag = 1
    for number, (_name, triangles) in enumerate(groups, start=1):
        rows = []
        for triangle in triangles:
            rows.append("%d %s" % (next_tag, " ".join(str(int(node)) for node in triangle[:3])))
            next_tag += 1
        blocks.append(("2 %d %d %d" % (number, _SURFACE_TRIANGLE, len(rows)), rows))
    for element_type, _element_tags, element_nodes in mesh.volumes:
        rows = []
        for nodes in element_nodes:
            rows.append("%d %s" % (next_tag, " ".join(str(int(node)) for node in nodes)))
            next_tag += 1
        blocks.append(("3 1 %d %d" % (int(element_type), len(rows)), rows))
    total = next_tag - 1
    lines.append("$Elements")
    lines.append("%d %d 1 %d" % (len(blocks), total, total))
    for header, rows in blocks:
        lines.append(header)
        lines.extend(rows)
    lines.append("$EndElements")

    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return path


def import_mesh(path, extra=()):
    """The commands that start a model from the mesh at 'path': its units, the mesh, its sets."""
    return [UNITS, {"command": "mesh.import.orphan", "params": {"path": path}}, *extra]


def solid_section(material):
    """The whole solid as one section of 'material'."""
    return {
        "command": "model.section.create",
        "params": {"name": "part", "set": BODY, "material": material, "kind": {"type": "solid"}},
    }


# --------------------------------------------------------------------------- #
# What it wrote                                                               #
# --------------------------------------------------------------------------- #

# VTK cell types FieldCraft writes for solid elements, and how many corners
# lead each one's node list (a second-order cell lists its corners first).
VTK_CORNERS = {10: 4, 24: 4, 12: 8, 25: 8, 13: 6}


def read_vtu(path):
    """Points, cells by corner count, point fields and field data of a VTK XML unstructured grid.

    Returns '(points, cells, fields, field_data)': points as (x, y, z) tuples in
    the file's order; cells as '{corners: [node index lists]}' for the solid
    cells only; every point array as a list of tuples by name; and every
    field-data array (a mode's frequency, say) as a list of floats by name.
    ASCII and inline base64 are both read.
    """
    root = ElementTree.parse(path).getroot()
    piece = root.find(".//Piece")
    if piece is None:
        raise support.ToolFailed("%s holds no unstructured grid" % os.path.basename(path))
    header_type = root.get("header_type", "UInt32")

    def values(array):
        return _array_values(array, header_type)

    points_array = piece.find("./Points/DataArray")
    flat = values(points_array)
    points = [tuple(flat[k : k + 3]) for k in range(0, len(flat), 3)]

    cells_node = piece.find("./Cells")
    by_name = {array.get("Name"): array for array in cells_node.findall("./DataArray")}
    connectivity = [int(v) for v in values(by_name["connectivity"])]
    offsets = [int(v) for v in values(by_name["offsets"])]
    types = [int(v) for v in values(by_name["types"])]
    cells = {}
    start = 0
    for end, cell_type in zip(offsets, types):
        if cell_type in VTK_CORNERS:
            cells.setdefault(VTK_CORNERS[cell_type], []).append(connectivity[start:end])
        start = end

    fields = {}
    for array in piece.findall("./PointData/DataArray"):
        width = int(array.get("NumberOfComponents", "1"))
        flat = values(array)
        fields[array.get("Name")] = [tuple(flat[k : k + width]) for k in range(0, len(flat), width)]

    field_data = {}
    for array in root.findall(".//FieldData/DataArray"):
        field_data[array.get("Name")] = values(array)
    return points, cells, fields, field_data


def _array_values(array, header_type):
    import base64
    import struct

    form = (array.get("format") or "ascii").lower()
    text = (array.text or "").strip()
    if form == "ascii":
        return [float(token) for token in text.split()]
    if form != "binary":
        raise support.ToolFailed("a %s VTU array cannot be read here: ask for 'encoding: ascii'" % form)
    codes = {"Float64": "d", "Float32": "f", "Int64": "q", "Int32": "i", "UInt8": "B", "UInt32": "I", "UInt64": "Q"}
    code = codes.get(array.get("type"))
    if code is None:
        raise support.ToolFailed("VTU arrays of type %s are not read here" % array.get("type"))
    raw = base64.b64decode(text)
    header = struct.calcsize("<" + ("Q" if header_type == "UInt64" else "I"))
    size = struct.calcsize("<" + code)
    body = raw[header:]
    return list(struct.unpack("<%d%s" % (len(body) // size, code), body[: len(body) - len(body) % size]))


def surface(points, cells):
    """The outer triangles of the solid cells read by 'read_vtu'."""
    triangles = []
    for corners, cell_list in cells.items():
        triangles.extend(support.outer_triangles(cell_list, corners))
    return triangles


def magnitude(vectors):
    return [sum(float(c) * float(c) for c in vector) ** 0.5 for vector in vectors]


def scalar(field):
    return [float(value[0]) for value in field]


def with_result(fields):
    """Which points the step has values for: FieldCraft writes 0 for the others and says so."""
    marks = fields.get("has_result")
    if not marks:
        return None
    return [bool(mark[0]) for mark in marks]


# --------------------------------------------------------------------------- #
# What it means                                                               #
# --------------------------------------------------------------------------- #


def nothing_covered(record):
    """The finding for a condition whose port covers no surface of the part."""
    return {
        "severity": WARNING,
        "message": (
            "The port covers no surface of the part, so the condition on it did nothing. Place the port on "
            "the face it means, or draw its interface with a sketch that lies on one."
        ),
        "where": record.get("port") or record.get("interface_label") or "a port",
    }


def flag(value, default=False):
    """A yes or a no, however a configuration wrote it."""
    return _flag(value, default)


def case_dir(work):
    """A directory to keep the case in, for whoever is debugging one by hand."""
    kept = os.environ.get("PARTCAD_FIELDCRAFT_CASE")
    if kept:
        os.makedirs(kept, exist_ok=True)
        return kept
    return work


if __name__ == "__main__":  # pragma: no cover - a convenience for fetching by hand
    print(find_fieldcraft({"download": "--download" in sys.argv}))
