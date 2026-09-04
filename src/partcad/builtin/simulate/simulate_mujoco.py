#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The built-in MuJoCo simulation plugin (see '//builtin/simulate' partcad.yaml).

Runs a scene under gravity for a while and says where everything ended up.

The scene arrives as MJCF -- PartCAD exported it (see
'builtin/export/export_mjcf.py') with every body free to move and a ground
plane under it -- so all this does is load the model, step it, and take the
same reading twice: once before anything has moved and once when the time is
up. That pair is what a ``simulate:``'s ``validation:`` expression is handed,
and it is the whole of what PartCAD requires a simulation plugin to produce.

Positions are reported in **millimetres**, PartCAD's unit everywhere, not in the
metres MuJoCo works in. A validation expression is written by whoever wrote the
part, against the numbers that part is drawn in.

Nothing here is specific to what is being simulated. A body is a body, and the
reading is "where is it and which way is it facing" -- which is all a static
description of a scene ever had to say, and so all that can be compared against
it. A plugin that needs to say more (a force, a temperature, a contact history)
states it beside 'before' and 'after' in its own vocabulary; see
'wrappers/wrapper_simulate.py'.
"""

# Millimetres per metre: MJCF is metres by definition, PartCAD is millimetres
# throughout. Spelled out rather than imported from 'urdf_common' because this
# script runs in a sandbox that carries MuJoCo and nothing else, and one
# constant is not worth a dependency on the wrappers directory.
MM_PER_M = 1000.0


def snapshot(mujoco, model, data):
    """Where every body is right now, keyed by the name the MJCF gave it.

    The world body is left out: it is body 0 of every model, it is the frame
    everything else is stated in, and it never moves. What is left is exactly
    the bodies PartCAD's exporter wrote out of the scene, under the names it
    gave them - which is what makes a validation expression readable.
    """
    bodies = {}
    for index in range(1, model.nbody):
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, index)
        if not name:
            name = "body_%d" % index
        bodies[name] = {
            "pos": [float(v) * MM_PER_M for v in data.xpos[index]],
            "quat": [float(v) for v in data.xquat[index]],
        }
    return {"time": float(data.time), "bodies": bodies}


def process(path, request):  # pylint: disable=unused-argument
    import mujoco

    scene_file = request["scene_file"]
    duration = float(request.get("duration") or 10.0)
    samples = int(request.get("samples") or 0)

    model = mujoco.MjModel.from_xml_path(scene_file)

    timestep = request.get("timestep")
    if timestep:
        model.opt.timestep = float(timestep)
    gravity = request.get("gravity")
    if gravity:
        # The exported MJCF already carries it; honouring it here too means a
        # 'simulate:' can ask for a different gravity without re-exporting.
        model.opt.gravity[:] = [float(v) for v in gravity]

    data = mujoco.MjData(model)
    # Positions the bodies where the model says they are and computes
    # everything derived from that, without advancing time: this is the state
    # the scene described, which is what 'before' has to be.
    mujoco.mj_forward(model, data)
    before = snapshot(mujoco, model, data)

    trace = []
    next_sample = duration / (samples + 1) if samples > 0 else None
    steps = 0
    while data.time < duration:
        mujoco.mj_step(model, data)
        steps += 1
        if next_sample is not None and data.time >= next_sample:
            trace.append(snapshot(mujoco, model, data))
            next_sample += duration / (samples + 1)

    after = snapshot(mujoco, model, data)

    result = {
        "success": True,
        "before": before,
        "after": after,
        # Beside the two PartCAD requires: what this run actually was, so that a
        # report of a failed validation says what it was a validation of.
        "simulator": "mujoco",
        "version": getattr(mujoco, "__version__", None),
        "duration": duration,
        "timestep": float(model.opt.timestep),
        "steps": steps,
        "gravity": [float(v) for v in model.opt.gravity],
        "units": "mm",
    }
    if trace:
        result["samples"] = trace
    return result
