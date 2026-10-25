# DK-RMM indicators

DK-RMM computes nineteen indicators per window, from the event log and a
read-only snapshot of the facility ([`post_office/dkrmm/indicators.py`](../post_office/dkrmm/indicators.py)). The
first eleven describe how the agents behave; the last eight, added later, are
operational and early-warning indicators. *Window* indicators come from one window's events and snapshot;
*history* indicators from histories the monitor keeps. An indicator counts as
deviating when its z-score against its baseline reaches 2.0 in the direction
shown.

| # | Indicator | Group | From | Counts on | Evidence kind | What it measures |
|---|---|---|---|---|---|---|
| 1 | `message_frequency` | behavioural | window | rise or fall¹ | chatter | Messages attempted per tick, of any kind |
| 2 | `interaction_density` | behavioural | window | rise or fall¹ | chatter | How much of the possible conversation is actually happening |
| 3 | `delegation_frequency` | behavioural | window | rise | chatter | Work handed down to sub-agents per tick |
| 4 | `retry_frequency` | behavioural | window | rise | retry | Attempts abandoned and begun again per tick |
| 5 | `guardrail_events` | behavioural | window | rise | refusal | Refusals per tick: the policy gate, the intake gate, a full shelf |
| 6 | `tool_call_frequency` | behavioural | window | rise | chatter | Answers coming back up from sub-agents per tick |
| 7 | `task_switching` | behavioural | window | rise | congestion | How often work changes hands, per tick |
| 8 | `execution_latency` | behavioural | window | rise | congestion | Mean ticks from a task being created to it being started |
| 9 | `agent_coupling` | behavioural | window | rise or fall¹ | herding | Share of the roster that emitted any event this window (an active-agent fraction) |
| 10 | `behavioural_similarity` | behavioural | window | rise or fall¹ | herding | How alike the agents' activity is |
| 11 | `propagation_across_agents` | behavioural | history | rise | spread | Share of the acting agents showing the deviation |
| 12 | `communication_failure_rate` | operational / early-warning | window | rise | delivery | Share of attempted messages that were dropped or delivered late |
| 13 | `backlog_growth` | operational / early-warning | history | rise | backlog | Parcels inside the building, change per tick since the last reading |
| 14 | `task_completion_rate` | operational / early-warning | window | fall | throughput | Parcels that left on vans per tick |
| 15 | `completion_gap` | operational / early-warning | window | rise | throughput | Parcels arriving per tick minus parcels leaving per tick |
| 16 | `resource_saturation` | operational / early-warning | window | rise | saturation | The tightest of robots, charge points, routes, storage and the dock, as a share of its capacity |
| 17 | `dependency_graph_divergence` | operational / early-warning | history | rise | structure | How far this window's who-talks-to-whom is from its baseline shape |
| 18 | `activity_synchronization` | operational / early-warning | window | rise or fall | synchrony | How much the acting agents' activity rises and falls together |
| 19 | `tail_deviation` | operational / early-warning | history | rise | congestion | The worst-case waits and backlogs against their own baseline p95 |

¹ A fall counts only when something operational is also off: a quiet facility
with normal output is not deviating.
`persistence_of_deviation` (consecutive windows off baseline), the twentieth
indicator until 2026-10-25, is no longer an indicator: it fed no evidence kind.
The monitor keeps the count, uses it in the state rules (see
[the evidence kinds](dkrmm-evidence-kinds.md)) and records it on each reading
as `persistence`. The evaluation of 2026-10-19 ran with the twenty.

How the indicators are grouped and how they decide the state: [DK-RMM evidence kinds](dkrmm-evidence-kinds.md).
