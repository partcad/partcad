# Profiling memory

Four scripts for finding out where a run's memory goes. They are what the measurements in
`docs/design/memory-and-scheduling.md` were taken with, and a pull request that claims to change those numbers should
quote them before and after.

| script | runs with | does |
| --- | --- | --- |
| `memory_sampler.py OUT.jsonl` | any Python | samples the RSS and PSS of the daemon, the client and every sandbox once a second until stopped |
| `memory_report.py OUT.jsonl` | any Python | the peaks, how many sandboxes ran at once, the jobs that cost most, a timeline |
| `capture_request.py OUTDIR OBJECT [TYPE]` | PartCAD's own interpreter | the request one render sends its sandbox, written to disk, and what the tree is made of |
| `replay_request.py CMD.json STDIN.json` | the sandbox's interpreter | that request run through `wrapper_export.py`, with the peak memory of each phase |

They read `/proc`, so they are Linux only.

## A whole run

```bash
cd ../partcad-ldraw-examples                 # or any package
python3 ../partcad/dev-tools/profiling/memory_sampler.py /tmp/run.jsonl & sampler=$!
PC_DAEMON_IDLE_TIMEOUT=0 pc --no-ansi render -r
kill $sampler
python3 ../partcad/dev-tools/profiling/memory_report.py /tmp/run.jsonl
```

Stop the package's daemon first (`pc daemon stop`) when the code changed, or the run is served by the daemon that
loaded the previous code.

To see what a smaller machine would do, run the whole thing inside one memory-limited cgroup -- the sampler as well as
`pc`, because the sampler reports the usage and peak of the cgroup *it* is in, and with the daemon stopped first, so
that the daemon `pc` starts is in it too:

```bash
pc daemon stop
systemd-run --user --scope -p MemoryMax=8G bash -c '
    python3 ../partcad/dev-tools/profiling/memory_sampler.py /tmp/run.jsonl & sampler=$!
    PC_DAEMON_IDLE_TIMEOUT=0 pc --no-ansi render -r; status=$?
    kill $sampler
    exit $status'
pc daemon stop
```

## One drawing, phase by phase

```bash
cd ../partcad-ldraw-examples
poetry --project ../partcad run python ../partcad/dev-tools/profiling/capture_request.py /tmp/capture castle png
~/.partcad/sandbox/pc-py-venv-3.11/bin/python -sOO ../partcad/dev-tools/profiling/replay_request.py \
    /tmp/capture/castle.png.cmd.json /tmp/capture/castle.png.stdin.json --output /tmp/castle.png
```

The sandbox's interpreter is the one PartCAD renders with: `pc-py-venv-<version>` for the `venv` sandbox, the conda
prefix for `conda`. The capture builds whatever the object is made of that is not cached yet.
