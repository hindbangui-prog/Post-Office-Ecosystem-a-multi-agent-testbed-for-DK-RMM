# DK-RMM evidence kinds

The [twenty indicators](dkrmm-indicators.md) are grouped into twelve evidence kinds
(`EVIDENCE` in [`post_office/dkrmm/monitor.py`](../post_office/dkrmm/monitor.py)), so that several indicators
driven by the same underlying events count as one finding, not several. The
four operational kinds are read even in a window too quiet to read the agents.

| Evidence kind | Type | Indicators | What it signals |
|---|---|---|---|
| refusal | behavioural | `guardrail_events` | Decisions and requests being refused by the gates |
| retry | behavioural | `retry_frequency` | Work being abandoned and started again |
| congestion | behavioural | `execution_latency`, `task_switching`, `tail_deviation` | Work queuing: longer waits, more hand-offs, worse tails |
| chatter | behavioural | `message_frequency`, `delegation_frequency`, `tool_call_frequency`, `interaction_density` | The volume of communication moving away from normal |
| herding | behavioural | `behavioural_similarity`, `agent_coupling` | The agents acting more (or less) alike than usual |
| spread | behavioural | `propagation_across_agents` | The deviation reaching a growing share of the agents |
| structure | behavioural | `dependency_graph_divergence` | Who talks to whom changing shape |
| synchrony | behavioural | `activity_synchronization` | The agents' activity rising and falling together |
| delivery | operational | `communication_failure_rate` | Messages dropped or delivered late |
| backlog | operational | `backlog_growth` | Parcels accumulating inside the building |
| throughput | operational | `task_completion_rate`, `completion_gap` | Fewer parcels leaving than arriving |
| saturation | operational | `resource_saturation` | A resource close to its capacity |

The state follows from the kinds present:

- **DEVIATING**: at least one kind.
- **UNSTABLE**: at least two kinds that also held in the previous window, or
  any kind while the facility has been off its baseline for three windows
  running.
- **RCT**: at least three kinds, one of them held from the previous window,
  at least half of the acting agents affected, and either a dragon-king
  extreme or critical slowing down (variance and memory both climbing).
