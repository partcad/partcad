#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Whether this machine has little memory for what PartCAD runs at once.

PartCAD aims its work at a share of the machine's memory ('memoryBudget') and
runs up to 'threadsMax' sandbox processes at once. Nothing is guessed about a
task, so tasks that start together may grow past what the budget leaves room
for: a drawing of a large assembly grows by up to 2.5 GB after it starts, and
the views of one model all start when its tree is ready. Where that is more than
the memory there is for each process, 'memoryPacing' is what keeps such a burst
from running the machine out of memory -- it starts new work one task at a time
once the work's memory is high -- and this check suggests it.

Low memory is read two ways: the budget is small for the processes that share
it (the machine is small, or the cgroup PartCAD runs in), or so much of the
machine is in use right now that what is still available is. Both are a warning:
everything works, and pacing is the user's to turn on, since it makes a run
slower once memory is high. With pacing on there is nothing to suggest.

Reading this costs a few system calls and slows nothing down: it runs when
`pc healthcheck` asks, and never while PartCAD works.
"""

import psutil

from partcad_utils.user_config import MEMORY_BUDGET_DEFAULT, MEMORY_PACING_ON, user_config

from .. import memory, sandbox_lock
from .tests import HealthCheckReport, HealthCheckTest

# Less memory than this for each sandbox process is low: what one drawing of a
# large assembly has been measured to grow by after it starts.
PER_PROCESS = 2.5 * 1024**3


def _advice() -> str:
    advice = (
        "Setting 'memoryPacing: true' (or PC_MEMORY_PACING=true) starts new work one task at a time once"
        " PartCAD's work holds %d%% of its memory budget, each after the memory has stopped rising; below"
        " that nothing waits. Work that becomes ready together while memory is still low starts together all"
        " the same: a share near 0 ('memoryPacing: 0.05') paces from the start, and a lower 'memoryBudget'"
        " (0.6, say) leaves more room for what a task grows by after it starts -- slower, and safer. Lowering"
        " 'threadsMax' runs fewer processes at once instead." % round(MEMORY_PACING_ON * 100)
    )
    if not getattr(user_config, "memory_budget", MEMORY_BUDGET_DEFAULT):
        advice += " Pacing needs 'memoryBudget', which is turned off."
    return advice


class MemoryPacingCheck(HealthCheckTest):
    def __init__(self):
        super().__init__(
            name="MemoryPacing",
            tags=["memory", "performance"],
            description="check there is enough memory for the sandbox processes PartCAD runs at once",
        )

    def auto_fixable(self) -> bool:
        return False

    def is_applicable(self) -> bool:
        return True

    def test(self) -> HealthCheckReport:
        if getattr(user_config, "memory_pacing", 0):
            return HealthCheckReport(self.name, self.findings)
        processes = sandbox_lock.process_slot_count(user_config)
        count_swap = bool(getattr(user_config, "memory_budget_swap", True))
        share = getattr(user_config, "memory_budget", MEMORY_BUDGET_DEFAULT) or MEMORY_BUDGET_DEFAULT
        capacity = memory.capacity(count_swap)
        budget = int(capacity * share)
        if budget < PER_PROCESS * processes:
            self.findings.append(
                "PartCAD's memory budget is %s (%d%% of the %s this machine has%s) for %d sandbox processes at"
                " once: %s each. A drawing of a large assembly can grow by 2.5 GB after it starts, and several"
                " that start together can run the machine out of memory. %s"
                % (
                    memory.size(budget),
                    round(share * 100),
                    memory.size(capacity),
                    ", swap included" if count_swap else "",
                    processes,
                    memory.size(budget // processes),
                    _advice(),
                )
            )
        else:
            available = psutil.virtual_memory().available + (psutil.swap_memory().free if count_swap else 0)
            if available < PER_PROCESS * processes:
                self.findings.append(
                    "Only %s of this machine's memory is available now%s, for %d sandbox processes at once:"
                    " %s each. Other programs hold the rest. A drawing of a large assembly can grow by 2.5 GB"
                    " after it starts, and several that start together can run the machine out of memory. %s"
                    % (
                        memory.size(available),
                        ", swap included" if count_swap else "",
                        processes,
                        memory.size(available // processes),
                        _advice(),
                    )
                )
        return HealthCheckReport(self.name, self.findings)

    def fix(self) -> bool:
        return False
