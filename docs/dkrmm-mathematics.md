# DK-RMM Mathematical Formulation: From Runtime Observation to RCT Detection

This document reconstructs, from the source code, the mathematics that the DK-RMM implementation
of this prototype actually computes, from the moment an event is written to the run's event log to
the moment an assessment is labelled RCT. It describes the code as it is; it does not propose or
repair anything. Every formula below was read off the code and checked against it, most of them by
the hand-computed tests in `tests/test_dkrmm_math.py`, whose coverage and remaining gaps are listed in
section 19. Where the request for this
document names a mathematical device that the code does not contain (a bootstrap, a null
distribution, p-values, Fisher's method, a declared interaction graph, a posterior), the document
says so plainly: "Not explicitly implemented in the current code."

Code base: `post_office/dkrmm/` (`monitor.py`, `indicators.py`, `signals.py`, `states.py`,
`record.py`, and since 2026-10-12 `operations.py`) and `post_office/communication/topics.py`.
The DK-RMM code was extended on 2026-10-12 with eight operational and early-warning indicators,
direction-aware evidence, a directional severity and a baseline-learning rule
(`docs/superpowers/specs/2026-10-12-dkrmm-operational-indicators-design.md`). Sections 1 to 16
describe the base pipeline as it stood before that date and as it still runs for the original
twelve indicators; sections 17 to 20 are its traceability, edge cases, tests and gaps, also as
they stood; the new section 21 describes the extension, and where it changes a formula of
sections 10 to 15 it says so and states both versions. (The design note numbers this extension
"section 17"; that number was already taken here, so it is 21.) The extension's validation runs,
its tests and the dashboard changes are reported in
[docs/dkrmm-operational-indicators.md](dkrmm-operational-indicators.md).

## 1. Purpose and scope

DK-RMM (Dragon-King Runtime Monitoring Model) is an observer attached beside a running
post-office ecosystem. Every 20 ticks it reads the events of the last 60 ticks, computes twelve
behavioural indicators, scores each against its own recent past, aggregates the positive scores
into one severity number per assessment, computes two statistics on the history of that severity
(a critical-slowing-down reading and a rank-ordering "dragon-king" reading), and assigns one of
five operational states: STABLE, DEVIATING, UNSTABLE, RCT (Runtime Critical Transition) or
RECOVERY. A separate human gate (DISCOVERED, VALIDATED, ACTIVE, DISMISSED) records a person's
verdict on an assessment and does not change the state.

Scope: the online detection pipeline (sections 3 to 16). The offline record and comparison
functions of `record.py` and the RCT explanation of `observability/rct_explain.py` are described
only where they touch the pipeline (section 16.3); they do not take part in detection.

Three levels and one kind of rule are marked on every formula, as requested:

| Mark | Level | Meaning in this implementation |
|---|---|---|
| **[A]** | Observed | computed directly from the events of one window (or from the run's clock and roster) |
| **[B]** | Derived | computed from the history of base indicators or of severity |
| **[C]** | Statistical | computed against a reference distribution; here the only reference is each indicator's own empirical past (no theoretical or resampled null exists in the code) |
| **[D]** | Decision rule | converts numbers into a kind, a flag, or a state |

The words "heuristic", "observed", "derived" and "statistical" are used in these senses throughout.

## 2. Mathematical notation

### 2.1 Symbols

| Symbol | Meaning | Code |
|---|---|---|
| $t \in \mathbb{N}$ | simulation tick (integer clock) | `event.tick`, `eco.world.tick` |
| $e$ | one runtime event | `communication.events.Event` |
| $\tau(e) \in \mathbb{N}$ | the tick stamped on $e$ | `event.tick` |
| $\theta(e)$ | the topic of $e$ (a string) | `event.topic` |
| $\alpha(e)$ | the actor of $e$ (a string, possibly empty) | `event.actor` |
| $\beta(e)$ | the target of $e$ (a string, possibly empty) | `event.target` |
| $v(e)$ | the decision verdict stage of $e$ | `event.detail["validation"]` |
| $\kappa(e)$ | the task id carried by $e$ | `event.detail["task_id"]` |
| $\mathcal{D}$ | the monitor's event buffer (last 20 000 events observed) | `DKRMM._events` |
| $C$ | task creation map: task id $\mapsto$ tick first seen in a `task_created` event | `DKRMM._created` |
| $k = 1, 2, \dots$ | assessment index | position in `DKRMM.history` |
| $t_k$ | tick of assessment $k$ | `Assessment.tick` |
| $L$ | window length in ticks, 60 | `WINDOW` |
| $E$ | assessment period in ticks, 20 | `EVERY` |
| $W_k$ | the window of assessment $k$ (a multiset of events) | `DKRMM._window(now)` |
| $\Delta_k$ | the span used as the denominator of rates | `ticks=min(window, max(1, now))` |
| $N_k = \lvert W_k \rvert$ | number of events in the window | `BehaviouralIndicators.events` |
| $R_k$ | roster size: number of agents in the ecosystem at $t_k$ | `len(eco.agents)` |
| $\mathcal{M}_k$ | message events of $W_k$ | topics `message`, `subagent_message` |
| $\mathcal{A}_k$ | active actors: distinct non-empty actors of $W_k$ | `actors` |
| $\mathcal{A}^{act}_k$ | acting actors: actors of a non-message event | `acting` |
| $\mathcal{T}_k$ | actors in trouble | `in_trouble` |
| $\Pi_k$ | realized directed pairs of the window | `pairs` |
| $\mathbf{p}_a$ | topic-count profile of actor $a$ in $W_k$ | `actors[a]` |
| $x_{i,k}$ | value of indicator $i \in \{1,\dots,12\}$ at assessment $k$ | `BehaviouralIndicators` fields |
| $H_{i,k}$ | baseline of indicator $i$ used at $k$: its last $\le 24$ values before $k$ | `DKRMM._series[name]` |
| $B$ | baseline capacity, 24 | `BASELINE` |
| $\mu(\cdot), \sigma(\cdot)$ | arithmetic mean; population standard deviation | `statistics.mean`, `statistics.pstdev` |
| $z_{i,k}$ | standardized deviation of indicator $i$ | `Assessment.z[name]` |
| $s_k$ | composite severity | `Assessment.severity` |
| $\mathbf{S}_k$ | severity buffer: the last $\le 80$ severities including $s_k$ | `DKRMM._severity` |
| $\nu_k$ | persistence counter after assessment $k$ ($\nu_0 = 0$) | `DKRMM._persistence` |
| $G_g$ | indicators of evidence kind $g$ | `EVIDENCE[g]` |
| $\mathcal{K}_k$ | evidence kinds fired at $k$ | `kinds` |
| $\mathcal{K}^{c}_k$ | confirmed kinds: fired at $k$ and at $k-1$ | `confirmed` |
| $\rho_k$ | propagation across agents, $= x_{12,k}$ | `propagation_across_agents` |
| $\mathrm{CSD}_k$ | critical-slowing-down flag on $\mathbf{S}_k$ | `Precursors.slowing_down` |
| $\delta_k$ | dragon-king ratio: observed top severity over the tail's prediction | `DragonKing.ratio` |
| $\phi_k$ | goodness of the tail fit ($R^2$ form) | `DragonKing.fit_quality` |
| $\mathrm{DK}_k$ | dragon-king flag | `DragonKing.is_dragon` |
| $\omega_k$ | operational state of assessment $k$ | `Assessment.state` |
| $\mathbf{1}[\cdot]$ | indicator function | |

Topic groups (`communication/topics.py`):

$$
\begin{aligned}
\Theta_{RET} &= \{\texttt{task\_released}, \texttt{queued\_errand\_rerouted}, \texttt{queue\_question\_timed\_out}, \texttt{yield\_failed}, \texttt{pick\_failed}, \texttt{recovery\_requested}, \texttt{promise\_revised}\} \\
\Theta_{REF} &= \{\texttt{parcel\_refused}, \texttt{arrival\_refused}, \texttt{storage\_refused}, \texttt{charge\_refused}, \texttt{charge\_unavailable}, \texttt{message\_refused}, \texttt{parcel\_returned}\} \\
\Theta_{SW} &= \{\texttt{task\_released}, \texttt{task\_assigned}, \texttt{errand\_handed\_over}, \texttt{command\_yield}, \texttt{command\_step\_aside}\} \\
\Theta_{TR} &= \Theta_{RET} \cup \Theta_{REF} \cup \{\texttt{blocked}, \texttt{overdue}, \texttt{charge\_deferred}\} \\
\Theta_{MSG} &= \{\texttt{message}, \texttt{subagent\_message}\}
\end{aligned}
$$

Predicates: $\mathrm{sub}(a) = \mathbf{1}[a \text{ begins with } \texttt{"SUB-"}]$ (a sub-agent id);
$\mathrm{gov}(e) = \mathbf{1}[\theta(e) = \texttt{decision} \wedge v(e) \in \{\texttt{policy}, \texttt{state}\}]$
(a well-formed decision refused by the policy gate);
$\mathrm{mal}(e) = \mathbf{1}[\theta(e) = \texttt{decision} \wedge v(e) = \texttt{schema}]$
(a decision whose answer was not among the options).

### 2.2 Constants

| Constant | Value | Code | Role |
|---|---|---|---|
| $E$ | 20 | `monitor.EVERY` | ticks between assessments |
| $L$ | 60 | `monitor.WINDOW` | window length |
| $B$ | 24 | `monitor.BASELINE` | baseline capacity per indicator |
| $z^{*}$ | 2.0 | `monitor.DEVIATION_Z` | evidence threshold on $z$ |
| $K_{U}$ | 2 | `monitor.UNSTABLE_KINDS` | confirmed kinds for UNSTABLE |
| $K_{R}$ | 3 | `monitor.RCT_KINDS` | kinds for RCT |
| $\rho^{*}$ | 0.5 | `monitor.RCT_PROPAGATION` | propagation for RCT |
| $P^{*}$ | 3 | `monitor.PERSISTENT` | persistence for UNSTABLE on one kind |
| $N^{*}$ | 24 | `monitor.MIN_ACTIVITY` | minimum events to read a window |
| $\lvert\mathbf{S}\rvert_{max}$ | 80 | `max(80, 3 * BASELINE)` | severity buffer capacity |
| $m^{*}$ | 12 | `signals.MIN_POINTS` | minimum points for the two statistics |
| $n_{tail}$ | 12 | `signals.TAIL_POINTS` | points used by the tail fit |
| $\delta^{*}$ | 2.0 | `signals.DRAGON_FACTOR` | dragon-king ratio threshold |
| $\phi^{*}$ | 0.5 | literal in `dragon_king` | fit-quality threshold |
| | 20 000 | `deque(maxlen=20000)` | event buffer capacity |
| | 400 | `monitor.HISTORY` | assessments kept |
| | 16 | literal in `compute_indicators` | actors used for similarity |

Every constant is a fixed design choice stated in the code; none is estimated from data.

## 3. Runtime observation model

**Collection [A].** `DKRMM.attach()` registers `DKRMM.observe` as a subscriber of the ecosystem's
`EventLogger` (`monitor.py:197-206`). `EventLogger.emit` calls every subscriber synchronously with
each event it records, after writing it (`communication/events.py:166-170`), and swallows any
exception a subscriber raises. Every event of every category is delivered: there is no topic,
actor or category filter at collection time. The monitor sends no message, holds no reference
through which it writes, and is not on the message bus (tests `test_watching_a_run_does_not_change_it`,
`test_the_monitor_is_not_an_agent_and_not_on_the_bus`, `test_no_agent_or_model_layer_module_imports_dkrmm`).

**What is kept of an event.** Five fields are read anywhere in the pipeline: tick $\tau(e)$, topic
$\theta(e)$, actor $\alpha(e)$, target $\beta(e)$ and the detail map, and of the detail map only two keys,
$v(e)$ (decision stage) and $\kappa(e)$ (task id). The interaction-taxonomy stamps (`interaction_type`, `channel`), the correlation id, the
wall-clock time and every other detail field are not read (pinned by
`test_dkrmm_reads_the_same_run_with_and_without_stamping`).

**Buffer [A].** `observe` appends $e$ to $\mathcal{D}$, a FIFO of capacity 20 000; the oldest event
is dropped when it is full (`monitor.py:225`). If $\theta(e) = \texttt{task\_created}$ and
$\kappa(e) \neq \texttt{""}$, the creation map is updated only if the key is new:

$$
C \leftarrow C \cup \{\kappa(e) \mapsto \tau(e)\} \quad \text{if } \kappa(e) \notin \mathrm{dom}(C).
\tag{O1}
$$

When $\lvert C \rvert > 4000$, the 2000 earliest-inserted keys are removed (`monitor.py:231-233`).

**Time.** Time is the integer tick only. Observations are not aggregated per tick; they are kept as
individual events and grouped by window (section 4). The representation is a multiset of events
with categorical fields, from which counts, sets and topic profiles are derived.

## 4. Observation windows

**Schedule [D].** The runner calls `DKRMM.tick()` once per simulation tick, after the ecosystem has
stepped (`api/runner.py:518`, `tools/run_normal.py:332`), with $t$ = the world clock. An assessment
is made at the first call and then whenever at least $E$ ticks have passed since the last one
(`monitor.py:242-246`):

$$
\text{assess at } t \iff \big(\text{no assessment yet}\big) \ \lor\ \big(t - t_{k-1} \ge E\big).
\tag{W1}
$$

With one call per tick starting at $t=1$, the assessment ticks are $t_k = 1 + E(k-1)$, i.e.
1, 21, 41, ... (test `test_assessments_happen_at_the_first_call_then_every_twenty_ticks`; observed in
runs: 1, 21, 41, 61, ...).

**Window [A].** The window is a closed tick interval over the buffer (`monitor.py:249-251`):

$$
W_k = \{ e \in \mathcal{D} : t_k - L \le \tau(e) \le t_k \}.
\tag{W2}
$$

It contains up to $L+1 = 61$ tick values. Consecutive windows overlap on the 41 tick values
$[t_k - 40, t_k]$, so one event is read by three or four consecutive windows (the assessment ticks $t_k \in [\tau(e), \tau(e) + 60]$; fewer for events in the last 60 ticks of a run). Windows are tick-based;
the event-count cap (20 000 in $\mathcal{D}$) would truncate a window only if more than 20 000 events
fell into 61 ticks (not observed: a 1600-tick Normal run holds about 18 600 events in total).

**Span [A].** Rates are divided by

$$
\Delta_k = \min\big(L,\ \max(1, t_k)\big)
\tag{W3}
$$

(`monitor.py:258`), then floored at 1 inside `compute_indicators` (`span = max(1, int(ticks))`). Note
that $\Delta_k = 60$ while $W_k$ covers 61 tick values, and that early windows include tick 0
(simulation-start events) while $\Delta_k = t_k$ (test
`test_the_window_is_the_closed_interval_and_the_span_is_capped_at_sixty`).

**Historical windows [B].** Two histories are kept, both as FIFO buffers of assessments rather than
of ticks: the baseline $H_{i,k}$ of each indicator (capacity $B = 24$ assessments, i.e. the
preceding 480 ticks) and the severity buffer $\mathbf{S}_k$ (capacity 80 assessments, 1600 ticks).

**Comparison windows / bootstrap samples.** Not explicitly implemented in the current code. The
only comparisons are (i) one window against its own baseline buffer (section 10) and (ii) the
earlier half of $\mathbf{S}_k$ against the later half (section 13.1).

## 5. Ecosystem state representation

DK-RMM does not build a state object of the ecosystem. Its only inputs besides the event stream are
two scalars read from the ecosystem at assessment time: the clock $t$ and the roster size
$R_k = \lvert \texttt{eco.agents} \rvert$ (`monitor.py:256`; 28 in the Normal configuration: one
supervisor, one planner, six experts, fifteen sub-agents, five robot agents).

| Quantity | Status | Definition |
|---|---|---|
| active agents $\mathcal{A}_k$ | observed [A] | non-empty actors of $W_k$ (may include the non-agent actors `ENVIRONMENT` and `SIMULATION`, which were observed as actors in Normal runs) |
| acting agents $\mathcal{A}^{act}_k$ | observed [A] | actors of non-message events |
| communication | observed [A] | $\mathcal{M}_k$ and $\Pi_k$ |
| tasks | observed [A] | `task_created` (into $C$) and `task_started` events |
| resources, physical/digital assets | not represented | resource events enter only through their topics ($\Theta_{REF}$, $\Theta_{TR}$) |
| dependencies, graph structure | not represented beyond $\Pi_k$ | section 6 |
| estimated quantities | none | the code estimates no latent state |

The ecosystem's own `state.SystemState` (used by the API) is not read by DK-RMM.

## 6. Interaction graphs

**Realized graph [A].** The code builds, per window, the set of directed actor-target pairs of
message events (`indicators.py:205-208`):

$$
\Pi_k = \{ (\alpha(e), \beta(e)) : e \in \mathcal{M}_k,\ \alpha(e) \neq \texttt{""},\ \beta(e) \neq \texttt{""} \},
\qquad \mathcal{M}_k = \{ e \in W_k : \theta(e) \in \Theta_{MSG} \}.
\tag{G1}
$$

$\Pi_k$ is an unweighted directed edge set: a pair is present once however many messages it
carried; no edge weight is computed. Self-loops are not excluded by the code (a message with
$\alpha(e) = \beta(e)$ would add one); none was observed in a 1600-tick Normal run. The node set
used to normalise it is $\mathcal{A}_k$ (all actors of the window, of any topic), so a target that
never acted in the window is an endpoint of an edge without being counted among the nodes. The
graph is used only through its edge count, in the interaction density $x_{2,k}$ (section 7.2).

**Declared graph.** Not explicitly implemented in the current code. The communication package
holds the hierarchy that decides which agent may message which (`communication/directory.py`,
`Directory.may_send`), but DK-RMM does not read it.

**Divergence between realized and declared graphs.** Not explicitly implemented in the current
code. No graph distance, divergence or comparison is computed.

## 7. Base indicators

All twelve are computed by `compute_indicators(events, ticks, roster, created, persistence)`
(`indicators.py:155-294`) over $W_k$ with $\Delta_k$, $R_k$, $C$ and $\nu_{k-1}$. Counts used below
(`indicators.py:171-259`):

$$
\begin{aligned}
n^{msg}_k &= \lvert \mathcal{M}_k \rvert, &
n^{tool}_k &= \lvert \{ e \in \mathcal{M}_k : \mathrm{sub}(\alpha(e)) \} \rvert, \\
n^{del}_k &= \lvert \{ e \in \mathcal{M}_k : \neg \mathrm{sub}(\alpha(e)) \wedge \mathrm{sub}(\beta(e)) \} \rvert, &
n^{ret}_k &= \lvert \{ e \in W_k : \theta(e) \in \Theta_{RET} \} \rvert, \\
n^{sw}_k &= \lvert \{ e \in W_k : \theta(e) \in \Theta_{SW} \} \rvert, &
n^{ref}_k &= \lvert \{ e \in W_k : \theta(e) \in \Theta_{REF} \vee \mathrm{gov}(e) \} \rvert .
\end{aligned}
\tag{N}
$$

(The code also counts $\lvert\{\theta(e) = \texttt{blocked}\}\rvert$ and
$\lvert\{\mathrm{mal}(e)\}\rvert$ as `counts["blocked"]` and `counts["malformed_decisions"]`;
neither enters any indicator.) Sets:

$$
\mathcal{A}_k = \{\alpha(e) : e \in W_k, \alpha(e) \neq \texttt{""}\},\quad
\mathcal{A}^{act}_k = \{\alpha(e) : e \in W_k, \alpha(e) \neq \texttt{""}, \theta(e) \notin \Theta_{MSG}\},
$$
$$
\mathcal{T}_k = \{\alpha(e) : e \in W_k, \alpha(e) \neq \texttt{""}, \theta(e) \in \Theta_{TR} \vee \mathrm{gov}(e)\}.
\tag{S}
$$

Because no topic of $\Theta_{TR}$ is a message topic and `decision` is not one either,
$\mathcal{T}_k \subseteq \mathcal{A}^{act}_k$ always.

All twelve are level [A] except $x_{11}$, which is a derived count of past states [B]. None is
normalised other than by $\Delta_k$, $R_k$ or a set size as written. "Range" below is what the
formula permits.

### 7.1 Message frequency $x_1$ [A]

$$ x_{1,k} = n^{msg}_k / \Delta_k \tag{I1} $$

Messages of any kind per tick. Range $[0, \infty)$. `message_frequency`. Unit: messages per tick.

### 7.2 Interaction density $x_2$ [A]

$$
x_{2,k} = \begin{cases} \dfrac{\lvert \Pi_k \rvert}{\lvert \mathcal{A}_k \rvert \,(\lvert \mathcal{A}_k \rvert - 1)} & \lvert \mathcal{A}_k \rvert \ge 2 \\[1ex] 0 & \text{otherwise} \end{cases}
\tag{I2}
$$

The share of possible ordered actor pairs that exchanged at least one message. Because targets need
not belong to $\mathcal{A}_k$ (section 6) and a self-pair $(a, a)$ would be counted in $\Pi_k$ but not
among the $\lvert\mathcal{A}_k\rvert(\lvert\mathcal{A}_k\rvert - 1)$ ordered pairs, the formula does not bound $x_2$ by 1, although in
practice it stays well below. `interaction_density`. Dimensionless.

### 7.3 Delegation frequency $x_3$ [A]

$$ x_{3,k} = n^{del}_k / \Delta_k \tag{I3} $$

Messages from a non-sub-agent to a sub-agent per tick: work handed down. Expert-to-expert
consultation messages (`CONSULT_*`) have no sub-agent end and are not counted here (test
`test_the_monitor_sees_the_consultation_as_messages`). `delegation_frequency`. Unit: per tick.

### 7.4 Retry frequency $x_4$ [A]

$$ x_{4,k} = n^{ret}_k / \Delta_k \tag{I4} $$

`retry_frequency`. Unit: per tick.

### 7.5 Guardrail events $x_5$ [A]

$$ x_{5,k} = n^{ref}_k / \Delta_k \tag{I5} $$

Refusals at the facility's gates plus decisions refused by the policy gate at the `policy` or
`state` stage. A `schema` refusal (malformed answer) is excluded. $\Theta_{REF}$ lists `charge_refused`,
which no module emits; the environment emits `charging_refused` (`environment/facility.py:356`), which
belongs to no topic group, so a refused charge point is not counted in $x_5$ or in $\mathcal{T}_k$; the
same holds for `consult_refused` (`crew/events.py`), a refused expert consultation (tests
`test_a_policy_refusal_is_a_guardrail_event`, `test_a_schema_refusal_is_counted_apart_from_the_guardrail`).
`guardrail_events`. Unit: per tick.

### 7.6 Tool-call frequency $x_6$ [A]

$$ x_{6,k} = n^{tool}_k / \Delta_k \tag{I6} $$

Messages sent by a sub-agent (answers coming back up) per tick. `tool_call_frequency`.

### 7.7 Task switching $x_7$ [A]

$$ x_{7,k} = n^{sw}_k / \Delta_k \tag{I7} $$

`task_switching`. Note that `task_released` belongs to both $\Theta_{RET}$ and $\Theta_{SW}$ and so
raises $x_4$ and $x_7$ together.

### 7.8 Execution latency $x_8$ [A, uses the cross-window map $C$]

Let $\mathcal{S}^{start}_k = \{ e \in W_k : \theta(e) = \texttt{task\_started},\ \kappa(e) \in \mathrm{dom}(C) \}$. Then

$$
x_{8,k} = \begin{cases} \dfrac{1}{\lvert \mathcal{S}^{start}_k \rvert} \displaystyle\sum_{e \in \mathcal{S}^{start}_k} \max\big(0,\ \tau(e) - C(\kappa(e))\big) & \mathcal{S}^{start}_k \neq \emptyset \\[1ex] 0 & \text{otherwise} \end{cases}
\tag{I8}
$$

(`indicators.py:134-152`). Mean ticks from creation to start of the tasks started in the window;
tasks created before the monitor attached (or pruned from $C$) are skipped. Unit: ticks.

### 7.9 Agent coupling $x_9$ [A]

$$ x_{9,k} = \begin{cases} \lvert \mathcal{A}_k \rvert / R_k & R_k > 0 \\ 0 & \text{otherwise} \end{cases} \tag{I9} $$

The share of the roster that appears as an actor. $\mathcal{A}_k$ can contain actors that are not
on the roster (`ENVIRONMENT`, `SIMULATION`), so the formula does not bound $x_9$ by 1; in a
1600-tick Normal run its maximum was 1.0. Despite its name, this is a participation share, not a
coupling or dependency statistic. `agent_coupling`.

### 7.10 Behavioural similarity $x_{10}$ [A]

For each $a \in \mathcal{A}_k$, the profile $\mathbf{p}_a$ maps each topic to the number of events of
that topic with actor $a$ in $W_k$ (all topics, messages included). Let $\mathcal{B}_k$ be the
(at most) 16 profiles with the largest totals $\sum_\theta \mathbf{p}_a[\theta]$ (a stable sort, so
ties keep first-appearance order). With

$$
\cos(\mathbf{p}, \mathbf{q}) = \begin{cases} \dfrac{\sum_{\theta \in \mathrm{supp}\,\mathbf{p} \cap \mathrm{supp}\,\mathbf{q}} \mathbf{p}[\theta]\,\mathbf{q}[\theta]}{\lVert \mathbf{p} \rVert_2 \lVert \mathbf{q} \rVert_2} & \mathrm{supp}\,\mathbf{p} \cap \mathrm{supp}\,\mathbf{q} \neq \emptyset \\[1ex] 0 & \text{otherwise} \end{cases}
$$

$$
x_{10,k} = \begin{cases} \binom{\lvert \mathcal{B}_k \rvert}{2}^{-1} \displaystyle\sum_{\{\mathbf{p}, \mathbf{q}\} \subseteq \mathcal{B}_k} \cos(\mathbf{p}, \mathbf{q}) & \lvert \mathcal{B}_k \rvert \ge 2 \\[1ex] 0 & \text{otherwise} \end{cases}
\tag{I10}
$$

(`indicators.py:124-131, 263-271, 288-289`). Range $[0, 1]$ (counts are non-negative), up to floating-point rounding (identical profiles can give
1.0000000000000002). Interpreted
in the code as herding (agents doing the same things). The cap of 16 is a cost heuristic.

### 7.11 Persistence of deviation $x_{11}$ [B]

$$ x_{11,k} = \nu_{k-1} \tag{I11} $$

The number of consecutive previous assessments whose computed state was not STABLE (section 15.2),
as it stood before assessment $k$. It is not computed from $W_k$; it is passed in
(`monitor.py:259`). Unit: assessments.

### 7.12 Propagation across agents $x_{12}$ [A]

$$ x_{12,k} = \rho_k = \begin{cases} \lvert \mathcal{T}_k \cap \mathcal{A}^{act}_k \rvert / \lvert \mathcal{A}^{act}_k \rvert & \mathcal{A}^{act}_k \neq \emptyset \\ 0 & \text{otherwise} \end{cases} \tag{I12} $$

Since $\mathcal{T}_k \subseteq \mathcal{A}^{act}_k$, this equals $\lvert \mathcal{T}_k \rvert / \lvert \mathcal{A}^{act}_k \rvert$.
The share of acting agents with at least one trouble event. The denominator excludes actors that
only sent messages (sub-agents, which cannot emit trouble events), as the code comments explain.
Range $[0, 1]$. `propagation_across_agents`.

## 8. Derived / historical indicators

The code derives the following from histories. Nothing else is derived.

| Derived quantity | Level | Definition | Section |
|---|---|---|---|
| persistence counter $\nu_k$ | [B] | consecutive non-STABLE computed states | 15.2 |
| baseline $H_{i,k}$ | [B] | last $\le 24$ values of $x_i$ before $k$ | 10 |
| severity buffer $\mathbf{S}_k$ | [B] buffer of [C] values | last $\le 80$ severities | 11 |
| variance, lag-1 autocorrelation, skewness of $\mathbf{S}_k$ and of its two halves | [B] | section 13.1 | 13.1 |
| rank-ordering tail fit of $\mathbf{S}_k$ | [B] | section 13.2 | 13.2 |

Not explicitly implemented in the current code: moving averages of an indicator, slopes, curvature,
acceleration, second differences, change-point statistics, growth rates and higher-order derivatives
of any indicator. Variance and autocorrelation are computed only on the severity series, never on an
individual indicator.

## 9. Null and bootstrap model

Not explicitly implemented in the current code. There is no resampling, no stationary or block
bootstrap, no block-length rule, no replicates, no null distribution, no quantile, no p-value and no
treatment of serial dependence. The overlapping windows of section 4 make successive indicator
values serially dependent; the code does not correct for this.

The only reference condition in the code is each indicator's own empirical past $H_{i,k}$
(section 10). The only quantity in the code that is a ratio with reference value 1 is the dragon-king
ratio $\delta_k$ (section 13.2): it equals 1 when the extrapolated tail explains the largest
severity exactly, and the code's decision threshold is $\delta_k \ge 2$, not $\delta_k > 1$. That
reference value comes from a least-squares extrapolation, not from a resampled null.

## 10. Standardized evidence

**Baseline [B].** For each indicator $i$, $H_{i,k}$ is the FIFO of its last $\min(B, k-1)$ values,
read before $x_{i,k}$ is appended (`monitor.py:264-268`):

$$
H_{i,k} = (x_{i,\max(1,k-B)}, \dots, x_{i,k-1}), \qquad \text{then } H_{i,k+1} = \text{last } B \text{ of } (H_{i,k}, x_{i,k}).
\tag{H}
$$

**Standardized deviation [C].** `zscore(value, history)` (`signals.py:243-260`), with $n = \lvert H_{i,k} \rvert$,
$\mu = \mu(H_{i,k})$, $\sigma = \sigma(H_{i,k}) = \sqrt{\tfrac{1}{n}\sum_j (h_j - \mu)^2}$ (population form):

$$
z_{i,k} = \begin{cases}
0 & n < 4 \\
0 & n \ge 4,\ \sigma \le 10^{-9},\ \lvert x_{i,k} - \mu \rvert \le 10^{-9} \\
3 & n \ge 4,\ \sigma \le 10^{-9},\ \lvert x_{i,k} - \mu \rvert > 10^{-9} \\
(x_{i,k} - \mu) / \sigma & \text{otherwise}
\end{cases}
\tag{Z}
$$

What it measures: how many baseline standard deviations the current window's value lies from the
mean of the same indicator's previous (at most) 24 windows. The reference distribution is the
indicator's own recent empirical history; no distributional form is assumed or used, and $z_{i,k}$
is not converted into a probability. The flat-baseline branch returns $+3$ for any change,
including a decrease (a heuristic; test
`test_zscore_on_a_flat_baseline_is_zero_or_plus_three_whatever_the_direction`). The first four
assessments have $z_{i,k} = 0$ for every indicator (their baselines hold 0, 1, 2 and 3 values).

**Evidence threshold [D].** An indicator counts as evidence when $z_{i,k} \ge z^{*} = 2$
(`monitor.py:323`). This is a fixed threshold on a standardized score, not a significance test.

## 11. Indicator combination

**Composite severity [C, aggregate].** One number per assessment (`monitor.py:273`):

$$
s_k = \frac{1}{12} \sum_{i=1}^{12} \max(0, z_{i,k}).
\tag{SEV}
$$

The mean of the positive parts of the twelve standardized deviations: only excess above baseline
counts. Equal weights; correlated indicators are not de-weighted here. $s_k$ is appended to
$\mathbf{S}$ (capacity 80): $\mathbf{S}_k = $ last 80 of $(\mathbf{S}_{k-1}, s_k)$. Severity is the
series on which both statistics of section 13 are computed; it does not by itself decide a state.

**Evidence kinds [D].** The twelve indicators are grouped into six kinds (`monitor.py:99-107`);
$x_{11}$ (persistence) belongs to none:

| Kind $g$ | $G_g$ |
|---|---|
| refusal | $\{x_5\}$ |
| retry | $\{x_4\}$ |
| congestion | $\{x_8, x_7\}$ |
| chatter | $\{x_1, x_3, x_6, x_2\}$ |
| herding | $\{x_{10}, x_9\}$ |
| spread | $\{x_{12}\}$ |

$$
\mathcal{K}_k = \{ g : \exists i \in G_g,\ z_{i,k} \ge z^{*} \} \quad (\text{when } N_k \ge N^{*};\ \mathcal{K}_k = \emptyset \text{ otherwise}).
\tag{K}
$$

A kind counts once however many of its indicators fire. This is the code's combination rule: a
count of distinct kinds, not a combined test statistic. The grouping is intended to stop indicators
driven by the same events from being counted as independent findings; the code does not test
independence.

**Fisher's method / dependent combiners.** Not explicitly implemented in the current code. No
p-values exist to combine, no $-2\sum \ln p_i$ is computed, and no chi-square or other reference
distribution is used.

## 12. Synchronization, coupling and systemic indicators

What the code computes in this family, all at level [A]:

| Quantity | Formula | What it is |
|---|---|---|
| interaction density $x_2$ | (I2) | share of ordered actor pairs that messaged |
| agent coupling $x_9$ | (I9) | share of the roster that appears as an actor in the window (any topic, messages included); a participation ratio |
| behavioural similarity $x_{10}$ | (I10) | mean pairwise cosine of topic profiles of the 16 busiest actors |
| propagation $x_{12}$ | (I12) | share of acting agents in trouble |

Not explicitly implemented in the current code: a coupling statistic with a bootstrap null centered
at 1, a coupling ratio $z^{cpl}$ or $\delta^{cpl}$, synchronization or coordinated-change measures
across indicators or agents, dependency-structure estimation, graph evolution measures, and
interaction-concentration measures. The name `agent_coupling` refers to (I9), which is a
participation share; it does not measure coupling between agents.

## 13. Early-warning signals

Both statistics are computed on the severity buffer $\mathbf{S}_k = (s_{1}', \dots, s_{m}')$,
$m = \lvert \mathbf{S}_k \rvert \le 80$, which includes the current $s_k$ (`monitor.py:274, 296-297,
336-337`). They are therefore early-warning readings of the composite severity, not of any
individual indicator.

### 13.1 Critical slowing down [B, then D]

`precursors(series)` (`signals.py:125-181`). For a sequence $y = (y_1,\dots,y_n)$ with mean $\bar y$:

$$
\mathrm{Var}(y) = \begin{cases} \tfrac{1}{n}\sum_j (y_j - \bar y)^2 & n \ge 2 \\ 0 & n < 2 \end{cases}
\tag{V}
$$

$$
\mathrm{AC}_1(y) = \begin{cases}
0 & n \le 2 \ \text{ or } \ \sum_j (y_j - \bar y)^2 \le 10^{-12} \\
\mathrm{clip}_{[-1,1]}\!\left( \dfrac{\sum_{j=1}^{n-1} (y_j - \bar y)(y_{j+1} - \bar y)}{\sum_{j=1}^{n} (y_j - \bar y)^2} \right) & \text{otherwise}
\end{cases}
\tag{AC}
$$

$$
\mathrm{Skew}(y) = \begin{cases}
0 & n < 3 \ \text{ or } \ \sigma(y) \le 10^{-12} \\
\tfrac{1}{n}\sum_j \big((y_j - \bar y)/\sigma(y)\big)^3 & \text{otherwise}
\end{cases}
\tag{SK}
$$

($\sigma$ is the population standard deviation.) (The clip in (AC) never takes effect: by the Cauchy-Schwarz inequality the ratio already lies in
$[-1, 1]$.) If $m < m^{*} = 12$ the reading is "not enough" and
all three rising flags are false. Otherwise, with $h = \lfloor m/2 \rfloor$, early half
$y^{e} = (s'_1, \dots, s'_h)$ and late half $y^{l} = (s'_{h+1}, \dots, s'_m)$ (the late half takes the
extra point when $m$ is odd):

$$
r^{V}_k = \mathbf{1}[\mathrm{Var}(y^{l}) > \mathrm{Var}(y^{e})],\quad
r^{AC}_k = \mathbf{1}[\mathrm{AC}_1(y^{l}) > \mathrm{AC}_1(y^{e})],\quad
r^{SK}_k = \mathbf{1}[\mathrm{Skew}(y^{l}) > \mathrm{Skew}(y^{e})].
\tag{R}
$$

$$
\mathrm{CSD}_k = \mathbf{1}[m \ge 12] \cdot r^{V}_k \cdot r^{AC}_k .
\tag{CSD}
$$

What it measures: whether the recent half of the severity history is both more variable and more
autocorrelated than the earlier half. This follows the critical-slowing-down idea (rising variance
and lag-1 autocorrelation before a transition), applied as a strict two-half comparison with no
significance test and no trend estimate. The skewness flag is computed and reported (the count
$r^{V}+r^{AC}+r^{SK}$ is `Precursors.rising`) but is not part of $\mathrm{CSD}_k$. Because the halves
span the whole buffer (up to 80 assessments, 1600 ticks), each half covers up to 40 assessments
(800 ticks); the halves are equal in length, or the later half has one extra point when $m$ is odd,
and both grow from 6 to 40 points while the buffer fills. The whole-series values $\mathrm{Var}, \mathrm{AC}_1, \mathrm{Skew}$
of $\mathbf{S}_k$ are reported but not used in any decision.

### 13.2 Rank-ordering ("dragon-king") test [B, then D]

`dragon_king(series)` (`signals.py:184-240`). Let $V = (V_1 \ge V_2 \ge \dots)$ be the strictly
positive entries of $\mathbf{S}_k$ in decreasing order; zero severities are discarded. If
$\lvert V \rvert < 12$, the reading is "not enough" and $\mathrm{DK}_k = 0$. Otherwise the tail is
$(V_1, \dots, V_{12})$ ($n_{tail} = 12$; the code's `max(4, min(12, |V|))` equals 12 whenever the
reading is enough). The largest point is held out and a least-squares line is fitted to
$\ln V_r$ against $\ln r$ for ranks $r = 2, \dots, 12$ (11 points):

$$
u_r = \ln r,\quad w_r = \ln V_r,\qquad
b = \frac{\sum_r (u_r - \bar u)(w_r - \bar w)}{\sum_r (u_r - \bar u)^2},\qquad
a = \bar w - b\,\bar u .
\tag{DK1}
$$

The fitted line predicts the rank-1 value $\hat V_1 = e^{a + b \ln 1} = e^{a}$. Then

$$
\delta_k = \begin{cases} V_1 / e^{a} & e^{a} > 10^{-12} \\ 0 & \text{otherwise} \end{cases},
\qquad
\phi_k = \begin{cases} 1 - \dfrac{\sum_r (w_r - a - b u_r)^2}{\sum_r (w_r - \bar w)^2} & \sum_r (w_r - \bar w)^2 > 10^{-12} \\[1ex] 1 & \text{else if residual} \le 10^{-12} \\ 0 & \text{otherwise} \end{cases}
\tag{DK2}
$$

$$
\mathrm{DK}_k = \mathbf{1}[\delta_k \ge \delta^{*} = 2 \ \wedge\ \phi_k > \phi^{*} = 0.5].
\tag{DK3}
$$

What it measures: how far the largest severity in the buffer lies above the value predicted by a
log-log (power-law-shaped) extrapolation of the next eleven largest severities, and whether that
extrapolation fitted well ($R^2 > 0.5$). $\delta_k \approx 1$ means the tail explains its largest
value; $\delta_k \ge 2$ with a good fit flags an outlier of a different order. This is a heuristic
rank-ordering outlier test: the code computes no confidence interval, p-value or null distribution
for $\delta_k$. The slope $b$ is reported (`DragonKing.slope`) but not used in the decision. With 11
distinct log-ranks the "zero spread of $u$" fallback in the code cannot trigger. Tests:
`test_a_power_law_tail_explains_its_own_largest_value`, `test_a_point_three_times_above_the_tail_is_flagged`,
`test_a_tail_explains_its_own_largest_value`, `test_a_value_above_the_tail_is_a_dragon_king`.

### 13.3 Levels of an indicator, side by side

| Level | Object | Example |
|---|---|---|
| raw indicator [A] | $x_{i,k}$ | $x_{5,k}$ = refusals per tick |
| normalized indicator [C] | $z_{i,k}$ | (Z) |
| "significant" indicator [D] | $z_{i,k} \ge 2$ (a threshold, not a test) | (K) |
| precursor condition [D] | $\mathrm{CSD}_k$, $\mathrm{DK}_k$ on the severity history | (CSD), (DK3) |

Precursors per individual indicator $P_i(t)$: not explicitly implemented in the current code. The
precursor conditions are defined only on the composite severity series.

## 14. RCT detection

The state rule is `DKRMM._classify` (`monitor.py:305-370`), evaluated in order, first match wins.
Let $\mathcal{K}^{c}_k = \mathcal{K}_k \cap \mathcal{K}_{k-1}$, where $\mathcal{K}_{k-1}$ is the kind set
returned by the previous assessment (empty before the first assessment and after a low-activity
window). Let $\nu_{k-1}$ be the persistence counter before this assessment. The computed state
$\tilde\omega_k$ is

$$
\tilde\omega_k = \begin{cases}
\text{STABLE} & N_k < N^{*} = 24 \quad (\text{and } \mathcal{K}_k := \emptyset) \\
\text{RCT} & \lvert \mathcal{K}_k \rvert \ge 3 \ \wedge\ \lvert \mathcal{K}^{c}_k \rvert \ge 1 \ \wedge\ \rho_k \ge 0.5 \ \wedge\ (\mathrm{DK}_k \vee \mathrm{CSD}_k) \\
\text{UNSTABLE} & \lvert \mathcal{K}^{c}_k \rvert \ge 2 \\
\text{UNSTABLE} & \lvert \mathcal{K}_k \rvert \ge 1 \ \wedge\ \nu_{k-1} \ge P^{*} = 3 \\
\text{DEVIATING} & \lvert \mathcal{K}_k \rvert \ge 1 \\
\text{STABLE} & \text{otherwise}
\end{cases}
\tag{RULE}
$$

The RCT indicator is therefore

$$
\mathrm{RCT}_k = \mathbf{1}\big[ N_k \ge 24 \big]\cdot \mathbf{1}\big[ \lvert \mathcal{K}_k \rvert \ge 3 \big]\cdot \mathbf{1}\big[ \mathcal{K}_k \cap \mathcal{K}_{k-1} \neq \emptyset \big]\cdot \mathbf{1}\big[ \rho_k \ge 0.5 \big]\cdot \max\big(\mathrm{DK}_k, \mathrm{CSD}_k\big).
\tag{RCT}
$$

In words, an assessment is an RCT when, in a window with enough activity: (i) at least three of the
six evidence kinds have an indicator at least two baseline standard deviations above its mean;
(ii) at least one of those kinds also fired in the previous assessment (one-step persistence;
the other kinds may differ, which the code justifies as symptoms rotating during a regime change);
(iii) at least half of the acting agents had a trouble event in the window; and (iv) the composite
severity history shows either a dragon-king outlier or critical slowing down. All four are
required; (iv) is a disjunction.

Properties that follow from the code:

- Temporal requirement: one previous assessment (20 ticks earlier) for (ii), at least 12 positive
  severities in the buffer for $\mathrm{DK}_k$, at least 12 assessments for $\mathrm{CSD}_k$. The first
  four severities are 0 (section 10) and are discarded by the dragon-king test, so the dragon-king
  path cannot fire before the 16th assessment; the earliest possible RCT is the 12th assessment
  (tick 221 with the default schedule), through $\mathrm{CSD}_k$.
- Ordering: no requirement that the precursor precede the evidence; both are evaluated on the same
  assessment, and both statistics include the current severity.
- Confidence: no probability or significance level is attached to an RCT.
- Hysteresis: none beyond the RECOVERY label (section 15.3) and the persistence counter.
- RCT outranks UNSTABLE: an assessment satisfying both is labelled RCT.

Tests: `test_an_rct_needs_spread_and_the_statistics_as_well_as_evidence`,
`test_rct_needs_three_kinds_one_confirmed_spread_and_a_statistic`.

## 15. State estimation

### 15.1 States are rule outputs, not estimates

$\omega_k$ is a deterministic function of the current window, the baselines, the creation map, the
roster, the previous kind set, the previous state, the persistence counter and the severity history. No probability, posterior or confidence
over states is computed: a posterior $\pi_t$ or any similar quantity is not explicitly implemented in
the current code. The three objects are distinct:

$$
\underbrace{x_{i,k},\ z_{i,k},\ s_k}_{\text{indicator evidence}} \ \neq\ \underbrace{\omega_k \in \{\text{STABLE}, \text{DEVIATING}, \text{UNSTABLE}, \text{RCT}, \text{RECOVERY}\}}_{\text{state assessment}} \ \neq\ \underbrace{\mathrm{RCT}_k}_{\text{one value of the state}}
$$

### 15.2 Persistence [B]

After $\tilde\omega_k$ is computed (`monitor.py:278-281`):

$$
\nu_k = \begin{cases} 0 & \tilde\omega_k = \text{STABLE} \\ \nu_{k-1} + 1 & \text{otherwise} \end{cases}, \qquad \nu_0 = 0.
\tag{P}
$$

The counter is updated from the computed state before the RECOVERY relabelling, so a RECOVERY
assessment resets it to 0. $\nu_{k-1}$ (not $\nu_k$) is both the value of indicator $x_{11,k}$ and the
value tested in the UNSTABLE-by-persistence branch of (RULE). Through $x_{11}$, persistence also
enters $z_{11}$ and hence the severity $s$ that feeds $\mathrm{CSD}$ and $\mathrm{DK}$; it belongs to no
evidence kind.

### 15.3 Recovery [D]

With $\omega_{k-1}$ the previous assessment's final state (`monitor.py:283-288`):

$$
\omega_k = \begin{cases} \text{RECOVERY} & \omega_{k-1} \in \{\text{DEVIATING}, \text{UNSTABLE}, \text{RCT}\} \ \wedge\ \tilde\omega_k = \text{STABLE} \\ \tilde\omega_k & \text{otherwise.} \end{cases}
\tag{REC}
$$

RECOVERY is not in the escalated set, so a STABLE assessment after a RECOVERY stays STABLE (test
`test_stable_after_an_escalated_state_is_recovery_and_resets_persistence`).

### 15.4 Activity flag and human gate

$\texttt{enough\_activity}_k = \mathbf{1}[N_k \ge 24]$ is reported with every assessment. The
discovery status (DISCOVERED at creation; VALIDATED, ACTIVE, DISMISSED by a person through
`validate`, `activate`, `dismiss`) is attached to the current assessment and has no influence on
any formula above.

### 15.5 RCT and Dragon King are different objects

An RCT ($\omega_k = \text{RCT}$) is, in the code's own words, the state in which "the system is
changing regime rather than having a bad minute" (`states.py:31-33`); operationally it is (RCT):
converging evidence, spread across agents, and a precursor statistic on the severity history. Dragon-king theory concerns extreme events that do not belong to the tail of the
ordinary distribution. In this implementation the dragon-king test $\mathrm{DK}_k$ is one of two
alternative statistical conditions inside the RCT rule, applied to the history of the monitor's own
severity score. Neither implies the other: $\mathrm{DK}_k = 1$ without three kinds, confirmation and
spread is not an RCT, and an RCT can be declared on $\mathrm{CSD}_k$ with $\mathrm{DK}_k = 0$. The code
does not establish that an RCT is followed by an extreme event. (Interpretation, not implemented:
one may read an RCT as a runtime transition toward systemic instability, a condition that could
precede such an event; the code tests no such link.)

## 16. End-to-end mathematical formulation

### 16.1 One assessment

For $k$ with $t_k$ satisfying (W1):

1. $W_k = \{e \in \mathcal{D} : t_k - 60 \le \tau(e) \le t_k\}$, $\Delta_k = \min(60, \max(1, t_k))$, $N_k = \lvert W_k \rvert$, $R_k = \lvert\texttt{eco.agents}\rvert$. [A]
2. $x_{1..12,k}$ by (I1) to (I12), using $C$ for $x_8$ and $\nu_{k-1}$ for $x_{11}$. [A]/[B]
3. $z_{i,k} = Z(x_{i,k}; H_{i,k})$ by (Z); then $H_{i,k+1} \leftarrow$ append $x_{i,k}$, keep 24. [C]
4. $s_k = \tfrac{1}{12}\sum_i \max(0, z_{i,k})$; $\mathbf{S}_k \leftarrow$ append $s_k$, keep 80. [C]
5. $\mathcal{K}_k$ by (K) (empty if $N_k < 24$); $\mathcal{K}^{c}_k = \mathcal{K}_k \cap \mathcal{K}_{k-1}$. [D]
6. $\mathrm{CSD}_k$ by (V), (AC), (R), (CSD) on $\mathbf{S}_k$; $\delta_k, \phi_k, \mathrm{DK}_k$ by (DK1) to (DK3) on $\mathbf{S}_k$. [B] then [D]
7. $\tilde\omega_k$ by (RULE); $\nu_k$ by (P); $\omega_k$ by (REC). [D]

### 16.2 Compact chain

$$
e \xrightarrow{\ \text{append}\ } \mathcal{D}
\xrightarrow{\ \text{(W2)}\ } W_k
\xrightarrow{\ \text{(N),(S),(I1)–(I12)}\ } \mathbf{x}_k \in \mathbb{R}^{12}
\xrightarrow{\ \text{(Z) vs } H_{\cdot,k}\ } \mathbf{z}_k \in \mathbb{R}^{12}
\begin{cases}
\xrightarrow{\ \text{(SEV)}\ } s_k \xrightarrow{\ \mathbf{S}_k\ } (\mathrm{CSD}_k, \mathrm{DK}_k) \\
\xrightarrow{\ \text{(K)}\ } (\mathcal{K}_k, \mathcal{K}^{c}_k)
\end{cases}
\xrightarrow{\ \text{(RULE)},\ \rho_k\ } \tilde\omega_k
\xrightarrow{\ \text{(P),(REC)}\ } \omega_k
$$

### 16.3 Downstream, not part of detection

`record.py` transposes `DKRMM.history` into per-indicator series and lists state changes
(`transitions_of`: every $k$ with $\omega_k \neq \omega_{k-1}$; `rct_events` are those with
$\omega_k = \text{RCT}$). `timeline_of` records first ticks, including the first $k$ with
$\max_i z_{i,k} \ge 2$ and the first with at least two indicators at $z \ge 2$ (counted over
indicators, not kinds). `compare_records` compares a perturbed run with its control and reports the
first $k$ with $s^{pert}_k - s^{ctrl}_k \ge 0.5$ and the first $k$ with different states. These are
offline analyses of a finished history [B]; they change no state. The RCT explanation of
`observability/rct_explain.py` (saved with each RCT by the run recorder) counts trouble events by
kind and links them to consultations, over the half-open window $(t - 60, t]$ (one tick narrower than
(W2)); it is a description for a reader and is not part of (RULE). `timeline_of` and `compare_records`
apply their thresholds to values rounded by `Assessment.as_dict` ($z$ to 3 decimals, severity to 4),
so a $z$ of 1.9996 counts in the timeline but not in (K).

## 17. Code-to-mathematics traceability

| Mathematical object | Definition | Code function/class | Source file | Main variables | Test |
|---|---|---|---|---|---|
| collection | §3 | `DKRMM.attach`, `DKRMM.observe` | `dkrmm/monitor.py:197-233` | `_events`, `_created` | `test_watching_a_run_does_not_change_it`; `test_dkrmm_reads_the_same_run_with_and_without_stamping` |
| creation map $C$ | (O1) | `DKRMM.observe` | `dkrmm/monitor.py:226-233` | `_created` | `test_task_creation_keeps_the_first_tick_and_prunes_the_oldest_half` |
| schedule $t_k$ | (W1) | `DKRMM.tick` | `dkrmm/monitor.py:235-246` | `_last_at`, `every` | `test_assessments_happen_at_the_first_call_then_every_twenty_ticks` |
| window $W_k$ | (W2) | `DKRMM._window` | `dkrmm/monitor.py:249-251` | `floor`, `window` | `test_the_window_is_the_closed_interval_and_the_span_is_capped_at_sixty` |
| span $\Delta_k$ | (W3) | `DKRMM.assess`, `compute_indicators` | `dkrmm/monitor.py:258`, `indicators.py:168` | `ticks`, `span` | same; `test_rates_do_not_grow_with_the_length_of_the_window` |
| counts, sets | (N), (S) | `compute_indicators` | `dkrmm/indicators.py:171-259` | `counts`, `actors`, `acting`, `in_trouble`, `pairs` | `test_the_twelve_indicators_on_a_hand_built_window`; `test_a_policy_refusal_is_a_guardrail_event` et al. |
| topic groups | §2.1 | constants | `communication/topics.py:22-45` | `RETRY_TOPICS` etc. | indirectly by the indicator tests |
| realized pairs $\Pi_k$ | (G1) | `compute_indicators` | `dkrmm/indicators.py:205-208` | `pairs` | `test_the_twelve_indicators_on_a_hand_built_window` |
| $x_1, x_3..x_7$ | (I1), (I3)-(I7) | `compute_indicators` | `dkrmm/indicators.py:279-285` | `counts`, `span` | `test_the_twelve_indicators_on_a_hand_built_window`; `test_work_handed_down_and_answers_coming_back_up_roughly_balance` |
| $x_2$ | (I2) | `compute_indicators` | `dkrmm/indicators.py:261-262, 280` | `pairs`, `possible` | `test_the_twelve_indicators_on_a_hand_built_window`; `test_density_and_similarity_are_zero_with_fewer_than_two_actors` |
| $x_8$ | (I8) | `_latency` | `dkrmm/indicators.py:134-152` | `waits`, `created` | `test_the_twelve_indicators_on_a_hand_built_window` |
| $x_9$ | (I9) | `compute_indicators` | `dkrmm/indicators.py:287` | `active`, `roster` | `test_the_twelve_indicators_on_a_hand_built_window` |
| $x_{10}$ | (I10) | `_cosine`, `compute_indicators` | `dkrmm/indicators.py:124-131, 263-271, 288` | `busiest`, `similarities` | `test_behavioural_similarity_is_the_mean_pairwise_cosine_of_topic_profiles` |
| $x_{11}$ | (I11) | `compute_indicators(persistence=)` | `dkrmm/indicators.py:290`, `monitor.py:259` | `_persistence` | `test_persistence_counts_non_stable_assessments_and_feeds_the_next_window` |
| $x_{12} = \rho_k$ | (I12) | `compute_indicators` | `dkrmm/indicators.py:291-292` | `in_trouble`, `acting` | `test_the_twelve_indicators_on_a_hand_built_window`; `test_a_refused_decision_puts_its_agent_in_trouble_only_for_policy_or_state` |
| baseline $H$ | (H) | `DKRMM.assess` | `dkrmm/monitor.py:176-177, 264-268` | `_series` | `test_severity_is_the_mean_positive_z_over_the_twelve` (append after scoring) |
| $z_{i,k}$ | (Z) | `zscore` | `dkrmm/signals.py:243-260` | `values`, `spread` | `test_zscore_is_population_standardisation_against_the_baseline`; `test_zscore_needs_four_baseline_points`; `test_zscore_on_a_flat_baseline_is_zero_or_plus_three_whatever_the_direction`; `test_a_flat_baseline_is_not_a_standard_deviation_of_nothing` |
| severity $s_k$, $\mathbf{S}_k$ | (SEV) | `DKRMM.assess` | `dkrmm/monitor.py:180, 273-274` | `severity`, `_severity` | `test_severity_is_the_mean_positive_z_over_the_twelve` |
| kinds $\mathcal{K}_k$ | (K) | `DKRMM._classify`, `EVIDENCE` | `dkrmm/monitor.py:99-107, 320-329` | `kinds`, `hits` | `test_kinds_are_groups_with_a_member_at_or_above_two`; `test_several_indicators_of_one_kind_are_still_one_kind` |
| confirmed $\mathcal{K}^{c}_k$ | §14 | `DKRMM._classify` | `dkrmm/monitor.py:333`, `277` | `confirmed`, `_last_kinds` | `test_a_burst_that_lasts_one_window_is_not_instability`; `test_the_previous_kind_set_is_the_last_assessment_s` |
| Var, AC, Skew | (V), (AC), (SK) | `_variance`, `_autocorrelation`, `_skewness` | `dkrmm/signals.py:125-151` | | `test_precursor_statistics_by_hand` |
| CSD | (R), (CSD) | `precursors`, `Precursors.slowing_down` | `dkrmm/signals.py:65-81, 154-181` | `early`, `late` | `test_the_rising_flags_compare_the_later_half_with_the_earlier_half`; `test_an_odd_length_series_gives_the_extra_point_to_the_later_half`; `test_critical_slowing_down_is_visible_before_the_transition` |
| DK | (DK1)-(DK3) | `dragon_king` | `dkrmm/signals.py:184-240` | `tail`, `slope`, `intercept`, `ratio`, `quality` | `test_a_power_law_tail_explains_its_own_largest_value`; `test_a_point_three_times_above_the_tail_is_flagged`; `test_the_dragon_threshold_is_a_ratio_of_two`; `test_only_positive_values_enter_and_twelve_are_needed`; `test_a_value_above_the_tail_is_a_dragon_king` |
| state rule, RCT | (RULE), (RCT) | `DKRMM._classify` | `dkrmm/monitor.py:305-370` | `RCT_KINDS`, `RCT_PROPAGATION`, `UNSTABLE_KINDS`, `PERSISTENT`, `MIN_ACTIVITY` | `test_rct_needs_three_kinds_one_confirmed_spread_and_a_statistic`; `test_an_rct_needs_spread_and_the_statistics_as_well_as_evidence`; `test_two_confirmed_kinds_are_unstable_and_persistence_alone_also_is`; `test_low_activity_is_stable_with_no_kinds`; `test_rct_is_refused_without_a_confirmed_kind_or_with_only_two_kinds`; `test_no_kind_with_enough_activity_is_stable_and_the_activity_boundary_is_24`; `test_one_kind_of_evidence_is_a_deviation_and_two_are_instability` |
| persistence $\nu_k$ | (P) | `DKRMM.assess` | `dkrmm/monitor.py:278-281` | `_persistence` | `test_persistence_counts_non_stable_assessments_and_feeds_the_next_window`; `test_persistence_increments_on_each_non_stable_assessment` |
| recovery | (REC) | `DKRMM.assess`, `ESCALATED` | `dkrmm/monitor.py:283-288`, `states.py:41-42` | `previous` | `test_coming_back_is_itself_reported`; `test_stable_after_an_escalated_state_is_recovery_and_resets_persistence` |
| activity flag | §15.4 | `DKRMM.assess` | `dkrmm/monitor.py:295` | `MIN_ACTIVITY` | `test_low_activity_is_stable_with_no_kinds` |
| human gate | §15.4 | `validate`, `activate`, `dismiss` | `dkrmm/monitor.py:373-397` | `status` | `test_a_person_validates_activates_or_dismisses`; `test_a_dismissal_is_kept` |
| offline record | §16.3 | `series_of`, `transitions_of`, `timeline_of`, `compare_records` | `dkrmm/record.py` | | `tests/test_dkrmm_record.py` (13 tests) |

## 18. Edge cases

| Case | Behaviour in the code | Formula |
|---|---|---|
| no events in the window | every count 0, every set empty; all twelve indicators 0 (test `test_an_empty_window_gives_all_zero_indicators`); $N_k = 0 < 24$ so $\tilde\omega_k$ = STABLE and $\mathcal{K}_k = \emptyset$ | (I1)-(I12), (RULE) |
| fewer than 24 events | indicators, $z$ and $s_k$ are still computed and $s_k$ still enters $\mathbf{S}$; the computed state $\tilde\omega_k$ is STABLE (so $\nu_k = 0$), the reported state is RECOVERY if $\omega_{k-1}$ was escalated and STABLE otherwise, and the kinds are emptied, so the next assessment has nothing to confirm | (RULE), (REC) |
| zero denominators | $\Delta_k \ge 1$ always; $x_2 = 0$ if $\lvert\mathcal{A}_k\rvert < 2$; $x_9 = 0$ if $R_k = 0$; $x_{12} = 0$ if no acting agent; $x_8 = 0$ if no timed start; cosine 0 if no shared topic or a zero norm | as stated |
| one observation / one actor | $x_2 = x_{10} = 0$ | (I2), (I10) |
| first tick / first window | $t_1 = 1$, $\Delta_1 = 1$, window includes tick-0 events | (W1)-(W3) |
| short baseline | $z_{i,k} = 0$ while $\lvert H_{i,k}\rvert < 4$, i.e. for assessments 1 to 4 | (Z) |
| flat baseline | $z = 0$ if unchanged, otherwise $+3$ in either direction | (Z) |
| short severity history | $\mathrm{CSD} = 0$ if $\lvert\mathbf{S}\rvert < 12$; $\mathrm{DK} = 0$ if fewer than 12 positive severities | (CSD), (DK3) |
| zero severities | discarded by the DK test; counted by CSD | (DK1), (V) |
| tasks started before observation | skipped in $x_8$ | (I8) |
| missing detail keys | `validation` and `task_id` default to `""`; an event without them contributes nothing to $\mathrm{gov}$, $\mathrm{mal}$ or $C$ | (N), (O1) |
| absent agents | an agent on the roster with no event is simply absent from $\mathcal{A}_k$; it lowers $x_9$ | (I9) |
| non-roster actors | `ENVIRONMENT`, `SIMULATION` count in $\mathcal{A}_k$ (numerator of $x_9$, nodes of $x_2$, profiles of $x_{10}$); `ENVIRONMENT` also emits trouble topics (`parcel_refused`, `storage_refused`), so it can enter $\mathcal{A}^{act}_k$ and $\mathcal{T}_k$ and both terms of $x_{12}$ | (I2), (I9), (I10), (I12) |
| absent resources | not represented | §5 |
| disconnected graphs | no connectivity is computed; only the edge count enters $x_2$ | (I2) |
| empty bootstrap sample, failed estimation | not applicable: no resampling or iterative estimation exists | §9 |
| monitor exception | the logger swallows exceptions raised in `observe`; an exception inside `assess` propagates to the caller of `tick()`, which the API runner swallows (`api/runner.py:516-520`) and `tools/run_normal.py` does not | §3 |
| buffer limits | events beyond 20 000, baselines beyond 24, severities beyond 80, assessments beyond 400 are dropped oldest-first; the creation map drops its 2000 earliest-inserted keys whenever it exceeds 4000 | §3, §4 |

## 19. Test validation

The new file `tests/test_dkrmm_math.py` (28 tests) checks each formula against values worked out by
hand inside the test from the formula as written here, never against output recorded from the code:
(O1) first-sighting rule and pruning; (Z) on a known history, its short-history and flat branches;
all twelve indicators on a hand-built window of twelve events; (I10) with three profiles whose cosines
are computed explicitly; (V), (AC) and (SK) on small sequences; the two-half rule (R) including an
odd-length series that distinguishes the floor split from a ceiling split; (DK1)-(DK3) on an exact
power law $v_r = 10\,r^{-1}$ (expected $\hat V_1 = 10$, $\delta = 1$, $\phi = 1$), on the same tail with
$V_1 = 30$ ($\delta = 3$, flagged) and at the threshold ($V_1 = 20.01$ flagged, $19.99$ not); (W1)-(W3);
(SEV) end to end including a negative $z$ that the positive part must ignore; every branch of (RULE),
including the activity boundary (23 vs 24 events), the final STABLE branch, the RCT boundary
$\rho = 0.5$ vs $0.49$, the refusal of RCT without a confirmed kind, with only two kinds and without
either statistic; the refresh of $\mathcal{K}_{k-1}$; (REC); both branches of (P). The production code
was not changed. The tests call the private helpers that implement a formula (`_window`, `_classify`)
and set the monitor's private state to construct a case (`_series`, `_severity`, `_last_kinds`,
`_persistence`, `current.state`).

An independent audit of this document against the code (every equation, 34 line ranges, every
"not implemented" claim) and a mutation check of the tests (35 single-point changes to the
production code, made in a scratch copy) were carried out; the coverage gaps it found were closed by
the tests listed above.

Existing tests (section 17) cover the same objects at a behavioural level. Gaps that remain:

- The 20 000-event buffer and the 16-actor cap of (I10) are not tested at their limits.
- (CSD) is tested on constructed series, not on severity produced by a run.
- No test asserts $x_9 \le 1$ or $x_2 \le 1$, because the code does not guarantee either.
- No test checks the RCT rule on a full simulated run (a Normal seed-1 rules-mode run of 1600 ticks
  produces DEVIATING, UNSTABLE and RECOVERY but no RCT, no dragon-king flag and no slowing-down flag).

## 20. Known gaps and limitations

What the code computes, how it is interpreted, and what theory would suggest, kept apart:

1. **No null model or significance.** All "evidence" is a fixed threshold ($z \ge 2$) on a
   standardized deviation against a 24-window empirical baseline. Overlapping windows make the
   baseline values serially dependent and the $z$-scores are not calibrated probabilities.
   Bootstrap, p-values and evidence combination by Fisher's method are not implemented.
2. **Heuristic constants.** $E, L, B, z^{*}, K_U, K_R, \rho^{*}, P^{*}, N^{*}, \delta^{*}, \phi^{*}$, the
   12-point minimum, the 16-actor cap and the flat-baseline value 3 are design choices stated in
   the code, not estimated or derived.
3. **Composite before statistics.** CSD and the dragon-king test act on the severity series, an
   equal-weight mean of positive $z$-scores that includes $z_{11}$ (the persistence counter), so the
   state history feeds back into the statistics that decide the current and later states.
4. **CSD form.** A strict two-half comparison over a buffer of up to 80 assessments, with no trend
   estimate, window choice or significance; each half spans up to 40 assessments (800 ticks).
5. **Dragon-king form.** A least-squares log-rank extrapolation with an $R^2$ gate; no uncertainty on
   $\delta$. It flags an outlier in the monitor's own severity series, not an extreme event of the
   facility.
6. **Indicator naming.** `agent_coupling` is a participation share; `behavioural_similarity` is a
   topic-profile cosine of at most 16 actors; neither is a coupling or synchronization statistic in
   the sense of dynamical systems.
7. **Bounds not enforced.** $x_2$ and $x_9$ are not bounded by 1 by construction (non-roster actors for
   $x_9$; targets outside the actor set and self-pairs for $x_2$); observed values stayed within $[0, 1]$.
8. **Graphs.** Only the realized pair set of messages is formed, unweighted, and only its size is
   used. No declared graph and no graph divergence exist.
9. **Span vs window.** Rates divide by 60 while the closed window spans 61 tick values.
10. **Flat-baseline sign.** A drop on a flat baseline scores $+3$, the same as a rise.
11. **Topic vocabulary mismatch.** The refusal group names `charge_refused`, which is never emitted;
    the emitted `charging_refused` is in no group, so refused charging is invisible to $x_5$ and to
    propagation; the same holds for the emitted `consult_refused`. This is a property of `communication/topics.py`, not of the DK-RMM formulas.

## Self-audit

| Check | Result |
|---|---|
| every formula traces to actual code | yes: each equation carries a file and line range (§17) |
| every symbol is defined | yes: §2 |
| every indicator is identified | yes: twelve, §7 |
| every derived indicator is identified | yes: §8 (persistence, baselines, severity buffer, CSD statistics, tail fit) |
| windowing is mathematically defined | yes: (W1)-(W3), §4 |
| graph construction is mathematically defined | yes: (G1) |
| realized/declared distinction documented | yes: realized only; declared not implemented (§6) |
| graph divergence is the actual implementation | not implemented; stated (§6) |
| normalization is the actual implementation | yes: rates by $\Delta_k$, shares by set sizes, (Z) |
| bootstrap/null procedure is the actual implementation | not implemented; stated (§9) |
| z/statistical evidence is the actual implementation | yes: (Z), population sd, flat branch |
| coupling/synchronization mathematics is the actual implementation | yes: (I2), (I9), (I10), (I12); bootstrap coupling ratio not implemented (§12) |
| Fisher/dependent combination correctly described | not implemented; the combination is a kind count (§11) |
| early-warning conditions explicitly defined | yes: (CSD), (DK3) |
| RCT detection rule explicitly defined | yes: (RULE), (RCT) |
| state-estimation rule explicitly defined | yes: (RULE), (P), (REC); no posterior (§15) |
| missing-data/edge cases documented | yes: §18 |
| formulas have code locations | yes |
| formulas have test mappings | yes, with gaps listed (§19) |
| no invented theory presented as implementation | checked: every unimplemented device is marked so, and the one interpretive reading of RCT (§15.5) is labelled as interpretation |
| Dragon King and RCT not conflated | yes: §15.5 |

## DK-RMM in one mathematical chain

$$
\underbrace{e}_{\text{observation}}
\ \to\ \underbrace{W_k}_{\text{window}}
\ \to\ \underbrace{x_{i,k}}_{\text{base indicator}}
\ \to\ \underbrace{H_{i,k},\ \nu_{k-1}}_{\text{derived}}
\ \to\ \underbrace{z_{i,k},\ \mathcal{K}_k,\ s_k,\ \mathbf{S}_k}_{\text{statistical evidence}}
\ \to\ \underbrace{\mathrm{CSD}_k \vee \mathrm{DK}_k}_{\text{precursor}}
\ \to\ \underbrace{\mathrm{RCT}_k}_{\text{decision}}
$$

- **Observation to window:** every logged event is buffered, and each assessment, made every 20 ticks, reads those stamped in the last 60 ticks inclusive.
- **Window to base indicator:** twelve numbers are counted off that window (rates per tick, shares of actors, a mean latency, a mean profile cosine), plus the previous persistence count.
- **Base indicator to derived:** each indicator's last 24 values form its baseline, and the persistence counter carries the previous states.
- **Derived to statistical evidence:** each indicator is scored in baseline standard deviations, an evidence kind fires when any of its indicators is at least 2, and the mean of the positive scores is the severity, whose last 80 values are kept.
- **Evidence to precursor:** the severity history is tested for both variance and lag-1 autocorrelation being higher in its later half (critical slowing down), or for its largest value lying at least twice above a well-fitted log-rank tail (dragon-king outlier).
- **Precursor to RCT decision:** an assessment is an RCT when, with at least 24 events, three or more evidence kinds fire, one of them also fired 20 ticks earlier, half or more of the acting agents are in trouble, and either precursor holds.

## 21. Operational and early-warning extension (2026-10-12)

Code: `indicators.py` (registry, the five event-based values), `operations.py` (the state
snapshot), `monitor.py` (the three history-held values, direction, severity, learning, the quiet
rule). The notation of section 2 is kept. New symbols: $\Sigma_k$ is the read-only state snapshot
taken at $t_k$ (`operations.snapshot_state(eco)`); $\epsilon_{i,k} \in \{0, 1\}$ is the
evaluability flag of indicator $i$ at $k$ (`BehaviouralIndicators.evaluable`), 1 for the original
twelve always; $d_i \in \{\text{up}, \text{down}, \text{both}\}$ is the direction of indicator $i$
(`INDICATOR_META[name]["direction"]`); $\mathcal{N}$ is the set of indicator names, now
$\lvert \mathcal{N} \rvert = 20$ (`INDICATOR_NAMES`). A value with $\epsilon_{i,k} = 0$ is stored as
0.0 by convention and shown as "n/a"; it enters no baseline and has $z_{i,k} = 0$.

The observer property is unchanged: the snapshot is a set of attribute reads on `eco` at
assessment time, each wrapped in `try/except`, none of which calls a method with a side effect
(`Directory.may_send` is a pure check). A failed read gives None for that field and
$\epsilon_{i,k} = 0$ for every indicator that needed it.

### 21.1 The eight new indicators

Additional event topics used: $\Theta_{DROP} = \{\texttt{message\_dropped}\}$ (actor: sender),
$\Theta_{LATE} = \{\texttt{agent\_message\_received}\}$ with $\lambda(e) =$
`detail["late_by"]` $> 0$ (actor: sender, target: receiver), `van_departed` with
$\pi(e) =$ `detail["parcels"]`, `parcel_arrived`, `arrival_refused`, `task_completed`.

**$x_{13}$ communication failure rate [A], direction up, range $[0, 1]$, unit: share.**

$$
n^{att}_k = \lvert \mathcal{M}_k \rvert,\quad
n^{drop}_k = \lvert \{ e \in W_k : \theta(e) \in \Theta_{DROP} \} \rvert,\quad
n^{late}_k = \lvert \{ e \in W_k : \theta(e) \in \Theta_{LATE},\ \lambda(e) > 0 \} \rvert,
$$
$$
x_{13,k} = \min\Big(1,\ \frac{n^{drop}_k + n^{late}_k}{n^{att}_k}\Big), \qquad \epsilon_{13,k} = \mathbf{1}[n^{att}_k > 0].
\tag{I13}
$$

A dropped message has no late event, so each attempted message is counted at most once. The bus
logs the attempt at send and the drop at delivery one tick later, so at a window's edges a drop
can fall inside it while its send falls outside; the raw ratio can then exceed 1 by a few percent
under a total drop (seen: 1.067). The indicator is clamped to the range the design states and the
raw ratio is kept in `detail["delivery"]["raw_rate"]`.
`counts`: `attempted`, `delivered` $= \max(0, n^{att}_k - n^{drop}_k)$ (floored for the same window-edge reason as the clamp), `dropped`, `late`, `held_now`
(messages the bus holds at $t_k$, from $\Sigma_k$). Source: events; `held_now` from state.

**$x_{14}$ backlog growth [B], direction up, range $(-\infty, \infty)$, unit: parcels per tick.**
With $b_k =$ `len(eco.env.parcels)` read from $\Sigma_k$ (parcels inside the building):

$$
x_{14,k} = \frac{b_k - b_{k-1}}{E}, \qquad \epsilon_{14,k} = \mathbf{1}[k > 1 \wedge b_k \ne \text{None} \wedge b_{k-1} \ne \text{None}].
\tag{I14}
$$

$E = 20$ is `every`, the ticks between assessments. Detail: $b_k$, parcels by zone (by
`parcel.current_zone`, a parcel with no position under "carried", each parcel once), unfinished
tasks (`tasks.counts()` less COMPLETED, FAILED, CANCELLED), `increasing_for` (consecutive
assessments with $x_{14} > 0$, this one included), `acceleration` $= x_{14,k} - x_{14,k-1}$.
Source: state. Held by the monitor, since it needs $b_{k-1}$.

**$x_{15}$ task completion rate [A], direction down, range $[0, \infty)$, unit: parcels per tick.**

$$
x_{15,k} = \frac{1}{\Delta_k} \sum_{e \in W_k : \theta(e) = \texttt{van\_departed}} \pi(e), \qquad \epsilon_{15,k} = 1.
\tag{I15}
$$

Zero is a reading, not a missing one. Detail: `incoming_per_tick` $= (n^{arr}_k + n^{aref}_k) / \Delta_k$
with $n^{arr}_k$ the `parcel_arrived` and $n^{aref}_k$ the `arrival_refused` events,
`tasks_completed_per_tick` $= n^{done}_k / \Delta_k$ (`task_completed`), `completed_per_tick`
$= x_{15,k}$. Source: events.

**$x_{16}$ completion gap [A], direction up, range $(-\infty, \infty)$, unit: parcels per tick.**

$$
x_{16,k} = \frac{n^{arr}_k + n^{aref}_k}{\Delta_k} - x_{15,k}, \qquad \epsilon_{16,k} = 1.
\tag{I16}
$$

Demand that is not leaving. Source: events. Registered as an indicator of its own (the design
note keeps it in detail only) because the `throughput` evidence kind reads it.

**$x_{17}$ resource saturation [A], direction up, range $[0, 1]$, unit: share of capacity.** Five
categories $c \in \{$robots, charge\_points, routes, storage, dock$\}$, each with a utilisation
$u_{c,k} \in [0, 1]$ and an evaluability $\epsilon_{c,k}$, read from $\Sigma_k$:

| $c$ | $u_{c,k}$ | not evaluable when |
|---|---|---|
| robots | $1 - \lvert\texttt{fleet.available()}\rvert / \lvert\texttt{fleet}\rvert$ (the fleet's own `is_available`) | roster 0 or unreadable |
| charge\_points | occupied / points; with points $= 0$: 1 if any robot `needs_charge`, else 0 | unreadable |
| routes | (declared $-$ open) / declared, open $=$ routes with a van at the bay (`departures._bay`) | declared $= 0$ (value 0.0 by convention) or unreadable |
| storage | `storage.used / storage.capacity`, capped at 1 | capacity $= 0$ or unreadable |
| dock | parcels on the intake dock / `generator.max_on_dock`, capped at 1; "on the dock" is `parcels_in(INTAKE)`, which is the by-zone count of INTAKE above | cap $= 0$ or unreadable |

$$
x_{17,k} = \max_{c : \epsilon_{c,k} = 1} u_{c,k}, \qquad \epsilon_{17,k} = \mathbf{1}[\lvert\texttt{fleet}\rvert > 0 \wedge \exists c : \epsilon_{c,k} = 1].
\tag{I17}
$$

The aggregation is the bottleneck (the maximum); every category is recorded in
`detail["resources"]`. Source: state.

**$x_{18}$ dependency-graph divergence [B], direction up, range $[0, 1]$, unit: none.** Let
$\mathbf{w}_k$ be this window's edge-weight map, $\mathbf{w}_k(a, b) = \lvert\{ e \in \mathcal{M}_k :
\alpha(e) = a, \beta(e) = b \}\rvert$ over ordered pairs with both ends non-empty (the realised graph
(G1) with weights; `detail["edges"]`). Let $\mathcal{B}^{w}_k$ be the FIFO of the edge maps of the
windows the baseline learned from (21.4), capacity $B$, and

$$
\bar{\mathbf{w}}_k(a, b) = \frac{1}{\lvert \mathcal{B}^{w}_k \rvert} \sum_{\mathbf{w} \in \mathcal{B}^{w}_k} \mathbf{w}(a, b)
\quad (\text{an edge absent from a window weighs 0 there}),
$$
$$
J(\mathbf{u}, \mathbf{v}) = \frac{\sum_{(a,b) \in \mathrm{supp}\,\mathbf{u} \cup \mathrm{supp}\,\mathbf{v}} \min(\mathbf{u}(a,b), \mathbf{v}(a,b))}{\sum_{(a,b) \in \mathrm{supp}\,\mathbf{u} \cup \mathrm{supp}\,\mathbf{v}} \max(\mathbf{u}(a,b), \mathbf{v}(a,b))},
\qquad J := 1 \text{ when both sums are } 0,
$$
$$
x_{18,k} = 1 - J(\mathbf{w}_k, \bar{\mathbf{w}}_k), \qquad \epsilon_{18,k} = \mathbf{1}[\mathcal{B}^{w}_k \ne \emptyset].
\tag{I18}
$$

The weighted Jaccard similarity of the two maps. Detail, against the declared structure
$\mathcal{E}$ read from `eco.bus.directory` (every parent/child link both ways, plus, while the
roster has at most 40 agents, every ordered pair the directory's `may_send` allows; the facility
has 28, so the full allowed set is used): `unexpected` $= \mathrm{supp}\,\mathbf{w}_k \setminus
\mathcal{E}$, `missing` $= \{ (a,b) \in \mathcal{E} : \bar{\mathbf{w}}_k(a,b) > 0,\ \mathbf{w}_k(a,b) = 0 \}$,
`weight_change` $= \lVert \mathbf{w}_k - \bar{\mathbf{w}}_k \rVert_1 / \sum \bar{\mathbf{w}}_k$. The
directory is the declared graph; no second network representation is built. Source: events for
$\mathbf{w}_k$, state for $\mathcal{E}$. Held by the monitor, since it needs $\mathcal{B}^{w}_k$.

**$x_{19}$ activity synchronization [A], direction both, range $[-1, 1]$, unit: correlation.**
Let $\underline{t}_k = \min_{e \in W_k} \tau(e)$, $\overline{t}_k = \max_{e \in W_k} \tau(e)$,
$T_k = \overline{t}_k - \underline{t}_k + 1$, and for each acting agent $a \in \mathcal{A}^{act}_k$
the series $c_a(t) = \lvert \{ e \in W_k : \alpha(e) = a, \tau(e) = t \} \rvert$ for
$t = \underline{t}_k, \dots, \overline{t}_k$ (every event of $a$, messages included; zero on
ticks it was silent). With $r(\cdot, \cdot)$ the Pearson correlation, defined only when both
series have positive variance, and $\mathcal{P}_k$ the unordered pairs of acting agents for which
it is defined:

$$
x_{19,k} = \frac{1}{\lvert \mathcal{P}_k \rvert} \sum_{\{a, b\} \in \mathcal{P}_k} r(c_a, c_b), \qquad
\epsilon_{19,k} = \mathbf{1}\big[\lvert \mathcal{A}^{act}_k \rvert \ge 2 \ \wedge\ T_k \ge 4 \ \wedge\ \mathcal{P}_k \ne \emptyset\big].
\tag{I19}
$$

A pair with a flat series contributes nothing (its correlation is undefined, not zero). Source:
events. `MIN_SYNC_AGENTS` $= 2$, `SYNC_MIN_TICKS` $= 4$.

**$x_{20}$ tail deviation [B], direction up, range $[0, \infty)$, unit: ratio.** Three tail metrics
$m$, each a list of values $V_{m,k}$ from the window: task wait (the waits of (I8), created to
started, in ticks), message delay ($\lambda(e)$ over the late events of (I13)), zone backlog (the
by-zone parcel counts of (I14), from $\Sigma_k$). With the nearest-rank percentile
$q_p(V) = V_{(\lceil p \lvert V \rvert \rceil)}$ (sorted ascending, 1-based), $p = 0.95$ (`TAIL_P`),
$\mathcal{B}^{m}_k$ the FIFO of the past learned windows' $q_p(V_{m,j})$ (capacity $B$, a window with
$V_{m,j} = \emptyset$ adds nothing), and $\mathrm{med}$ the median:

$$
\rho_{m,k} = \frac{q_p(V_{m,k})}{\mathrm{med}(\mathcal{B}^{m}_k)}
\quad \text{defined when } V_{m,k} \ne \emptyset,\ \lvert \mathcal{B}^{m}_k \rvert \ge 4,\ \mathrm{med}(\mathcal{B}^{m}_k) > 0,
$$
$$
x_{20,k} = \max_{m : \rho_{m,k} \text{ defined}} \rho_{m,k}, \qquad \epsilon_{20,k} = \mathbf{1}[\exists m : \rho_{m,k} \text{ defined}].
\tag{I20}
$$

A metric whose baseline median is 0 while the window has values is recorded as "baseline zero"
and contributes no ratio. Detail per metric: $q_p(V_{m,k})$, $\mathrm{med}(\mathcal{B}^{m}_k)$,
$\rho_{m,k}$. `execution_latency_p95` $= q_p$ of the waits is recorded in detail beside (I8).
`TAIL_MIN_BASELINE` $= 4$. Held by the monitor, since it needs $\mathcal{B}^{m}_k$.

**Guardrail split (I5 unchanged).** `counts["refusals"]` $= n^{ref}_k$ is unchanged; it is now
also recorded as four parts that add up to it: `gate_rejections` ($\mathrm{gov}(e)$),
`intake_rejections` (`parcel_refused`, `arrival_refused`, `parcel_returned`),
`resource_denials` (`charge_refused`, `charge_unavailable`, `storage_refused`),
`message_refusals` (`message_refused`). Every member of $\Theta_{REF}$ is in exactly one part.

**Registry.** `INDICATORS` stays a tuple of `(name, about)` pairs; `INDICATOR_META[name]` carries
`kind` ("base" for $x_{1..10}, x_{13}, x_{15}, x_{16}, x_{17}, x_{19}$; "derived" for
$x_{11}, x_{12}, x_{14}, x_{18}, x_{20}$), `direction` and `about`. The `about` text of $x_9$ now
says it is the active-agent fraction and not a coupling measure, and that of $x_{10}$ that a
change away from normal similarity in either direction is the signal.

### 21.2 Direction-aware evidence [D]

Replaces the evidence threshold of section 10 and (K) of section 11. The kinds are now twelve
(`EVIDENCE`), each indicator with its direction $d_i$:

| Kind $g$ | $G_g$ (direction) |
|---|---|
| refusal | $x_5$ (up) |
| retry | $x_4$ (up) |
| congestion | $x_8$ (up), $x_7$ (up), $x_{20}$ (up) |
| chatter | $x_1$ (both), $x_3$ (up), $x_6$ (up), $x_2$ (both) |
| herding | $x_{10}$ (both), $x_9$ (both) |
| spread | $x_{12}$ (up) |
| delivery | $x_{13}$ (up) |
| backlog | $x_{14}$ (up) |
| throughput | $x_{15}$ (down), $x_{16}$ (up) |
| saturation | $x_{17}$ (up) |
| structure | $x_{18}$ (up) |
| synchrony | $x_{19}$ (both) |

$\mathcal{G}_{op} = \{$delivery, backlog, throughput, saturation$\}$ (`OPERATIONAL_KINDS`) and
$\mathcal{G}_{beh}$ the other eight (`BEHAVIOURAL_KINDS`). The tail statistic $x_{20}$ belongs to
congestion and not to a kind of its own: its task-wait metric is the 95th percentile of the same
sample whose mean is $x_8$, and its other two metrics are tails of what delivery and backlog
already read, so a separate kind would count one queue twice (found in validation on Normal,
seed 1, ticks 1481 to 1501, where congestion and a separate tail kind made UNSTABLE out of a
single slow queue). The design note of 2026-10-12 lists tail as its own kind; this is the
documented correction. The deviation of indicator $i$ at $k$:

$$
\delta_{i,k} = \begin{cases}
\text{up} & d_i \in \{\text{up}, \text{both}\} \wedge z_{i,k} \ge z^{*} \\
\text{down} & d_i \in \{\text{down}, \text{both}\} \wedge z_{i,k} \le -z^{*} \\
\text{none} & \text{otherwise}
\end{cases}
\tag{DIR}
$$

**Sign of $z$ on a flat baseline.** `zscore` is unchanged and still returns $+3$ on the flat
branch of (Z) whichever way the value moved. For (DIR) to be meaningful the sign has to be that of
the move, so the monitor takes it from the raw difference on that branch
(`DKRMM._signed_z`): $z_{i,k} := -3$ when $n \ge 4$, $\sigma \le 10^{-9}$ and $x_{i,k} < \mu$. On
every other branch the sign of (Z) already is the sign of $x_{i,k} - \mu$, so nothing else
changes. Consequence for the original twelve: a fall from a dead-flat baseline no longer counts as
"up" evidence (before, a refusal rate that dropped from a flat non-zero baseline to 0 read $+3$
and fed the refusal kind).

**Corroborated fall.** For $i \in \{x_1, x_2, x_9, x_{10}\}$ (`CORROBORATED_FALL`),
$\delta_{i,k} = \text{down}$ counts only when some operational kind is present in the same
window; the operational kinds are read first for that reason. A quiet facility with normal
output is not deviating, and fewer agents active or agents looking less alike is what a lull
looks like, not herding (found in validation on Normal, seed 1, tick 1381, where $x_9$ and
$x_{10}$ both fell in a lull and read as herding; the design note named only $x_1$ and $x_2$).
A rise on any of the four always counts.

$$
\mathcal{K}_k = \{ g : \exists i \in G_g,\ \delta_{i,k} \ne \text{none} \ \wedge\ \neg(i \in \{x_1, x_2, x_9, x_{10}\} \wedge \delta_{i,k} = \text{down} \wedge \mathcal{K}_k \cap \mathcal{G}_{op} = \emptyset) \},
\tag{K'}
$$

subject to the quiet rule of 21.5. The evidence line for a hit keeps its format,
"`name` at $\pm z$ standard deviations". The assessment records, per indicator, $\epsilon_{i,k}$,
$\delta_{i,k}$, the kind it fed (`in_evidence`) and the baseline mean $\mu(H_{i,k})$ when
$n \ge 4$ (`baseline`). (RULE), (RCT), (P) and (REC) are unchanged and read $\mathcal{K}_k$ from
(K'); no threshold declares UNSTABLE or RCT from one indicator.

### 21.3 Directional severity [C, aggregate]

Old (SEV), section 11, and new, side by side:

$$
s_k^{old} = \frac{1}{12} \sum_{i=1}^{12} \max(0, z_{i,k}),
\qquad
s_k = \frac{1}{\lvert \mathcal{N} \rvert} \sum_{i \in \mathcal{N} : \epsilon_{i,k} = 1} \phi_i(z_{i,k}),
\quad
\phi_i(z) = \begin{cases} \max(0, z) & d_i = \text{up} \\ \max(0, -z) & d_i = \text{down} \\ \lvert z \rvert & d_i = \text{both} \end{cases}
\tag{SEV'}
$$

with $\lvert \mathcal{N} \rvert = 20$. The divisor is the number of indicator names, evaluable or
not, so the scale stays comparable between windows in which a different number could be read
(a not-evaluable indicator has $z = 0$ and would add nothing either way). For the original twelve
under "up" the summand is unchanged; the two-sided ones ($x_1, x_2, x_9, x_{10}$) now contribute a
fall as well. The severity buffer, (CSD) and (DK) are unchanged and run on $s_k$.
Test: `test_severity_is_the_mean_positive_z_over_the_twelve` (updated: $(3 + 3) / 20$).

### 21.4 Baseline learning [B]

Replaces the unconditional append of (H), section 10. With $\Lambda = \{$STABLE, DEVIATING,
RECOVERY$\}$ (`BASELINE_LEARNS_FROM`) and $\omega_k$ the final state of assessment $k$:

$$
H_{i,k+1} = \begin{cases}
\text{last } B \text{ of } (H_{i,k}, x_{i,k}) & \epsilon_{i,k} = 1 \ \wedge\ \big(\omega_k \in \Lambda \ \vee\ \lvert H_{i,k} \rvert < B\big) \\
H_{i,k} & \text{otherwise.}
\end{cases}
\tag{H'}
$$

$z_{i,k}$ is still computed against $H_{i,k}$ before the append, and `_classify` reads no
baseline, so moving the append after the classification changes no verdict. The same rule governs
$\mathcal{B}^{w}$ (edge maps) and $\mathcal{B}^{m}$ (tail p95s). The second disjunct is the one
reading the design note leaves open: until a baseline holds its full $B$ windows it learns from
every window whatever the state. Without it the monitor froze on five start-up windows (Normal,
seed 1, rules: UNSTABLE from tick 101 to the end of a 500-tick run, because the steady state
differs from the first hundred ticks and no later window was ever allowed in). A handful of
start-up windows is not a normal worth protecting. Once formed, a baseline does not learn from a
window the monitor called UNSTABLE or RCT.

### 21.5 Narrowed activity rule [D]

Replaces the first branch of (RULE). With $N_k < N^{*} = 24$:

$$
\mathcal{K}_k := \mathcal{K}_k \cap \mathcal{G}_{op}, \qquad \text{not\_evaluated}_k = \mathcal{G}_{beh},
\tag{Q}
$$

and the evidence list begins with "only $N_k$ events in the window; behavioural kinds not
evaluated". If $\mathcal{K}_k = \emptyset$ the state is STABLE as before; otherwise the remaining
branches of (RULE) run on the operational kinds alone. The operational kinds come from parcel
events and the state of the building, not from chatter, so a facility that has gone silent while
its dock fills is no longer "too quiet to say". $\texttt{enough\_activity}_k$ is unchanged.

### 21.6 Propagation extension [A]

Replaces (S) for $\mathcal{T}_k$; (I12) is unchanged:

$$
\mathcal{T}_k = \{\alpha(e) : e \in W_k,\ \alpha(e) \ne \texttt{""},\ \theta(e) \in \Theta_{TR} \vee \mathrm{gov}(e)\}
\ \cup\ \{\alpha(e) : e \in W_k,\ \theta(e) \in \Theta_{DROP}\}
\ \cup\ \{\beta(e) : e \in W_k,\ \theta(e) \in \Theta_{LATE},\ \lambda(e) > 0\}.
\tag{S'}
$$

The sender of a dropped message and the receiver of a late one are affected. `message_dropped`
is not a message topic, so its actor is also in $\mathcal{A}^{act}_k$ by the unchanged rule for
acting agents; a late receiver is in $\mathcal{A}^{act}_k$ only if it emitted a non-message event
of its own, and (I12) still divides $\lvert \mathcal{T}_k \cap \mathcal{A}^{act}_k \rvert$ by
$\lvert \mathcal{A}^{act}_k \rvert$, so a receiver that only waited does not count. The inclusion
$\mathcal{T}_k \subseteq \mathcal{A}^{act}_k$ of section 7 no longer holds in general.
`test_the_twelve_indicators_on_a_hand_built_window` needed no change: its window has no dropped or
late message.

### 21.7 New constants

| Constant | Value | Code | Role |
|---|---|---|---|
| | 2 | `monitor.MIN_SYNC_AGENTS` | fewest acting agents for (I19) |
| | 4 | `indicators.SYNC_MIN_TICKS` | fewest ticks spanned for (I19) |
| $p$ | 0.95 | `monitor.TAIL_P` | percentile of (I20) |
| | 4 | `monitor.TAIL_MIN_BASELINE` | fewest baseline windows for a ratio in (I20) |
| $\Lambda$ | {STABLE, DEVIATING, RECOVERY} | `monitor.BASELINE_LEARNS_FROM` | states a formed baseline learns from (H') |
| $\mathcal{G}_{op}$ | 4 kinds | `monitor.OPERATIONAL_KINDS` | kinds read under the quiet rule (Q) |
| $\mathcal{G}_{beh}$ | 8 kinds | `monitor.BEHAVIOURAL_KINDS` | kinds skipped under the quiet rule (Q) |
| | $\{x_1, x_2, x_9, x_{10}\}$ | `monitor.CORROBORATED_FALL` | falls that need an operational kind (K') |
| | 40 | `operations.DECLARED_EDGES_FULL_UP_TO` | roster size up to which $\mathcal{E}$ uses `may_send` |
| $E$ | 20 | `DKRMM.every` | divisor of (I14), the existing `EVERY` |

Every constant of section 2.2 keeps its value.

### 21.8 Not implemented

- No threshold declares UNSTABLE or RCT from a single indicator; a delivery failure of 1.0 is one
  kind of evidence and enters (RULE) like any other.
- No null distribution, bootstrap, p-value or significance level: $z$ and the ratios of (I20) are
  still measured against each indicator's own empirical past.
- No second network representation: the declared structure $\mathcal{E}$ is read from the agent
  directory as it is; (I18) compares realised windows with realised baseline windows and reports
  $\mathcal{E}$ only in the detail.
- No automatic action on any state; the human gate of section 15.4 is unchanged.
- No change to the simulation: the monitor reads `eco` at assessment time and writes nothing
  to it, emits no event and sends no message.
