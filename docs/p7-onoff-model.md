# P7-ONOFF-MODEL: the ON-OFF misbehaviour on rules-first, model-when-insufficient experts

The seventh study scenario of the live page (`post_office/stress/onoff_model.py`,
preset `p7-onoff-model`, label "ON-OFF, model" (since 2026-10-23;
before that "Phase 7 · ON–OFF Agent Misbehaviour · rules first, model when insufficient
· CrewAI · Ollama/<model>")) is the P7-ONOFF configuration
(`docs/p7-onoff.md`) run on the experts as the app normally runs them with the
model: the Python rule answers first and, when it says it is insufficient, the
expert consults the model. It is added as a scenario beside `p7-onoff`; the Normal
scenario, the C2-NEAR conditions, the five collapse scenarios, `p7-onoff` itself,
DK-RMM and everything under `results/` are what they were.

## 1. What is the same and what differs

Everything frozen is imported from `onoff_attack`, not copied: the four ON phases
(1200 to 1500, 1800 to 2200, 2500 to 3000, 3300 to 3800) and 300 ticks OFF after
each, the displacement (ROUTING answers WAIT to every blocked robot; SCHEDULING
gives every errand the lowest-battery able robot and starts the non-urgent task
with the most slack), the hospital consignment of 20 urgent parcels for HRADEC
between 1400 and 3400, the horizon 4400, the seeds of the picker and the
demonstration seed 11977. The configuration is `normal_config()`, the same
dictionary. The arrivals and the displacement are installed by the same two
seams at construction.

The one difference is the path a targeted decision takes before the ON-phase
displacement or the OFF-phase action. On `p7-onoff` ("ON-OFF, rules only", which runs
every expert on its rules whatever mode the app is in) the rule's answer is
the decision. Here the project's own decision path runs
unchanged (`agents/base.py`): the rule answers first; if a trigger says the rule
is insufficient (for ROUTING's `resolve_block`: still blocked after six ticks or
more, recorded as the reason `failed`; an expensive detour or two goals at odds,
`conflict`; for SCHEDULING: `contention` among claimants and its peer conditions)
the expert consults the model through CrewAI and the consultation service, the
gate validates the answer, and the recorded decision is what the ON phase
displaces or the OFF phase acts on. The Phase 7 confirmation ran on rules alone,
so no frozen artifacts exist for this path: nothing is replayed, nothing is
claimed to be reproduced, and every run shows its own outcome, which will differ
from one run to the next with the model's answers.

The preset needs the experts on the model. Chosen in an app served with `--rules`
it is refused with a 400 and the message names `p7-onoff` as the rules-only
scenario, as the C2 condition of C2-NEAR is refused; the run goes on as it was.

## 2. What the page shows

The strip, the ON bands, the DK-RMM row, the DK alert and the ON–OFF tab are the
ones `p7-onoff` has. Two cards are added to the tab on this preset only.

**The model's part.** The targeted decisions of ROUTING (`resolve_block`) and
SCHEDULING (`choose_robot`, `choose_next_task`) counted per phase (before the
window, ON 1, OFF 1, ..., ON 4, after the window) by the path they took: answered
by a rule, sent to the model, and of those accepted at the gate, rejected, or
with nothing usable (the rule answering after both), displaced in ON phases, and
the raw model calls; the triggers that sent a decision to the model; and the
blocked streaks ROUTING was asked about, each with its answers by path and the
last answer before the block cleared. The last answer is reported as what
ROUTING said, not as proof that it cleared the block: the other robot may have
moved. Every figure is a count of recorded `decision`, displaced-decision and
`llm_call` events of this run.

**Beside the rules-only run.** For the six seeds of the picker, this run's trap,
impact and DK-RMM figures next to those of the `p7-onoff` preset on the same seed
at its horizon, from `post_office/stress/p7_rules_reference.json`. The file is
computed by `tools/p7_rules_reference.py` from the existing preset on the live
path with every expert on its rules; the runs are deterministic in the seed and
not new experiments, and seed 11977's event stream is checked against the frozen
Phase 7 confirmation run (`FROZEN_EVENTS_SHA256_4400`). A seed outside the file
has no reference and the card says so. The two columns are two runs of one seed,
not a verdict.

Switching between `p7-onoff` and `p7-onoff-model` keeps the seed, so the two can
be run on the same seed in turn; entering either from Normal starts on 11977.

A note on the picker's labels: they are the Phase 7 confirmation's classification
of the seeds (its trap is two or more robots without an errand head to head). The
page's own definition, a robot BLOCKED for 300 consecutive ticks, is wider: on
seed 12057 ("not trapped (median run)") the rules-only run shows R5 blocked for
330 ticks in temporary storage, with an errand, from 2672 to 3002, and the page
reports it as a trap that cleared. Both statements are true of that run.

## 3. Running it

```
.venv\Scripts\python main.py --api          (the experts on the model; Ollama running)
```

choose the scenario in the selector (seed 11977), press Start; the run ends at tick
4400. To compare with the rules-only path on the same seed, choose `p7-onoff` ("Only
Rules") in the same app: it runs every expert on its rules whatever mode the app
is in, keeps the seed, and reproduces the frozen run on 11977; its figures at the
horizon are also the reference column of this preset's tab.

## 4. Checks made when the scenario was added

The ten existing presets are unchanged: the event streams, floor frames, summaries
and study status of `default` (seeds 1 and 11, 600 ticks), `c2near-n` and
`c2near-c0` (seed 11, 900), `ms-drop`, `ms-delay`, `cs-starve`, `cs-partition`
(seed 11, 800), `ms-stall` (seed 13, 2200) and `p7-onoff` (seed 11977, 1700) are
identical before and after the change. `tests/test_p7_onoff_model.py` (7 tests)
checks the registration, the refusal on a rules-only runner, a run on the test
suite's fake Ollama with the model's part counted consistently, the seed
behaviour, the reference file and the page; the six files that count the
scenario options are updated for the eleventh. Model-enabled runs of this scenario
on the real model were not made here; the page shows whatever they show.
