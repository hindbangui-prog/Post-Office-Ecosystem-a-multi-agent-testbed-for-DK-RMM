"""
What the facility's event topics mean, grouped.

These groupings were written inside the monitor, which was the wrong place for
them the moment anything else needed the same answer: the perturbation tracer
has to know what "an agent in difficulty" looks like, and if it and the monitor
disagreed about that, the spread one measures would not be the spread the other
detects. Two definitions of the same word is how two components stop describing
the same building.

They live here, in the communication package, because they are facts about the
log's vocabulary rather than about any reader of it. Importing them costs the
importer nothing and commits it to nothing -- which matters most for the
monitor, whose whole claim is that it is not part of what it watches.
"""

from __future__ import annotations

#: An attempt was given up and will be made again. Retrying is not failure -- a
#: facility that never retried would be one that dropped work -- so this is a
#: rate to watch rather than a fault to count.
RETRY_TOPICS = frozenset({
    "task_released", "queued_errand_rerouted", "queue_question_timed_out",
    "yield_failed", "pick_failed", "recovery_requested", "promise_revised",
})

#: Something was refused. The guardrails of this facility are its gates: the
#: policy gate over every agent decision, the intake gate at the door, and the
#: physical limits -- a full shelf, an occupied charge point.
REFUSAL_TOPICS = frozenset({
    "parcel_refused", "arrival_refused", "storage_refused", "charge_refused",
    "charge_unavailable", "message_refused", "parcel_returned",
})

#: Work changed hands.
SWITCH_TOPICS = frozenset({
    "task_released", "task_assigned", "errand_handed_over", "command_yield",
    "command_step_aside",
})

#: An agent or a robot is in difficulty, wherever it sits in the hierarchy.
#: Used for spread rather than for volume: the question these answer is not how
#: many such events there were but across how much of the population they were.
TROUBLE_TOPICS = (RETRY_TOPICS | REFUSAL_TOPICS
                  | frozenset({"blocked", "overdue", "charge_deferred"}))
