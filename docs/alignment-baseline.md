# Behavioural alignment baseline

Prototype II copies the source's simulator, rules and DK-RMM and replaces only the model
layer. On the rules path nothing should therefore change: the same seed and the same
configuration must produce the same world, tick for tick, and DK-RMM must read it the same
way. `tests/test_normal_alignment.py` checks this against a baseline generated from the
source package itself, `tests/data/normal_baseline_filtered.json`.

## Why the baseline is filtered

The source's own guard, `tests/data/normal_baseline.json`, hashes the complete event stream
and the complete configuration. Some rows of that stream exist only because of the source's
model implementation, and Prototype II has its own rows of the same kind instead, so a
byte-identical event hash is impossible by construction and is not required.
`tools/normal_fingerprint.py` therefore applies one filter, `STRIP`, identically to both
sides before hashing. It is, verbatim:

```python
STRIP = {
    "topics": {"llm_async", "discussions", "interception", "llm"},
    "config_keys": {"llm_async", "llm_deterministic", "llm_max_pending", "llm_timeout_s",
                    "llm_deadline_ticks", "llm_det_latency_ticks", "discussions",
                    "discussion_calls", "discussion_deadline_ticks", "discussion_max_open",
                    "discussion_bias", "perturbations", "interceptors"},
    "side_effects": ["seq renumbered", "events counters netted"],
}
```

Rows whose topic is in `topics` are dropped. The keys in `config_keys` are pruned from
`simulation_started.detail.config`, which is where the ecosystem echoes the configuration it
was built with (`dict(self.config)` in `start()` on both sides). Every remaining row also
loses `wall_clock`, which is the time of day, and its top-level `run_id`, which names the run
rather than anything that happened in it. Only the top-level key is removed:
`simulation_started.detail.run_id` stays in the compared stream, which is sound because both
sides build every run with the same run id (`fp-<name>`, below).

The runtime communication taxonomy ([events.md](events.md)) added two top-level keys to every
event, `interaction_type` and `channel`, and the detail key `in_reply_to` to the bus's
carried messages, none of which the source ever wrote. `filter_rows` removes them from every
row on both sides, the way it removes `wall_clock` and `run_id`, through the two constants
`STAMP_KEYS` and `STAMP_DETAIL_KEYS` that sit beside `STRIP` in the tool rather than inside
it. They are kept outside `STRIP` because the baseline file records `STRIP` in its provenance
block and `test_the_baseline_records_its_provenance_and_filter` compares the two, so the
recorded `strip` and `tests/data/normal_baseline_filtered.json` are unchanged and were not
regenerated; the baseline therefore does not itself say that the stamp is stripped, and this
paragraph does. The four runs still match with the stamp in place.

| Item | Kind | Side | Why it is filtered |
|---|---|---|---|
| `llm_async` | topic | source | Start-up notice of the source's asynchronous model dispatcher, which Prototype II does not have. |
| `discussions` | topic | source | Start-up notice of the source's expert discussion mechanism, which Prototype II replaces with synchronous consultation. |
| `interception` | topic | Prototype II | Start-up notice that the (inert) interception layer has nothing active. |
| `llm` | topic | Prototype II | Notice of the model layer, emitted once that layer is installed. |
| `llm_async` | config key | source | Switch for the asynchronous dispatcher, set by the source app's `interactive_config`. |
| `llm_deterministic` | config key | source | Dispatcher option: model answers on a fixed logical schedule. |
| `llm_max_pending` | config key | source | Dispatcher option: queue bound. |
| `llm_timeout_s` | config key | source | Dispatcher option: wall-clock timeout of a model call. |
| `llm_deadline_ticks` | config key | source | Dispatcher option: how long a held decision may wait. |
| `llm_det_latency_ticks` | config key | source | Dispatcher option: latency in deterministic mode. |
| `discussions` | config key | source | Switch for the discussion mechanism, set by `interactive_config`. |
| `discussion_calls` | config key | source | Discussion option: call budget. |
| `discussion_deadline_ticks` | config key | source | Discussion option: deadline. |
| `discussion_max_open` | config key | source | Discussion option: open discussions per agent. |
| `discussion_bias` | config key | source | Discussion option: experimental bias. |
| `perturbations` | config key | both | The source's perturbation schedule; Prototype II refuses any non-empty value. |
| `interceptors` | config key | Prototype II | The interception layer's (always empty) list, set by `normal_config()`. |

None of these items describes the world. Each is either a notice that a model-layer
component exists or the configuration of one, and on the rules path every one of those
components is idle or absent.

## Side effects of the stripped rows

Dropping a row is not enough on its own, because every row the logger writes also advances
two counters that the kept data carries: the `seq` number of every later row, and the
logger's running total, which `snapshot()` and `summary()` report as `events`. The sides
emit different numbers of the stripped notices. The source emits its `discussions` notice
only when discussions are on (the app's configuration, where it says they are not
available), and its `llm_async` notice only when an agent is deciding on a model, which on
the rules path none is; so its app runs carry one stripped row and its `config("default")`
and code-default runs carry none. Prototype II always emits one `interception` notice and,
from Task 6, one `llm` notice. Left alone, these extra rows would shift `seq` and the
`events` counters by a constant on one side, although nothing in the world differs. The
filter therefore also removes those traces, on both sides and in the same way, which is what
the `side_effects` entry of `STRIP` records. After the topics are dropped, `seq` is
renumbered densely, 1 to N in the original order of the kept rows, before the stream is
hashed. The `events` counter of every snapshot is reduced by the number of stripped rows
whose tick is at or before the snapshot's tick, cumulatively (a notice at tick 0 is netted
from every snapshot, because a snapshot is taken after its tick has run), and
`summary["events"]` is reduced by the total number of stripped rows. Both counters then
measure the non-stripped stream on either side. Neither `seq` nor `events` is excluded from
the comparison: a later divergence in the number of world events would still change them.

## What is compared

Four runs of 1600 ticks each are made on the experts' rules with DK-RMM attached and ticked
after every step: the app's Normal on seeds 11 and 1 (`app_normal_rules_seed11`,
`app_normal_rules_seed1`), the default configuration on seed 11 (`default_config_seed11`)
and the code defaults on seed 1 (`code_defaults_seed1`). The source builds the first two
with `interactive_config(config("default"))`, the third with `config("default")` and the
fourth with `None`; Prototype II builds them with `normal_config()`, `normal_config()`,
`DEFAULT_CONFIG` and `None`. Every run is `build(seed=seed, config=cfg, run_id=f"fp-{name}",
log_path=log, scenario="normal")`.

Five quantities are compared for each run, and equality on all five for all four runs is the
alignment criterion. The first is `snapshots_sha256`, the hash of every per-tick
`eco.snapshot()` (parcels, tasks, robots, battery, storage, messages and the netted event
count).
The second is `dkrmm_readings_sha256`, the hash of every DK-RMM assessment record
(`monitor.history`, each `as_dict()` without `decided_at`, which is a wall-clock time). The
third is `dkrmm_states` together with `rct_ticks`, the sequence of DK-RMM states and the
ticks at which it reported RCT. The fourth is the summary reduced to its world counts:
`parcels_created`, `parcels_dispatched`, `parcels_refused`, `parcels_returned`,
`parcels_late`, `vans_departed`, `tasks`, `messages`, `events`, `reroutes`,
`supervisor_interventions` and `robots_recovered`. The fifth is
`event_stream_filtered_sha256`, the hash of the filtered event stream, which covers the
semantics of every remaining event. Every hash is the sha256 of
`json.dumps(obj, sort_keys=True, default=str)`, exactly as in the source's fingerprint. As a
check on the recipe, the source side's DK-RMM readings hash equals the one in the source's
own recorded `normal_baseline.json` for all four runs, and so does its snapshots hash for the
two runs in which the source emits no stripped row (`default_config_seed11` and
`code_defaults_seed1`); in the two app runs the snapshots hash differs from the recorded one
only because their `events` counter is netted of the `discussions` notice.

## How the baseline was generated

From the project root, with the source mirror at `SOURCE`:

```
PYTHONHASHSEED=0 .venv/bin/python tools/normal_fingerprint.py --from-source SOURCE --write tests/data/normal_baseline_filtered.json
```

`--from-source` runs the same recipe in a subprocess whose working directory is the source,
with the source package first on `sys.path`, `PYTHONHASHSEED=0`, `PO_NO_DOTENV=1` (so the
source does not read a `.env`), no other `PO_` variables and no bytecode written. The parent
hashes the source tree with `tools.provenance.tree_sha` before and after the run, refuses to
write if the two differ, and records the hash in the file's provenance block together with
`generated_at`, `ticks` and the filter (`strip`, its sets as sorted lists, with the
`side_effects` entry). No hash in the file was
typed by hand. Run without `--from-source`, the tool fingerprints this project instead, which
is what the test does.
