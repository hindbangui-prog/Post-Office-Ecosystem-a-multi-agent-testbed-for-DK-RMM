# DK-RMM sequence diagrams

Five sequence diagrams of one DK-RMM assessment, one per outcome: STABLE, DEVIATING, UNSTABLE, RCT,
and the dragon-king flag on the severity series (an extreme value of DK-RMM's own severity score).
Every message in the diagrams is a call or a data flow that exists in the code; the conditions are
the rules of `DKRMM._classify` (`post_office/dkrmm/monitor.py`) and the symbols are those of
[dkrmm-mathematics.md](dkrmm-mathematics.md), where each formula is derived and referenced.

The participants are the same in every diagram:

| Participant | Code | Role |
|---|---|---|
| SimulationRunner | `api/runner.py` | steps the run once per tick and then asks the monitor for an assessment |
| PostOfficeEcosystem | `simulation/ecosystem.py` | the simulation; emits every event through the logger |
| EventLogger | `communication/events.py` | records each event and calls its subscribers |
| DKRMM | `dkrmm/monitor.py` | the monitor: buffers events, assesses every 20 ticks |
| indicators | `dkrmm/indicators.py` | `compute_indicators`: the twelve indicators of one window |
| signals | `dkrmm/signals.py` | `zscore`, `precursors` (critical slowing down), `dragon_king` |
| RunRecorder | `observability/run_record.py` | writes the run's DK-RMM record and one file per RCT (when recording is on) |
| Operator | the live page and the API | reads the assessment; validates or dismisses it |

Every assessment starts the same way (steps 1 to 11 of each diagram): the run steps, every event
reaches the monitor through the logger, and when 20 ticks have passed since the last assessment the
monitor reads the window $W_k$ of the last 60 ticks, computes the twelve indicators, scores each
against its own last 24 values ($z_{i,k}$), and forms the severity $s_k$ (mean of the positive scores).
The diagrams differ in what `_classify` finds. DK-RMM never sends anything back to the simulation:
all its arrows point away from it, towards the recorder and the operator.

## 1. STABLE

```mermaid
sequenceDiagram
  autonumber
  participant RN as SimulationRunner
  participant ECO as PostOfficeEcosystem
  participant LOG as EventLogger
  participant MON as DKRMM
  participant IND as indicators
  participant SIG as signals
  participant REC as RunRecorder
  participant OP as Operator

  RN->>ECO: step()
  loop every event of the tick
    ECO->>LOG: emit(category, topic, actor, target, detail)
    LOG->>MON: observe(event)
    Note right of MON: append to buffer (last 20 000 events)<br/>task_created: remember C[task] = tick
  end
  RN->>MON: tick()
  Note over MON: assessment due: t - t(k-1) >= 20<br/>(otherwise tick() returns None)
  MON->>MON: _window(t): events with t-60 <= tick <= t
  MON->>IND: compute_indicators(W_k, span, roster, C, persistence)
  IND-->>MON: x_1 .. x_12
  loop each of the 12 indicators
    MON->>SIG: zscore(x_i, last 24 values of x_i)
    SIG-->>MON: z_i
  end
  MON->>MON: append x_i to baselines, then s_k = mean of max(0, z_i), then append s_k
  MON->>MON: _classify(x, z)
  alt fewer than 24 events in the window
    MON->>MON: STABLE, kinds = [] ("too little happening to read")
  else 24 events or more
    MON->>MON: kinds = groups with some z_i >= 2  ->  none
    MON->>SIG: dragon_king(severity history), precursors(severity history)
    SIG-->>MON: computed, but no rule can fire without a kind
    MON->>MON: STABLE
  end
  MON->>MON: persistence = 0, then previous kinds = []
  alt previous state was DEVIATING, UNSTABLE or RCT
    MON->>MON: report RECOVERY ("back to baseline from ...")
  else previous state was STABLE or RECOVERY
    MON->>MON: report STABLE
  end
  MON->>MON: Assessment(status DISCOVERED) appended to history
  MON-->>RN: assessment
  RN->>REC: update(monitor, eco)
  REC->>REC: rewrite dkrmm/run.json (no RCT file)
  OP->>RN: GET /dkrmm/state
  RN-->>OP: STABLE, severity, z-scores, indicators
```

![STABLE sequence](img/dkrmm-seq-1-stable.svg)

STABLE is the outcome when the window holds fewer than 24 events (nothing is read) or when no
indicator stands two baseline standard deviations above its mean, so no evidence kind fires. The
persistence counter returns to 0. If the previous assessment was DEVIATING, UNSTABLE or RCT, the
same computed STABLE is reported as RECOVERY.

## 2. DEVIATING

```mermaid
sequenceDiagram
  autonumber
  participant RN as SimulationRunner
  participant ECO as PostOfficeEcosystem
  participant LOG as EventLogger
  participant MON as DKRMM
  participant IND as indicators
  participant SIG as signals
  participant REC as RunRecorder
  participant OP as Operator

  RN->>ECO: step()
  loop every event of the tick
    ECO->>LOG: emit(category, topic, actor, target, detail)
    LOG->>MON: observe(event)
  end
  RN->>MON: tick()
  Note over MON: assessment due (t - t(k-1) >= 20)
  MON->>MON: _window(t): events with t-60 <= tick <= t
  MON->>IND: compute_indicators(W_k, span, roster, C, persistence)
  IND-->>MON: x_1 .. x_12
  loop each of the 12 indicators
    MON->>SIG: zscore(x_i, last 24 values of x_i)
    SIG-->>MON: z_i
  end
  MON->>MON: append to baselines, then severity s_k, then append s_k
  MON->>MON: _classify(x, z), 24 events or more
  MON->>MON: kinds = groups with some z_i >= 2<br/>e.g. guardrail_events z = 2.6 -> {refusal}
  MON->>MON: confirmed = kinds also fired at k-1 -> none
  MON->>SIG: dragon_king(severity history), precursors(severity history)
  SIG-->>MON: flags (not decisive here)
  MON->>MON: RCT? needs >= 3 kinds -> no
  MON->>MON: UNSTABLE? needs >= 2 confirmed kinds -> no
  MON->>MON: UNSTABLE? needs persistence before this assessment >= 3 -> no
  MON->>MON: at least one kind -> DEVIATING
  MON->>MON: persistence = persistence + 1, then previous kinds = {refusal}
  MON->>MON: Assessment(DEVIATING, DISCOVERED, evidence "guardrail events at +2.6 standard deviations")
  MON-->>RN: assessment
  RN->>REC: update(monitor, eco)
  REC->>REC: rewrite dkrmm/run.json
  OP->>RN: GET /dkrmm/state
  RN-->>OP: DEVIATING, kinds, evidence lines
```

![DEVIATING sequence](img/dkrmm-seq-2-deviating.svg)

DEVIATING is one or more evidence kinds firing in a window with enough activity, with none of the
stronger rules satisfied: not three kinds with confirmation, spread and a statistic (RCT); not two
kinds that also fired in the previous assessment; and not a deviation that has already lasted three
assessments. The persistence counter increases by one, and the kinds are remembered so the next
assessment can confirm them.

## 3. UNSTABLE

```mermaid
sequenceDiagram
  autonumber
  participant RN as SimulationRunner
  participant ECO as PostOfficeEcosystem
  participant LOG as EventLogger
  participant MON as DKRMM
  participant IND as indicators
  participant SIG as signals
  participant REC as RunRecorder
  participant OP as Operator

  RN->>ECO: step()
  loop every event of the tick
    ECO->>LOG: emit(category, topic, actor, target, detail)
    LOG->>MON: observe(event)
  end
  RN->>MON: tick()
  Note over MON: assessment due (t - t(k-1) >= 20)
  MON->>MON: _window(t): events with t-60 <= tick <= t
  MON->>IND: compute_indicators(W_k, span, roster, C, persistence)
  IND-->>MON: x_1 .. x_12
  loop each of the 12 indicators
    MON->>SIG: zscore(x_i, last 24 values of x_i)
    SIG-->>MON: z_i
  end
  MON->>MON: append to baselines, then severity s_k, then append s_k
  MON->>MON: _classify(x, z), 24 events or more
  MON->>MON: kinds = groups with some z_i >= 2
  MON->>MON: confirmed = kinds that also fired at k-1
  MON->>SIG: dragon_king(severity history), precursors(severity history)
  SIG-->>MON: dragon flag, slowing-down flag
  MON->>MON: RCT? fails: fewer than 3 kinds, or propagation < 0.5,<br/>or neither statistic, or nothing confirmed
  alt two or more confirmed kinds
    MON->>MON: e.g. {refusal, retry} at k-1 and at k -> UNSTABLE<br/>("2 independent kinds of evidence, each holding from the window before")
  else at least one kind and persistence before this assessment >= 3
    MON->>MON: UNSTABLE ("off baseline for 3 windows running")
  end
  MON->>MON: persistence = persistence + 1, then previous kinds = kinds
  MON->>MON: Assessment(UNSTABLE, DISCOVERED) appended to history
  MON-->>RN: assessment
  RN->>REC: update(monitor, eco)
  REC->>REC: rewrite dkrmm/run.json
  OP->>RN: GET /dkrmm/state
  RN-->>OP: UNSTABLE, kinds, evidence lines
```

![UNSTABLE sequence](img/dkrmm-seq-3-unstable.svg)

UNSTABLE has two routes. Either at least two kinds of evidence fire in this window and also fired in
the previous one, or at least one kind fires after three or more consecutive assessments that were
not STABLE. The RCT rule is checked first, so UNSTABLE means the RCT conditions were not all met.

## 4. RCT (Runtime Critical Transition)

```mermaid
sequenceDiagram
  autonumber
  participant RN as SimulationRunner
  participant ECO as PostOfficeEcosystem
  participant LOG as EventLogger
  participant MON as DKRMM
  participant IND as indicators
  participant SIG as signals
  participant REC as RunRecorder
  participant OP as Operator

  RN->>ECO: step()
  loop every event of the tick
    ECO->>LOG: emit(category, topic, actor, target, detail)
    LOG->>MON: observe(event)
  end
  RN->>MON: tick()
  Note over MON: assessment due (t - t(k-1) >= 20)
  MON->>MON: _window(t): events with t-60 <= tick <= t
  MON->>IND: compute_indicators(W_k, span, roster, C, persistence)
  IND-->>MON: x_1 .. x_12, including propagation x_12 = share of acting agents in trouble
  loop each of the 12 indicators
    MON->>SIG: zscore(x_i, last 24 values of x_i)
    SIG-->>MON: z_i
  end
  MON->>MON: append to baselines, then severity s_k, then append s_k
  MON->>MON: _classify(x, z), 24 events or more
  MON->>MON: kinds >= 3, e.g. {refusal, congestion, spread}
  MON->>MON: confirmed >= 1, e.g. refusal also fired at k-1
  MON->>MON: propagation >= 0.5
  MON->>SIG: precursors(severity history)
  SIG-->>MON: slowing down = variance and lag-1 autocorrelation<br/>higher in the later half (needs >= 12 points)
  MON->>SIG: dragon_king(severity history)
  SIG-->>MON: dragon flag = largest severity >= 2x tail prediction, fit R^2 > 0.5
  alt dragon flag
    MON->>MON: RCT, evidence "... and an extreme above what the tail predicts"
  else slowing-down flag
    MON->>MON: RCT, evidence "... and variance and memory both climbing"
  end
  MON->>MON: persistence = persistence + 1, then previous kinds = kinds
  MON->>MON: Assessment(RCT, DISCOVERED) appended to history
  MON-->>RN: assessment
  RN->>REC: update(monitor, eco)
  REC->>REC: new RCT reading: stamp detected_at,<br/>explain(events, tick), write rct/run/tick.json
  REC->>REC: rewrite dkrmm/run.json
  OP->>RN: GET /dkrmm/rct-log, GET /dkrmm/rct-log/item
  RN-->>OP: the RCT with its cause as saved at detection
  OP->>MON: POST /dkrmm/validate {by, note} (or dismiss): the API handler calls validate(by, note)
  MON-->>OP: status VALIDATED (the state stays RCT)
  RN->>REC: record_gate(): write(monitor), the saved RCT records the verdict
  Note over MON,ECO: no arrow goes from DKRMM to the simulation: the monitor observes only
```

![RCT sequence](img/dkrmm-seq-4-rct.svg)

An RCT requires all four conditions in one assessment with enough activity:
- at least three evidence kinds fire;
- at least one of them also fired in the previous assessment;
- at least half of the acting agents had a trouble event;
- the severity history shows either critical slowing down or a dragon-king outlier.

When recording is on, the recorder saves the RCT with its explanation at the moment it is first seen. A person then validates or dismisses it; the verdict changes the discovery status, not the state.

## 5. Dragon-king flag (extreme severity)

```mermaid
sequenceDiagram
  autonumber
  participant RN as SimulationRunner
  participant MON as DKRMM
  participant SIG as signals
  participant REC as RunRecorder
  participant OP as Operator

  RN->>MON: tick()
  Note over MON: assessment due: window, indicators and z-scores<br/>as in diagrams 1 to 4
  MON->>MON: s_k = mean of max(0, z_i), then append to severity history (last 80)
  MON->>SIG: dragon_king(severity history)
  SIG->>SIG: V = severities > 0, largest first
  alt fewer than 12 positive severities
    SIG-->>MON: enough = false, flag = false
  else 12 or more
    SIG->>SIG: tail = V_1 .. V_12, V_1 held out
    SIG->>SIG: least squares: ln V_r = a + b ln r over ranks r = 2..12
    SIG->>SIG: expected = e^a (the line at rank 1)<br/>ratio = V_1 / expected and fit = R^2 of the line
    SIG-->>MON: flag = ratio >= 2 and fit > 0.5
  end
  MON->>MON: _classify(x, z)
  alt flag and >= 3 kinds and >= 1 confirmed and propagation >= 0.5
    MON->>MON: RCT, evidence "an extreme above what the tail predicts"
  else flag, but another RCT condition fails
    MON->>MON: state from the other rules (STABLE, DEVIATING or UNSTABLE)
  else no flag
    MON->>MON: RCT only if the slowing-down flag holds instead
  end
  MON->>MON: Assessment.dragon = {ratio, observed, expected, fit, flag}
  MON-->>RN: assessment
  RN->>REC: update(monitor, eco): the flag is kept in the record<br/>(state series and the timeline's first_dragon_flag)
  OP->>RN: GET /dkrmm/state
  RN-->>OP: dragon reading shown beside the state
  Note over MON,SIG: the extreme is in DK-RMM's severity history, not a measured event of the facility.<br/>The flag is not a state and not an RCT on its own.
```

![Dragon-king sequence](img/dkrmm-seq-5-dragon-king.svg)

The dragon-king test asks whether the largest severity in the monitor's history (last 80 assessments) sits
at least twice above what a straight line through the next eleven largest severities, on log rank against
log value, predicts for rank 1, and whether that line fits well. It needs at least 12 positive severities,
so it cannot fire before the 16th assessment. The flag is reported with every assessment. On its own it
is not a state: it contributes to an RCT only together with three evidence kinds, a confirmed kind and
spread across at least half of the acting agents, and it is one of two alternatives (the other is
critical slowing down). In the terms of dragon-king theory, the flag marks an extreme value that the
ordinary tail of the severity distribution does not explain; the code does not test whether such an
extreme corresponds to an extreme event of the facility itself.
