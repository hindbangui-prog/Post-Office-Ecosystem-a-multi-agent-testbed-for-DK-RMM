# Provenance

## Source identity

| field | value |
| --- | --- |
| Source commit | no git repository |
| source_tree_sha256 | b8ef01c738db9f84bcf1664ad39dfacb86a8b81226366db30342643d21588474 |
| source_tree_sha256_at_start | b8ef01c738db9f84bcf1664ad39dfacb86a8b81226366db30342643d21588474 |
| Date | 2026-10-12 |

The source tree hash covers the read-only cloud mirror of the source that this record was made from, not the user's source directory itself. The user's directory also holds `post_office/agents/llm_async-1.py`, which is not in the mirror (see Not copied), so a tree hash recomputed over the user's directory (`tools/provenance.py::tree_sha`) will differ from the one above even though no file changed.

Check the files one at a time instead. A row's `source_sha256` is the SHA-256 of the source file's bytes as the mirror holds them. The mirror was copied from the user's directory with the line endings kept (CRLF where the file has CRLF), so it should equal the SHA-256 of the user's file as it is on disk, not normalised. A file classed `unchanged` here is that source file after CRLF to LF normalisation. In PowerShell, from the user's source directory (the first hash printed is compared with `source_sha256`; the second, of the LF-normalised bytes, with the SHA-256 of an `unchanged` file in this project):

```powershell
cd "<source directory>"
python -c "import hashlib,sys; d=open(sys.argv[1],'rb').read(); print(hashlib.sha256(d).hexdigest(), hashlib.sha256(d.replace(b'\r\n',b'\n')).hexdigest())" post_office\agents\base.py
```

## Files

| path | class | source path | source sha256 |
| --- | --- | --- | --- |
| .env.example | new |  |  |
| .gitignore | new |  |  |
| README.md | new |  |  |
| conftest.py | new | conftest.py | 458e2de6c9aa296c2a5f5c47784d5a02b45293cdfd5c9f936de42e71e65eb9c7 |
| docs/agents.md | new |  |  |
| docs/alignment-baseline.md | new |  |  |
| docs/architecture.md | new |  |  |
| docs/c2-near-system-override.md | new |  |  |
| docs/camel-removal.md | new |  |  |
| docs/collapse-scenarios.md | new |  |  |
| docs/consultation.md | new |  |  |
| docs/crewai-ollama.md | new |  |  |
| docs/dkrmm-backlog-level-deviation.md | new |  |  |
| docs/dkrmm-mathematics.md | new |  |  |
| docs/dkrmm-operational-indicators.md | new |  |  |
| docs/dkrmm-sequences.md | new |  |  |
| docs/dkrmm.md | new |  |  |
| docs/events.md | new |  |  |
| docs/img/c2near-conditions.svg | new |  |  |
| docs/img/dkrmm-seq-1-stable.svg | new |  |  |
| docs/img/dkrmm-seq-2-deviating.svg | new |  |  |
| docs/img/dkrmm-seq-3-unstable.svg | new |  |  |
| docs/img/dkrmm-seq-4-rct.svg | new |  |  |
| docs/img/dkrmm-seq-5-dragon-king.svg | new |  |  |
| docs/img/ms-drop-crewai-v2.svg | new |  |  |
| docs/img/ms-drop-crewai-v3.svg | new |  |  |
| docs/img/ms-drop-crewai.svg | new |  |  |
| docs/img/ms-drop-zone-backlog-model.svg | new |  |  |
| docs/img/ms-drop-zone-backlog-rules.svg | new |  |  |
| docs/img/ms-stall-dk-seed13-model.svg | new |  |  |
| docs/img/ms-stall-steps-seed13-model.svg | new |  |  |
| docs/img/sim-1-tick-loop.svg | new |  |  |
| docs/img/sim-2-crewai.svg | new |  |  |
| docs/img/sim-3-decide-act.svg | new |  |  |
| docs/limitations.md | new |  |  |
| docs/ms-drop-model-enabled-v1.md | new |  |  |
| docs/ms-drop-model-enabled.md | new |  |  |
| docs/packages/README.md | new |  |  |
| docs/packages/agents-subagents.md | new |  |  |
| docs/packages/agents.md | new |  |  |
| docs/packages/api.md | new |  |  |
| docs/packages/communication.md | new |  |  |
| docs/packages/config.md | new |  |  |
| docs/packages/core.md | new |  |  |
| docs/packages/crew.md | new |  |  |
| docs/packages/discussion.md | new |  |  |
| docs/packages/dkrmm.md | new |  |  |
| docs/packages/environment.md | new |  |  |
| docs/packages/img/agents-1.svg | new |  |  |
| docs/packages/img/agents-2.svg | new |  |  |
| docs/packages/img/agents-3.svg | new |  |  |
| docs/packages/img/agents-subagents-1.svg | new |  |  |
| docs/packages/img/agents-subagents-2.svg | new |  |  |
| docs/packages/img/api.svg | new |  |  |
| docs/packages/img/communication.svg | new |  |  |
| docs/packages/img/config.svg | new |  |  |
| docs/packages/img/core.svg | new |  |  |
| docs/packages/img/crew-1.svg | new |  |  |
| docs/packages/img/crew-2.svg | new |  |  |
| docs/packages/img/discussion.svg | new |  |  |
| docs/packages/img/dkrmm.svg | new |  |  |
| docs/packages/img/environment-1.svg | new |  |  |
| docs/packages/img/environment-2.svg | new |  |  |
| docs/packages/img/observability.svg | new |  |  |
| docs/packages/img/packages.svg | new |  |  |
| docs/packages/img/policy.svg | new |  |  |
| docs/packages/img/robots.svg | new |  |  |
| docs/packages/img/simulation.svg | new |  |  |
| docs/packages/img/state.svg | new |  |  |
| docs/packages/img/tasks.svg | new |  |  |
| docs/packages/img/ui.svg | new |  |  |
| docs/packages/observability.md | new |  |  |
| docs/packages/policy.md | new |  |  |
| docs/packages/robots.md | new |  |  |
| docs/packages/simulation.md | new |  |  |
| docs/packages/state.md | new |  |  |
| docs/packages/tasks.md | new |  |  |
| docs/packages/ui.md | new |  |  |
| docs/perturbation-seams.md | new |  |  |
| docs/provenance.json | new |  |  |
| docs/provenance.md | new |  |  |
| docs/provenance_classification.json | new |  |  |
| docs/provenance_notes.md | new |  |  |
| docs/provenance_trimmed_tests.md | new |  |  |
| docs/real-run-2026-10-02.md | new |  |  |
| docs/running.md | new |  |  |
| docs/simulation-diagrams.md | new |  |  |
| docs/superpowers/plans/2026-10-01-prototype-ii-implementation-plan.md | new |  |  |
| docs/superpowers/plans/2026-10-02-runtime-communication-taxonomy-plan.md | new |  |  |
| docs/superpowers/plans/2026-10-02-trajectory-and-rct-log-plan.md | new |  |  |
| docs/superpowers/specs/2026-10-01-prototype-ii-crewai-ollama-design.md | new |  |  |
| docs/superpowers/specs/2026-10-02-runtime-communication-taxonomy-design.md | new |  |  |
| docs/superpowers/specs/2026-10-02-trajectory-and-rct-log-design.md | new |  |  |
| docs/superpowers/specs/2026-10-11-c2-near-system-override-design.md | new |  |  |
| docs/superpowers/specs/2026-10-12-dkrmm-operational-indicators-design.md | new |  |  |
| docs/verification.md | new |  |  |
| main.py | adapted | main.py | 8baed660dfe95c8af04cd57574c748b3afdf92f46b91aedd6a9814d81af5fc23 |
| post_office/__init__.py | new | post_office/__init__.py | 863f3f72fd18f93ef2eb1bc95f271ed2a3a34710ac69bd374163f817e9d59e32 |
| post_office/agents/__init__.py | adapted | post_office/agents/__init__.py | 8fa78aa155123d7f5009961d2312ceda36dc9d5b44ff84072933d5fab151d9eb |
| post_office/agents/assignment_metrics.py | unchanged | post_office/agents/assignment_metrics.py | fa4fe216eb98609db9309dbf04691e5c4b762654d3c36adf845abde2111e1bd6 |
| post_office/agents/base.py | adapted | post_office/agents/base.py | a03a514b2003adda9ff963fee4319071473aad056593181d55032a2d9c25e0d2 |
| post_office/agents/brain.py | adapted | post_office/agents/brain.py | 50410aae4af071423da9e87cfa3091685f53fa93bef740b52c11f0e3d80fd922 |
| post_office/agents/deferral.py | replaced | post_office/agents/llm_async.py | 503db4fb088c3a9911d5a2f404e358503eaf11cc2c56d0a7432a695736c53721 |
| post_office/agents/dispatch_agent.py | adapted | post_office/agents/dispatch_agent.py | 0ab09f23f11d15601aa7c570d42383d97b5a0754d74d7e3e10b1a2e380e61bb5 |
| post_office/agents/intake_agent.py | adapted | post_office/agents/intake_agent.py | 73837a019cba302b0e0c60aeb7c59f36a10c50e1adbb0873419a59a45e7d45b4 |
| post_office/agents/planner_agent.py | adapted | post_office/agents/planner_agent.py | 57f8eac111e9b9aa64cb95f0ecf65e80d689caa6b8cead96e14153c6cf31450c |
| post_office/agents/reasoning.py | unchanged | post_office/agents/reasoning.py | 1414446a90572d1d82ab5a002355d529db12e8b397f4c72bdb55c3de4e938252 |
| post_office/agents/resource_agent.py | adapted | post_office/agents/resource_agent.py | 056a68bf967a3ca9a0b6b2d60520ad8511c05e22ff7aef74a7e6de02d8b2512c |
| post_office/agents/robot_agent.py | unchanged | post_office/agents/robot_agent.py | 524d5de70ce37d35a987b6a03e3ca67d39842bd3c0127fa4d4e2294755e4ce8a |
| post_office/agents/routing_agent.py | adapted | post_office/agents/routing_agent.py | 449fda5c58a0072a46c01e70985f93bedd20961a93d92b08cc8a957c24f5ebab |
| post_office/agents/scheduling_agent.py | adapted | post_office/agents/scheduling_agent.py | fe9749b234ed6bb6e024c60972bda0e87c5d3c260b241aee144710c8e71a115b |
| post_office/agents/sorting_agent.py | adapted | post_office/agents/sorting_agent.py | bbb2b3c31a0ca5f9c38ada38e4151533e8a1b0d8eb3605fee0e0e795901aab9c |
| post_office/agents/subagents/__init__.py | unchanged | post_office/agents/subagents/__init__.py | a244c404126a4f8428f8041cefc90d097fbfabf70b944965c89711c354a6b8f6 |
| post_office/agents/subagents/assignment_subagent.py | unchanged | post_office/agents/subagents/assignment_subagent.py | 7cf65840af1b90db89d2e814c7938816b6a35866ad6cd29fdc793e0b562b5e6d |
| post_office/agents/subagents/gate_subagents.py | unchanged | post_office/agents/subagents/gate_subagents.py | 67da99dc5135f8e980169907ff52c2de812c5a4bd882440945845885f767f949 |
| post_office/agents/subagents/resource_subagents.py | unchanged | post_office/agents/subagents/resource_subagents.py | ed7d0b3cfbf9312c684037e2e1c8948a3c7213f51ab8dfbe5fbeb5d1a7c2b753 |
| post_office/agents/subagents/routing_subagents.py | unchanged | post_office/agents/subagents/routing_subagents.py | 0a728a9f258db82dfe16280a4ba93c22f5ac463b09bb14d565b4c44d2adac0fb |
| post_office/agents/subagents/scheduling_subagents.py | unchanged | post_office/agents/subagents/scheduling_subagents.py | 0e93aff6256efea2ad7b52b6ff768a043355f2365a7c68fa5fe1243da5ddf8cb |
| post_office/agents/subagents/sorting_subagents.py | unchanged | post_office/agents/subagents/sorting_subagents.py | 816d2ec5d1b2105f1bf73b78e0b633174dd406cc92df5916e560b88831e2a699 |
| post_office/agents/supervisor.py | unchanged | post_office/agents/supervisor.py | 7601549809ea9bd16801c561740e4f8df976bfc06ec5144fe38c83e1686bb366 |
| post_office/api/__init__.py | adapted | post_office/api/__init__.py | ea0a2f8857b25b38f5a9aca72447f4f5c2ec5f700116c51285cef85515361faa |
| post_office/api/digest.py | adapted | post_office/api/digest.py | f81f297360fb7d9fbf3c518a03fd4853c72cb693bcccb0cf7173b04369c94171 |
| post_office/api/runner.py | adapted | post_office/api/runner.py | 324705817458899a4e29e1d06e17f1428a8a223e391ff4b5a73083ca7b96e8c4 |
| post_office/api/server.py | adapted | post_office/api/server.py | 262186570d506c25ec43806b5536b9417f33ec05d0882beb51a2d60fa58e86ad |
| post_office/communication/__init__.py | unchanged | post_office/communication/__init__.py | 2ca513271aff5c70177515e3b4a3757a5d2dcf25021c3ca59d7bf5db5271c4c5 |
| post_office/communication/bus.py | adapted | post_office/communication/bus.py | 595eca2b45d2816c2ed31b599be8e962ef5c20ff0c5346743de08c27b5f86570 |
| post_office/communication/directory.py | unchanged | post_office/communication/directory.py | 320d996b6c703620a8c725dfad22da617e61a14c2d57081507cca33fdcab2bfd |
| post_office/communication/events.py | adapted | post_office/communication/events.py | f82dce0907e359e88d486024fcbbec616b4a0ca9186c491c67389edbe70eeafa |
| post_office/communication/message.py | adapted | post_office/communication/message.py | f380eb74c68e13d0b2d5180e27c0868dddd291015f88698857fbf5a06bcb6714 |
| post_office/communication/provenance.py | unchanged | post_office/communication/provenance.py | c39ef03439d8aed4b4534f9ea3a3266f0907e4d0d5fd3eff1f52d15c71433af7 |
| post_office/communication/taxonomy.py | new |  |  |
| post_office/communication/topics.py | unchanged | post_office/communication/topics.py | d99d52889fe43338713c26d2ab82f546b0fccd410ff2afb465828e146bea41b7 |
| post_office/config/__init__.py | adapted | post_office/config/__init__.py | 6591670a7c26d2b675d4cafbad0fdcac765ac6a377f1a665bc3f3968dee5dc35 |
| post_office/config/ollama.py | replaced | post_office/config/providers.py | 654ff78be71e5454fdb826bd06e21e95e0f685915e03c6eac518f25e181bd04b |
| post_office/config/settings.py | adapted | post_office/config/settings.py | ca13210faf1a0163d726b6f44f55cb6267be6f69b064e8d7e6d35b492e810641 |
| post_office/core/__init__.py | unchanged | post_office/core/__init__.py | 289e9528ee6ac26d8784352deba4b85d30bec5511b96045fa1165411a015f404 |
| post_office/core/ids.py | unchanged | post_office/core/ids.py | 65393c4e93748ec47398f781bdf30857b6c26d417815b216110fefa5044c7378 |
| post_office/core/rng.py | unchanged | post_office/core/rng.py | 0f380ece390064587b51bcf48716e41d47330a8f90f311af91971932837e92fd |
| post_office/core/visible.py | unchanged | post_office/core/visible.py | 2e70896fa015972a9c635354190dcea1065605170804dd1ab42f154a52cfd8f3 |
| post_office/core/world.py | unchanged | post_office/core/world.py | bd8b3e21dacd63a4cd8eff68797e1a3c25a4612897bb55b6b2a7dfec8ea17eeb |
| post_office/crew/__init__.py | new |  |  |
| post_office/crew/audit.py | replaced | post_office/config/providers.py | 654ff78be71e5454fdb826bd06e21e95e0f685915e03c6eac518f25e181bd04b |
| post_office/crew/brain.py | replaced | post_office/agents/camel_brain.py | 73e248ebc4eeda9daa98015c1e2bd3b5f8f6bf3bd00fcde2f43f76990db9a6bf |
| post_office/crew/console.py | new |  |  |
| post_office/crew/consultation.py | replaced | post_office/discussion/manager.py | 975b9724352163f03db191d46edee9eb3239c0c6bb7823107fa7a4613a4081d3 |
| post_office/crew/events.py | new |  |  |
| post_office/crew/identity.py | replaced | post_office/config/providers.py | 654ff78be71e5454fdb826bd06e21e95e0f685915e03c6eac518f25e181bd04b |
| post_office/crew/interception.py | new |  |  |
| post_office/crew/llm.py | replaced | post_office/config/providers.py | 654ff78be71e5454fdb826bd06e21e95e0f685915e03c6eac518f25e181bd04b |
| post_office/crew/parse.py | replaced | post_office/agents/camel_brain.py | 73e248ebc4eeda9daa98015c1e2bd3b5f8f6bf3bd00fcde2f43f76990db9a6bf |
| post_office/crew/roles.py | replaced | post_office/agents/camel_brain.py | 73e248ebc4eeda9daa98015c1e2bd3b5f8f6bf3bd00fcde2f43f76990db9a6bf |
| post_office/crew/tools.py | replaced | post_office/discussion/manager.py | 975b9724352163f03db191d46edee9eb3239c0c6bb7823107fa7a4613a4081d3 |
| post_office/discussion/__init__.py | adapted | post_office/discussion/__init__.py | d8d0414ee82525c079e7488b860ce09a9b656e1bd79d0bb25e064f7b4b91086c |
| post_office/discussion/briefings.py | unchanged | post_office/discussion/briefings.py | fcf1f69be4bd3496e29bf086fec6ea3ba94e51d94e3ac69a587fde8e2e9fb22a |
| post_office/discussion/peers.py | unchanged | post_office/discussion/peers.py | 44cc7043d000eae88e1959d4fce570b09bebc8a61cbf11a3aee90458d5263727 |
| post_office/discussion/prompts.py | unchanged | post_office/discussion/prompts.py | f0e67185e88adc6fc8f263be74e51b8b202ebcf803415d7f4988546cb7f6d725 |
| post_office/dkrmm/__init__.py | adapted | post_office/dkrmm/__init__.py | 9a883f6af1e136d70e3a09493487ff8527f3f62455292d066ce4d4dcd3449127 |
| post_office/dkrmm/indicators.py | adapted | post_office/dkrmm/indicators.py | e7dcee122a8524c4665a15062c598d67297d2d8a5d389e9bff11e3d13ea180b9 |
| post_office/dkrmm/monitor.py | adapted | post_office/dkrmm/monitor.py | b27b918ab8137d7b1e9f321c26cc01ab2b05d7aa52c1318c7fc87225203d63c7 |
| post_office/dkrmm/operations.py | new |  |  |
| post_office/dkrmm/record.py | unchanged | post_office/dkrmm/record.py | 5cc672e9019e5b599f9a3f589fa39cc31e44cea0103f1cde6a8c2106ac3ab42a |
| post_office/dkrmm/signals.py | unchanged | post_office/dkrmm/signals.py | 1c867377cd0f68f4231e40c77db5d121d2481897809f23e4a4f2660555211c22 |
| post_office/dkrmm/states.py | unchanged | post_office/dkrmm/states.py | f644d660730581f7e0217afda7db72a0a47ed58303c6009838a0aec84ae23450 |
| post_office/environment/__init__.py | unchanged | post_office/environment/__init__.py | 8b964fbe9606395ee745a773ed1fc4d1e4c03a9b45298b3564bcff8964b96b39 |
| post_office/environment/facility.py | adapted | post_office/environment/facility.py | 4c796baa63635462f2ce08d47adc65a4785371b8bd621d30fe066b3fd567bd74 |
| post_office/environment/grid.py | unchanged | post_office/environment/grid.py | 2789fce6bd803f7e6544abca86d7f48a6fac7539c347eede762af5367275c2e7 |
| post_office/environment/layout.py | unchanged | post_office/environment/layout.py | 1b0ab699bc9d8b3424e6bcae2df912813f8417e0a0da1512d7fe27325f5bf7d1 |
| post_office/environment/parcels.py | unchanged | post_office/environment/parcels.py | 60a2f80034467e09df74680cc915099d2b563e75b74ab57888da770beea870b5 |
| post_office/environment/receptacles.py | unchanged | post_office/environment/receptacles.py | 3d7ede4c7c664bba373a0beafd7d5d2e9fb4c1b71fdccc139f68426344dcda4e |
| post_office/environment/recovery.py | unchanged | post_office/environment/recovery.py | 409d41024759a37830442546427b2f3a507415e493d3aabb94142145cea60879 |
| post_office/environment/vehicles.py | unchanged | post_office/environment/vehicles.py | e6973f4f619dc2c80002166a183f790849310f8ec4e218fc574f6b9859fb28a2 |
| post_office/environment/zones.py | unchanged | post_office/environment/zones.py | 8ac27a8ccc65cfee81c65a092aa092fc8378c9eaa798a32def64c0afaf3ca9b2 |
| post_office/observability/__init__.py | new | post_office/observability/__init__.py | 6cbe97b6bc23522c7defd409ed1356aab6f5251c84f161c404a0c8a0e265b412 |
| post_office/observability/context.py | unchanged | post_office/observability/context.py | 8bdaa18ec98364537d0588864fbd177827170b57eff94e038f52247f29b99c83 |
| post_office/observability/decision_trace.py | new |  |  |
| post_office/observability/experiment.py | new |  |  |
| post_office/observability/rct_explain.py | adapted | post_office/observability/rct_explain.py | 8c82265f3070144439af375f62e0323a75f5832a7839647d986bafca4d79cdcc |
| post_office/observability/rct_log.py | unchanged | post_office/observability/rct_log.py | 9e3f5bb241762c493bf10eb9125e40f536616fc572327e2f253338f3cb213efc |
| post_office/observability/run_record.py | adapted | post_office/observability/run_record.py | 677a3226c36ed2f922147bda343763eee9745790c803730efdb4043370d7954d |
| post_office/observability/zone_backlog.py | new |  |  |
| post_office/policy/__init__.py | unchanged | post_office/policy/__init__.py | 4e5608ffa1e7693df4291f834b096fa76a9696589a6a094eb58b64b740702da3 |
| post_office/policy/gate.py | unchanged | post_office/policy/gate.py | c6ce984e7d5a348e45a009d9a99a903dc6a7dc8d110d0c147b8baccf6dd93ece |
| post_office/robots/__init__.py | unchanged | post_office/robots/__init__.py | 7a7f1532e17fad6acaf0e82da2d844c08468bb897401df8870d9b895ae665f91 |
| post_office/robots/fleet.py | unchanged | post_office/robots/fleet.py | ef8ed846b954e0bc153f901f766c93b8a78bf89e7cb12e7677a76df649552c2d |
| post_office/robots/robot.py | unchanged | post_office/robots/robot.py | ae3f913a602b34e0269b2a5d149d7e34bc10425b530351429540943c44f21753 |
| post_office/simulation/__init__.py | unchanged | post_office/simulation/__init__.py | 3643dff5f28c7fb07200456f3a1e5bdddc541ba62063a0b3f3e0ee44c4ad1c5d |
| post_office/simulation/ecosystem.py | adapted | post_office/simulation/ecosystem.py | 02cce9e1d3ff2d397515097ec31ca6f5a4cf79264dd8d7d8c3fcdb9215312048 |
| post_office/simulation/generator.py | unchanged | post_office/simulation/generator.py | ed09971716664a8123a583ae24bc54414376f000bbc9643c5d3c01432a7cdd89 |
| post_office/simulation/recovery.py | unchanged | post_office/simulation/recovery.py | f826df154cc102ea818efc749453ef5d800993f429241642f7edb20d22827758 |
| post_office/state/__init__.py | unchanged | post_office/state/__init__.py | 65db405e118048de568d8675b0feed4c7bf3496134328272f9f54dd8ed52ad93 |
| post_office/state/system_state.py | unchanged | post_office/state/system_state.py | c218bb975ad74235cc58b6afb08e569c0c392fdca704633a04e5bf03e46e4d7a |
| post_office/stress/__init__.py | new | post_office/stress/__init__.py | cf8707ce438257f5028f6bce44768ecdcae7ead1553faffe7795f51eb4ab37da |
| post_office/stress/analysis.py | new |  |  |
| post_office/stress/c2near_system_override.py | new |  |  |
| post_office/stress/collapse.py | new | post_office/stress/collapse.py | f6ec9e7abf3ae413efa254faac852b48ecfc011a9b7a3aa6566af1b24f9931f8 |
| post_office/stress/collapse_scenarios.py | new |  |  |
| post_office/stress/measure.py | new |  |  |
| post_office/stress/operational.py | new |  |  |
| post_office/stress/report.py | new |  |  |
| post_office/stress/states.py | new |  |  |
| post_office/stress/system_override.py | new |  |  |
| post_office/tasks/__init__.py | unchanged | post_office/tasks/__init__.py | 4c8cb6ab0f714f0c9cb7250bcc8945e379d4eba85b06913afee31d042dfb91ae |
| post_office/tasks/registry.py | unchanged | post_office/tasks/registry.py | a7050a9124175330893842b636616218ee3318260b4fd069f885b59ad4a6902f |
| post_office/tasks/task.py | unchanged | post_office/tasks/task.py | df760aa00fa1e8b44cf39f1461cc2529eb4c6b2ff15b1de5699f95d7736940fc |
| post_office/ui/__init__.py | adapted | post_office/ui/__init__.py | 3973b855d7da8162d5cce8913577489e5950593ec1b722702eac48f34215c6e4 |
| post_office/ui/c2near_report.html | new |  |  |
| post_office/ui/feed.py | new |  |  |
| post_office/ui/floor.html | adapted | tools/replay_template.html | ad00edf73bd5e436f67208d54dd8196faf9d9e42b2db68aa2da95b1a7f1190d0 |
| post_office/ui/live.html | adapted | post_office/ui/live.html | a7a5f8cbed3a2bb4b3b43c887b110ac6752d31360975d329496e3703e3c57cd8 |
| post_office/ui/live.py | adapted | post_office/ui/live.py | 0799d6f836d7fbd3de7d8cf7ee0c5c88095fedb3381542dc49b23c75ad17242a |
| post_office/ui/rcts.html | adapted | post_office/ui/rcts.html | d50df474b984699ddcd5509b80f445750e60b01dfe0de3d8a6690c9b53b21294 |
| post_office/ui/trajectory.html | adapted | tools/trajectory_template.html | f6e1bc90c337e9e0f449200c54d765447fed72153bfd1b7a5308e60324e8db56 |
| post_office/ui/views.py | adapted | post_office/ui/views.py | 0536877aec7186149db42719b5d0e418a406a9578d85fd91584225a2289d5b51 |
| pyproject.toml | new | pyproject.toml | 537afcc9a2f2db47c4ee3665e6e449c200194652d3f1b6c5a870335435a17ba1 |
| pytest.ini | new |  |  |
| requirements.txt | new | requirements.txt | fbe39bc70be8fc505ea8f37e7690d167155ff80a127c98518937f728641ab6a5 |
| tests/__init__.py | new |  |  |
| tests/consult_helpers.py | new |  |  |
| tests/data/normal_baseline_filtered.json | new |  |  |
| tests/fake_ollama.py | new |  |  |
| tests/presets.py | new |  |  |
| tests/test_agents.py | adapted | tests/test_agents.py | 2a2ae835b1c3081c3e1470bdbc58c657ec20a4e115aa82d401e11c8228b4bf5c |
| tests/test_allowed_peer_enforcement.py | new |  |  |
| tests/test_api.py | adapted | tests/test_api.py | e32341d76b624a7609c0dcb5b3b63ad9dc7da06d0c2bd50c834d30325d0cd2e9 |
| tests/test_api_rcts.py | new |  |  |
| tests/test_api_taxonomy.py | new |  |  |
| tests/test_api_trimmed.py | new |  |  |
| tests/test_base_sync_decide.py | new |  |  |
| tests/test_c2near_report.py | new |  |  |
| tests/test_c2near_system_override.py | new |  |  |
| tests/test_charging.py | unchanged | tests/test_charging.py | 7b9513ea35b07687c94dda99fff3c2b933fcb4a0820025abfbf6c7dd22e6dac7 |
| tests/test_collapse_scenarios.py | new |  |  |
| tests/test_communication.py | unchanged | tests/test_communication.py | 089cb506324bf7f25455ea30b0628004dbf47c55150f18f83f9d7ad5a03ba146 |
| tests/test_consultation_causality.py | new |  |  |
| tests/test_consultation_fallbacks.py | new |  |  |
| tests/test_consultation_sync.py | new |  |  |
| tests/test_controls.py | adapted | tests/test_controls.py | ef0db5f43d525e9e811d605d509d22d21fe6d7bbb513a14e28cddc354db623e7 |
| tests/test_crew_brain_init.py | new |  |  |
| tests/test_crew_llm.py | new |  |  |
| tests/test_decision_pipeline.py | adapted | tests/test_decision_pipeline.py | f0d18d4183609f565fd7a9a2ef52305fc695340682b747d126a3fcb8bb0c7559 |
| tests/test_deferral.py | new |  |  |
| tests/test_discussion_briefings.py | adapted | tests/test_discussion_briefings.py | 4185e31ecef9d0b55e508a49f1112cdc068c2aa483b6137e11f8e1fc47107f86 |
| tests/test_discussion_peers.py | adapted | tests/test_discussion_peers.py | fb7befa0f9e76f50304e93aa7ec58c9a53ec3ec89bd6bd9f1d0066ddd189c86d |
| tests/test_discussion_prompts.py | adapted | tests/test_discussion_prompts.py | bf3dfb63fd53a5845e0ea55e770aac4e546fcee844a8878c5036c6e1a675028a |
| tests/test_discussion_trigger_names.py | unchanged | tests/test_discussion_trigger_names.py | 214f2b9cfc1cda4deedd4590ded45727ca973e3a41842ddb3cb50f8a571e5d3a |
| tests/test_dispatch_flow.py | unchanged | tests/test_dispatch_flow.py | 29a20488dde3cb7eb1c7ab4f80985d1f6304e610f12105462a1ab9dd08782c48 |
| tests/test_dispatch_priority.py | adapted | tests/test_dispatch_priority.py | 166eda713a92ca4abe1d5fc4a0ccfa3d56f13e0ef6c98f8fef78dc66c381d4b5 |
| tests/test_dk_view.py | new |  |  |
| tests/test_dkrmm.py | adapted | tests/test_dkrmm.py | 2ea9bb2f99f9307281e64ec1c4e509dc283fcfc30aa2374db494f582c55a78dd |
| tests/test_dkrmm_dashboard.py | new |  |  |
| tests/test_dkrmm_independence.py | new |  |  |
| tests/test_dkrmm_math.py | new |  |  |
| tests/test_dkrmm_operational.py | new |  |  |
| tests/test_dkrmm_receives_consultations.py | new |  |  |
| tests/test_dkrmm_record.py | unchanged | tests/test_dkrmm_record.py | 44e23d5dcf263a3d6b048cc31f2e01c07eb80e209b7773f8e6111e8350d7e357 |
| tests/test_dkrmm_stamping_invariance.py | new |  |  |
| tests/test_docs_present.py | new |  |  |
| tests/test_ecosystem.py | adapted | tests/test_ecosystem.py | 20d580d17022e15b23a01718192b510c6effaafcd95c0e2e1557eea3072c47b4 |
| tests/test_ecosystem_normal_guards.py | new |  |  |
| tests/test_environment.py | unchanged | tests/test_environment.py | ed1ab8b90988bd3ce6fb3a65c8b0b40f48db22addfb415458b6ce0a2163ca9de |
| tests/test_event_stamping.py | new |  |  |
| tests/test_events_consultation.py | new |  |  |
| tests/test_fake_ollama.py | new |  |  |
| tests/test_feed_integrity.py | new |  |  |
| tests/test_four_state_view.py | new |  |  |
| tests/test_gates.py | adapted | tests/test_gates.py | f6c9e8ca665210924d523cb1b1c29eb2956461947034cc7eeb05b477db389354 |
| tests/test_header_digest.py | adapted | tests/test_header_digest.py | cc53486223e58cdabe4b7ebbb00270fc2d8843fd2032a39f7007c85cf2184148 |
| tests/test_judgement.py | unchanged | tests/test_judgement.py | 4142d04aaf03b65efb57346d1a3ea48875fe684b982482cabd98f6c071ed3b9e |
| tests/test_live_c2near.py | new |  |  |
| tests/test_live_collapse_ui.py | new |  |  |
| tests/test_live_experiment.py | new |  |  |
| tests/test_live_ui.py | new |  |  |
| tests/test_llm_call_logging.py | new |  |  |
| tests/test_model_identity.py | new |  |  |
| tests/test_ms_drop_model_analysis.py | new |  |  |
| tests/test_ms_stall.py | new |  |  |
| tests/test_no_camel.py | new |  |  |
| tests/test_normal_alignment.py | new |  |  |
| tests/test_ollama_settings.py | new |  |  |
| tests/test_packing.py | unchanged | tests/test_packing.py | 7119535d89ed698fa7789b7c568ed46765fb4e29aa0b75dceeab45c8a4c5ee3b |
| tests/test_paid_service.py | adapted | tests/test_paid_service.py | 2b1d9209cf410af8e68fed5a931e16d757cbf81bfb9602d316eef7d450988dbb |
| tests/test_parse.py | new |  |  |
| tests/test_policy_gate.py | adapted | tests/test_policy_gate.py | 8c8643febc9c7eedcee8459594960158e0ad5d8031c47ad1022c44b5a4c5589a |
| tests/test_priority.py | adapted | tests/test_priority.py | c8fccab089ac7d3e7c9e6486eda25d7019716bd6ccf4bc310057edf87bda23f8 |
| tests/test_project_layout.py | new |  |  |
| tests/test_queued_assignment.py | adapted | tests/test_queued_assignment.py | dcf133fa784324977fe56260cc91c732b31f08b179cd0deb3bc933e52c3bf0c4 |
| tests/test_rct_explain.py | adapted | tests/test_rct_explain.py | f07cfec21fbba375677b5bcb629cb65477ccbb6916b38cf6cccb11629bf769d4 |
| tests/test_rct_log.py | adapted | tests/test_rct_log.py | 6aa063e47342ede372cf1a61381dc0b67cb5802d9331c7a0aa2b6fd5c4df9154 |
| tests/test_reasoning_trigger.py | unchanged | tests/test_reasoning_trigger.py | a752dc59c55796c4debecae95805994a372b20fc97331effd719548f539a73fd |
| tests/test_recording.py | new |  |  |
| tests/test_recovery.py | unchanged | tests/test_recovery.py | e54e1bc8540e6c1335040fe98cf7031b139daddd0789f312c100cf3f0bc5881e |
| tests/test_resource_priority.py | unchanged | tests/test_resource_priority.py | 87f71d1d63dc52c3a04ef5b937630201a2871b1697281321e9af043bba4a6c05 |
| tests/test_robots.py | unchanged | tests/test_robots.py | add4734efe6f97d78a7347ada51d8679e1cbe2f00148604362ea19b9a2630928 |
| tests/test_roles_preserved.py | new |  |  |
| tests/test_rules_first.py | new |  |  |
| tests/test_run_normal_tool.py | new |  |  |
| tests/test_run_record.py | adapted | tests/test_run_record.py | 70c66b80d14856f64756f40087b3a62dd83f55e3637b814873e0ef5f1c0bf67a |
| tests/test_runner.py | new |  |  |
| tests/test_seams_noop.py | new |  |  |
| tests/test_simulator_authority.py | new |  |  |
| tests/test_sorting_process.py | unchanged | tests/test_sorting_process.py | 2634ff5c12e2f8d16bcb43a9ee05ac11b52b9096a864553690229733562c2bbc |
| tests/test_taxonomy.py | new |  |  |
| tests/test_taxonomy_completeness.py | new |  |  |
| tests/test_throughput.py | adapted | tests/test_throughput.py | 538ff2d4523ca82bfa864b2675408cfaeb1b5cc1b68cb3fd5cd265ae50274975 |
| tests/test_trajectory.py | new |  |  |
| tests/test_urgent_route.py | adapted | tests/test_urgent_route.py | 725c37605e90ef243195a8e59de9aaddaabe522f94b7ec5d4e8a2fa6c7783595 |
| tests/test_validation.py | unchanged | tests/test_validation.py | 85ea72f78a107310daa38ee7f5f3da7ebf8c11b709a9e9854f3d3c3b5fedbe27 |
| tests/test_vehicles.py | adapted | tests/test_vehicles.py | 248eff6ffaecd3e5133dd1fae10683d652bcd85258aa11cf37809119049ad3f7 |
| tests/test_where_judgement_lives.py | unchanged | tests/test_where_judgement_lives.py | d9d7f4b9656e631da4e37f40d6546cb6f58e116b1813c003edd1157cdcf6b22c |
| tools/analyze_ms_drop_model.py | new |  |  |
| tools/c2near_report.py | new |  |  |
| tools/ms_stall_dk_figure.py | new |  |  |
| tools/ms_stall_steps_figure.py | new |  |  |
| tools/normal_fingerprint.py | adapted | tools/normal_fingerprint.py | 5680976f3d0503f60e94b92816466a7eca54d463ca5a5df63c06927f20b5fdf8 |
| tools/provenance.py | new |  |  |
| tools/run_c2near_system_override.py | new |  |  |
| tools/run_collapse_scenarios.py | new |  |  |
| tools/run_normal.py | new |  |  |
| tools/taxonomy_table.py | new |  |  |
| tools/validate_dkrmm_indicators.py | new |  |  |
| tools/verify_ollama.py | new |  |  |
| tools/write_provenance.py | new |  |  |
| tools/zone_backlog_figure.py | new |  |  |

Classes: `unchanged` (byte-identical to the source file except for line endings, normalised to LF), `adapted` (copied and changed), `replaced` (a new file that takes over a removed source file's job), `new` (no source counterpart).

The check that the source's model framework is gone, with the grep and the dependency audit, is the removal record [camel-removal.md](camel-removal.md).

## Removed

Every file of the source tree that has no counterpart in this project, with its reason class: the `post_office/` package, `tests/`, `tools/`, `scripts/`, `docs/` and the top-level files. The directories the source tree hash also skips (.git, .model_cache, .pytest_cache, .venv, __pycache__, logs, results) and the tool caches .deepeval, .pytest_cache hold no source files and are not listed. `tools/replay_template.html` and `tools/trajectory_template.html` are not listed either: they were adapted into `post_office/ui/floor.html` and `post_office/ui/trajectory.html` (see Notes). The source files that `replaced` files take over from are listed here and named as those files' source path under Files.

| reason class | why it has no counterpart |
| --- | --- |
| model layer | the source's model framework, asynchronous dispatch, response cache, provider factory and discussion manager, and the launcher of the app on them; replaced by `post_office/crew/` and `config/ollama.py` |
| perturbation machinery | attacks, injections and biased discussions; no perturbation is part of this phase (see docs/perturbation-seams.md) |
| experiment tooling | stress batteries, experiment families and their runners, reports and templates, the trace store and its viewers; Normal is the only scenario and the event log and `results/` files replace the trace |
| UI pages | pages of the source UI that served removed features; the consultation, Ollama and DK-RMM panes of `ui/live.html` replace them |
| tests of removed machinery | tests of the model framework, the asynchronous dispatch, the discussion manager, perturbations, stress experiments and the trace; the carried tests are listed under Files |
| superseded test data | the source's unfiltered Normal baseline, replaced by `tests/data/normal_baseline_filtered.json` (see docs/alignment-baseline.md) |
| frozen attack scripts | the frozen perturbation scripts the source's experiments replayed |
| source docs | the source's notes on its asynchronous model dispatch and on a pilot experiment |

| source path | reason class | source sha256 |
| --- | --- | --- |
| docs/2026-09-29-pstar-matched-pilot.md | source docs | 7fd7db3a8279d593a36c435142026480cd0f089c0981def83e89c71cbbadf4a4 |
| docs/async-llm.html | source docs | 09cc4e55b97d70fb66ea33b499dc920455f5813fd59d634ce096d14ea92bd458 |
| post_office/agents/camel_brain.py | model layer | 73e248ebc4eeda9daa98015c1e2bd3b5f8f6bf3bd00fcde2f43f76990db9a6bf |
| post_office/agents/llm_async.py | model layer | 503db4fb088c3a9911d5a2f404e358503eaf11cc2c56d0a7432a695736c53721 |
| post_office/agents/response_cache.py | model layer | 2b5f065a2b3e6204fb7e0a440ca6430e034aff23dfa235ead0ef9908f83be8cb |
| post_office/api/injections.py | perturbation machinery | 2ec2999d7dc226e4f0aa74832b8bb050cd9060cbe936f64649b4e0180ea987b6 |
| post_office/config/experiments.py | experiment tooling | 8c60b1da8fd77dd098a87a14246e68b72722e868f00bf3a8d12ec082012fed22 |
| post_office/config/providers.py | model layer | 654ff78be71e5454fdb826bd06e21e95e0f685915e03c6eac518f25e181bd04b |
| post_office/discussion/bias.py | perturbation machinery | 297aece5fa167a47cced4bb579b95bca162e18a4deaf163524a08075aa310b94 |
| post_office/discussion/manager.py | model layer | 975b9724352163f03db191d46edee9eb3239c0c6bb7823107fa7a4613a4081d3 |
| post_office/observability/instrumentation.py | model layer | c6fe975dbc1bfcc42471658d9550bede4d644d5fda3274bfdd1577271186d9f8 |
| post_office/observability/sink.py | experiment tooling | 69b31052fc8d35798fe7a4043312daac2b9121e492611406452c86a75688abeb |
| post_office/observability/store.py | experiment tooling | 6b7fd5a2822576ca63538af2db7f7c21cf19d1c5343cb1daa6a7423b761848f1 |
| post_office/observability/tools.py | experiment tooling | 927a7fcf001d4337aaa8a2fba2315b387dd9576ae2b8f73be16258696e4557c7 |
| post_office/observability/tracer.py | experiment tooling | bff2c1d1cc2749d0429991f5fa838c58c02c082093c772d90d3dd9e90a6d617b |
| post_office/perturbation/__init__.py | perturbation machinery | eacacc20eacf2040c15c04d956c123299b3176aa9b4e4f6e3740c40aca9cc2f9 |
| post_office/perturbation/controller.py | perturbation machinery | e204d258ace3387633613973b8012340905d18006485d9d13f31a92569062d51 |
| post_office/perturbation/deepteam_adapter.py | perturbation machinery | b4f1ea9ea0bac842e471b72ac48a0da449665e4f20b3d00868cb388dd96aae0c |
| post_office/perturbation/injectors.py | perturbation machinery | c562461b2e58c5c3ebe05d2f650014d4eae2ff994803631d4d0fdfe163891664 |
| post_office/perturbation/judge.py | perturbation machinery | a4d428a174b790c5286214a024a9ce1e8d83b4c32a52c975fdbe1388c35cd231 |
| post_office/perturbation/model.py | perturbation machinery | 5aaf278062e6027fd032e54a626e153f34076141763c41ce87b0056501c0b2c9 |
| post_office/perturbation/openrt_adapter.py | perturbation machinery | 273dff20c6e011783ac2f6b458827da750035aa54a59ff63ddeb34c10254d71f |
| post_office/perturbation/propagation.py | perturbation machinery | 1a6c1fa0726d38c883c995b1d6ce64e026a8c16f937ccace984bfac8bdfde322 |
| post_office/perturbation/replay.py | perturbation machinery | ab7089fac05da0954d941cc5fdea5ea00b3889f95d2b588ee0c4b2e457542a7a |
| post_office/perturbation/script.py | perturbation machinery | 5c6a7ca83a1069367cb2c78481da06e6909b4071ab0dafee7e99b401e25c7888 |
| post_office/perturbation/stimulus.py | perturbation machinery | 92c5829b3c812293c8e665aa0637aa56211227c31862cbb7a620087015c37421 |
| post_office/perturbation/surrogate.py | perturbation machinery | 7ae8b81158bef4c0e6ffaf00944587d48390d5f3020de4fa0b6282c1e600592f |
| post_office/perturbation/uptake.py | perturbation machinery | e6c740a146de5d05048c5279fefbb62fc695ff8b02c5ae477c875c11056749ff |
| post_office/perturbation.py | perturbation machinery | 9385ef80c2f702102133226fc0006a6921771900f0cb4ba9bf59feef94713d6e |
| post_office/stress/autodk.py | experiment tooling | 9a3788cd368eaeee5ec2958b78b427fed9d196baa49d48393f776c75ac1e4fc9 |
| post_office/stress/battery.py | experiment tooling | 71f46e7a6bc517135bb407bd8e652109f13c1ec0b63240ccd7ea5fb6af106eac |
| post_office/stress/collapse_driver.py | experiment tooling | 2a072a3a18d0bea9a6440267f2547cff2daccb94cc468636564db3fe7bd5dbca |
| post_office/stress/discussion_bias.py | experiment tooling | 4b004227ea644335e062a60c2acf9444b82d8019495c66e741f94e0bf311be7e |
| post_office/stress/driver.py | experiment tooling | 0199911f9c4dc061bf07ca37dde502104d0ef591dca25a4089eda9bed75e2385 |
| post_office/stress/effectiveness.py | experiment tooling | b277871251b2fc3253a6be770dbeab38af05e1c341a3355880d51e6f29f9a870 |
| post_office/stress/effectiveness_driver.py | experiment tooling | 52f504e23239c97885eb79cd7b34d61596fb0d452b15692126009f0795b0cac0 |
| post_office/stress/outcome.py | experiment tooling | 1b8b768b768735acd8d7c799496c688b68b4cf8766af75cb73fe6f4167439a71 |
| post_office/stress/precursors.py | experiment tooling | 4b80408ebfb87ac2bae6566003490d86ad27a0f66d04290f88c098e7b1a49851 |
| post_office/stress/pulsed_demo.py | experiment tooling | 42f93af56f5f6c841460f68c5a3f0954c4674893821a5587c70f67b7fca73d6b |
| post_office/ui/discussions.html | UI pages | aa67019c74c294f31419cba664d75497674b28c2c6cf2eda0145b526d38268d1 |
| post_office/ui/settings.html | UI pages | a0202ba0b76832f679e20338bbb649655c94c2b311e50472c9a8ed49acef920b |
| post_office/ui/viewer.html | UI pages | 3f62af64ed8ef55d9fba088b91d5c0b4aad126440c08003c0ebf6e25dd28f72f |
| run.py | experiment tooling | 7beca79a84d1c82c3d13825fb5f241f56ec510e0eda2fd4fa4e58a4184739662 |
| run_discuss.bat | model layer | a6141835460fbd7b51283a24591c7f756ef79e67fab923317d2e7040c89d5c9e |
| scripts/EXP1-IAC-ACTOR.json | frozen attack scripts | fd2866bbb7e5ae72873d671867dcac033ae42c25d83eface12dfe141358969b8 |
| scripts/EXP1A-DRIFT-ACTOR.json | frozen attack scripts | 8612d14ac9e32392f3ecc5007c15452476adcd7c725c0799de431b1559578a3a |
| scripts/HYBRID-OVERLAP-1-SCHEDULING.json | frozen attack scripts | 60636b03a3475f437e868e9590b2f5c7347938051a850e22f6659d72f66f0d16 |
| scripts/HYBRID-OVERLAP-2-SORTING.json | frozen attack scripts | b1fd10e6c523a6ed70ec58a2fa7daf19aaa473c73a529b8209a34d600b91961f |
| scripts/HYBRID-OVERLAP-3-ROUTING.json | frozen attack scripts | 544e92db0cab23959a2ebde989d81048ef9fb9f261eed48ff01a5cd6a1d75900 |
| scripts/HYBRID-SEQ-1-SCHEDULING.json | frozen attack scripts | 708d95c304c1ecb08eb13176e2a01e6de07099f7347f28b630596d9d06d78689 |
| scripts/HYBRID-SEQ-2-SORTING.json | frozen attack scripts | 474e1b329ed17bb50c06233b5b72b21dba8ca322c49a3d4ec98a11e725544dde |
| scripts/HYBRID-SEQ-3-ROUTING.json | frozen attack scripts | 3e6bab167c7fd723702370e7041c761107eab15be967b899a768671bf66403cc |
| scripts/STRESS-RAINBOW-ROUTING.json | frozen attack scripts | 5cfd33568341653d256eff8656f031d95a60659dd4ba3a97ab5e18961bc0cd69 |
| scripts/STRESS-RAINBOW-SCHEDULING.json | frozen attack scripts | 9700862532440b8b14fe12620341ade60490b6bdf611f4e0dc249ad672337f1c |
| scripts/STRESS-RAINBOW-SORTING.json | frozen attack scripts | 4c62646cce524f3fb48cd832d770ea4f14754710d4d473c93846c0280944e3ba |
| scripts/STRESS-XTEAM-1-SCHEDULING.json | frozen attack scripts | 3a23f979dc0ef7bc42024aa79560b814ec5a71174b3fbdc877148a1e81dbb30f |
| scripts/STRESS-XTEAM-2-SORTING.json | frozen attack scripts | 96878b052a006b9d576cbe5dc0fe3fcd801f5f1a206f6ef81536b5fbf20f7bf5 |
| scripts/STRESS-XTEAM-3-ROUTING.json | frozen attack scripts | 3d1b0316b4d8fff8403aa8c7ceefe810dda1a2b47d2b9bd4b5226457bbc4a93d |
| scripts/stress_battery/frozen/EXP1A-DRIFT-ACTOR.json | frozen attack scripts | 8612d14ac9e32392f3ecc5007c15452476adcd7c725c0799de431b1559578a3a |
| scripts/stress_battery/frozen/HYBRID-OVERLAP-1-SCHEDULING.json | frozen attack scripts | 60636b03a3475f437e868e9590b2f5c7347938051a850e22f6659d72f66f0d16 |
| scripts/stress_battery/frozen/HYBRID-OVERLAP-2-SORTING.json | frozen attack scripts | b1fd10e6c523a6ed70ec58a2fa7daf19aaa473c73a529b8209a34d600b91961f |
| scripts/stress_battery/frozen/HYBRID-OVERLAP-3-ROUTING.json | frozen attack scripts | 544e92db0cab23959a2ebde989d81048ef9fb9f261eed48ff01a5cd6a1d75900 |
| scripts/stress_battery/frozen/HYBRID-SEQ-1-SCHEDULING.json | frozen attack scripts | 708d95c304c1ecb08eb13176e2a01e6de07099f7347f28b630596d9d06d78689 |
| scripts/stress_battery/frozen/HYBRID-SEQ-2-SORTING.json | frozen attack scripts | 474e1b329ed17bb50c06233b5b72b21dba8ca322c49a3d4ec98a11e725544dde |
| scripts/stress_battery/frozen/HYBRID-SEQ-3-ROUTING.json | frozen attack scripts | 3e6bab167c7fd723702370e7041c761107eab15be967b899a768671bf66403cc |
| scripts/stress_battery/frozen/L4_FROZEN.json | frozen attack scripts | d919b0d127054769847a4eac0ec7e462915c86c6120e4dca8c47b08f07e0e1f2 |
| scripts/stress_battery/frozen/STRESS-L4F-1-INTAKE.json | frozen attack scripts | 26454fe1fb0989887c78b9367d9db535c0ab4cd3a851661ce3516c1993471b98 |
| scripts/stress_battery/frozen/STRESS-L4F-2-SORTING.json | frozen attack scripts | 5042554d388419600d3c145fbc31afec57526978ac97d325f4e106f12fee98c1 |
| scripts/stress_battery/frozen/STRESS-L4F-3-DISPATCH.json | frozen attack scripts | 92187de439005726353982481722cbe6e1295f330710934506e7a8205e41b297 |
| scripts/stress_battery/frozen/STRESS-L4R-1-SCHEDULING.json | frozen attack scripts | eb8ab3b5a2ed80635f7458768f7ef32dca0afc050c8ff9033114e95cd530bce4 |
| scripts/stress_battery/frozen/STRESS-L4R-2-ROUTING.json | frozen attack scripts | dc6ef6c780e75beba3cde6bdc5631dc58a3ff6364eaff2649ef92a50551c7c29 |
| scripts/stress_battery/frozen/STRESS-L4R-3-RESOURCE.json | frozen attack scripts | b81cbce723e83f120a75b6789f907e33f897f478b2e024e968b965d0c351a6b9 |
| scripts/stress_battery/frozen/STRESS-RAINBOW-ROUTING.json | frozen attack scripts | 5cfd33568341653d256eff8656f031d95a60659dd4ba3a97ab5e18961bc0cd69 |
| scripts/stress_battery/frozen/STRESS-RAINBOW-SCHEDULING.json | frozen attack scripts | 9700862532440b8b14fe12620341ade60490b6bdf611f4e0dc249ad672337f1c |
| scripts/stress_battery/frozen/STRESS-RAINBOW-SORTING.json | frozen attack scripts | 4c62646cce524f3fb48cd832d770ea4f14754710d4d473c93846c0280944e3ba |
| scripts/stress_battery/frozen/STRESS-XTEAM-1-SCHEDULING.json | frozen attack scripts | 3a23f979dc0ef7bc42024aa79560b814ec5a71174b3fbdc877148a1e81dbb30f |
| scripts/stress_battery/frozen/STRESS-XTEAM-2-SORTING.json | frozen attack scripts | 96878b052a006b9d576cbe5dc0fe3fcd801f5f1a206f6ef81536b5fbf20f7bf5 |
| scripts/stress_battery/frozen/STRESS-XTEAM-3-ROUTING.json | frozen attack scripts | 3d1b0316b4d8fff8403aa8c7ceefe810dda1a2b47d2b9bd4b5226457bbc4a93d |
| tests/data/normal_baseline.json | superseded test data | b7df53b59fd83aa5f5543931e4dcd89cbf92bdfd559ba2ad5fbfd357647c1a40 |
| tests/discussion_helpers.py | tests of removed machinery | 82b64f9d8a12bab206e01efa44a47f370e9a040b7056f1d759bd75f19a793c7e |
| tests/test_anthropic_provider.py | tests of removed machinery | 0f1afd2486d4cef282d249fbd81b18f5c82ca0c3c66a461e292aa4dda0dec04f |
| tests/test_attack_experiments_ui.py | tests of removed machinery | f020b6a423dcf2003c9854941cfa3ce0c25ab5d411303798870d24cc96ca2963 |
| tests/test_deterministic_execution.py | tests of removed machinery | a6508dc7fd962ff9153c7d0e3f92f9957383414cbdeb1d2e80a39bdcf9fb8edf |
| tests/test_discussion_agent_hooks.py | tests of removed machinery | 84ed31e0b714caf07fb70af6106b05d6dd9b447977fc82a66818dd9fae355695 |
| tests/test_discussion_api.py | tests of removed machinery | c778e851c8d66dd49bf354e29ed22fbed88c4b8094324ace275e4cfecf47e75e |
| tests/test_discussion_bias.py | tests of removed machinery | ba184195e3175abc2f9da834c270e83932fc4ce279981b2c27cb7bdf8a147439 |
| tests/test_discussion_brain.py | tests of removed machinery | 28d79f0ad2f426e6265ec0a5d3d09dd087259af39f82c96b85b2938171189210 |
| tests/test_discussion_check_tool.py | tests of removed machinery | 31acffc31754fc9caaccf4b09222ad55d1beec865c04178ec75d3a78599b7566 |
| tests/test_discussion_dispatcher.py | tests of removed machinery | b9a39dd64f81c481daa6218c64cdd4bbe1452658164b4155abffa69759dc8e3b |
| tests/test_discussion_manager.py | tests of removed machinery | e703bcc014569e35fc983af0b6eb3b36dec006f018c8d5a543ad5aaf77945992 |
| tests/test_discussion_view.py | tests of removed machinery | f9781e6d81e9effb1ce83bfaa747c0be593f289135312f529c9b0b9657a561d7 |
| tests/test_discussion_wiring.py | tests of removed machinery | 66a989da96506dd8208684104bb1721b7a0ed04bbd203749711e5561d246c0b2 |
| tests/test_dk_effectiveness.py | tests of removed machinery | 8184452369b892c40186535c32c8160d120aacab9e895fd7c84491c82f313554 |
| tests/test_generated_scenarios.py | tests of removed machinery | 871a708cf8656b299fd83f25b980f8578e18d73c207a2b032a4ec8f0b5d5c8ac |
| tests/test_llm_async.py | tests of removed machinery | d41fadb99d984f5fa104d5ce3116807bc6e9ccb1168615aebca996858dc8de88 |
| tests/test_llm_cancel.py | tests of removed machinery | 2b353209d670a87a46db26a2c337e8627ab8bb8640a6b8d73ec11710088123bb |
| tests/test_observability.py | tests of removed machinery | cb12ad9ab427c05242ec1a01821112a0c141a8e24d0cbf6067da7a59387cef93 |
| tests/test_perturbation.py | tests of removed machinery | 7e11966a2c2111d39716625616139373cde849155eddbcd43113c01cc65ad5cc |
| tests/test_perturbation_script.py | tests of removed machinery | 796091a4a15a5580c8ccea4202a1b32da306e9d13f94391454ae9ef602c957af |
| tests/test_scenario.py | tests of removed machinery | 511c8f6ffc693a076bb7124c697d8ee2bd7ef44009d46e979d6cea8045bd0008 |
| tests/test_stress_battery.py | tests of removed machinery | 24df956266ab5501e676b814db03e388710ab57fd020c45cd2f3df10787929b4 |
| tests/test_stress_rct_collapse.py | tests of removed machinery | cb8a4d13589e506e493fbeed1bccb6d36c6df9b6c61a239f502c114f4b80c932 |
| tests/test_stress_reasoning.py | tests of removed machinery | 99d03764f493381d048f2da306a8da6a4b2c75b4ad2e6e485f49b1f0fb478626 |
| tools/async_benchmark.py | experiment tooling | 6da9b1aed95b918ca01c6383eefd68d1bac63ce82b44f140c0ebaf9f9019506e |
| tools/autodk_report.py | experiment tooling | bf669d062666f60979da0759f3c771998316929d1c5f878c1ecbb4d5ad61cd9e |
| tools/calibrate_platform.py | experiment tooling | e6f8f2c36d4f45f4d13905d37072744d88218f3f57c7109b9e139e83a14f1f2d |
| tools/capture_dashboard.py | experiment tooling | 2b9b831f82d97a7e732b2eb46b0f28b8def700f8f070ba2768c8daef7c0a03dc |
| tools/capture_replay.py | experiment tooling | 71f7c69ba3bc81da2e032d140ba95399063f061e55aee3591f71323fde8de18c |
| tools/capture_settings.py | experiment tooling | 5cc74ab6cc842bb6d4e705e0a6682c5bb7a57edb2e62d37db19ed6f1211e069f |
| tools/capture_trace.py | experiment tooling | 030566f5e7af3b351a25de728684446d91e21b470fbd143b77aa6434439828e3 |
| tools/capture_trajectory.py | experiment tooling | 50a3f271686ca8eb3b8af9b6efa6fdc070e20016c5abce617bc69e81d44837dc |
| tools/characterise_modes.py | experiment tooling | 35c800c78055923032cfb0c0c03b6eb2290ec0ca8cf874060aa3fd4d0e206de0 |
| tools/check_generation.py | experiment tooling | 350dc95a0b028076ae0a64d3bed8dbbe4cf72bc2740500262090d91452c0ffa2 |
| tools/check_hybrid.py | experiment tooling | 5c245f653cde8478b4fcf60f00f24385c387c9fb4657088d44abdc04867e166c |
| tools/dashboard_template.html | experiment tooling | e66e799264d32f31c9a8999b32f4d41dd8c9109f82c8ef5fbc15ff3c66ca5415 |
| tools/discussion_check.py | experiment tooling | dc3aca783c05017b6c18f4d10b511636bfa638da43349b6a4aff535687729b2a |
| tools/dk_experiment.py | experiment tooling | a248d647eaff3d30066575ffcee2b77c074eb26949eaffeb088f888f6e1a936d |
| tools/dkrmm_replay.py | experiment tooling | f58a9ae6d8d954924964a1eb71ba802ff066e5f3fa2aac62615885266525b693 |
| tools/dkrmm_template.html | experiment tooling | b3d8d217b0cc437504160aacadc7b2c53e33b2fae237a9722105ac8fb144fa89 |
| tools/experiment_analysis.py | experiment tooling | 15770f77b5b83d86494b8f4ba54d7aa4143ee8f278ddec12e19ba14408bdd13f |
| tools/experiment_index.py | experiment tooling | 57c2e9662416ec38ee3164276ae8116676665d93941f8cb0153682617a898a92 |
| tools/experiment_report.py | experiment tooling | 208405a2cef2aa1db13355ca9c45eccc67614e617b022006c4a359904c52759e |
| tools/experiment_summary.py | experiment tooling | 17cc4cec4874cae8e0c1e9ae9443f599baa1f46232b34257d652b01f95228799 |
| tools/experiment_template.html | experiment tooling | 1d8a182a0929ed80e8fa87d557ff5e6d19b079a349e5005906d5412ebf7a6435 |
| tools/experiment_view.py | experiment tooling | a35fac03809c26d230e405b68ced7250d705320c775650fb5d1e7d2b295a95f3 |
| tools/final_report.py | experiment tooling | 8c094f5661f6d822671ef2e02b902230a0f0846dabda7ac5a50175912bc5f2ef |
| tools/freeze_l4_scripts.py | experiment tooling | e661605a22b287c69e8d47ea1f879d7a756dcf725a076041009b08191ca6a94f |
| tools/generate_script.py | experiment tooling | 8fd818e28ea86f47d632446009224a21240b4ec0e63bc56101090809cdd95d7d |
| tools/generate_stress_scripts.py | experiment tooling | d31c43db82b93dd2f00a6515fa47ac7438d4eb13c2ec919ce76fe141653bf0b1 |
| tools/history_template.html | experiment tooling | eb6a4d634b1f4eb084d01d1afcf239d87697fd80d37f641fb038d8a05539a422 |
| tools/hybrid_finish.py | experiment tooling | afe3b990077d2a7997665eb68550ccf66fafb69cb9ac49364124f6d5831b5977 |
| tools/hybrid_finish2.py | experiment tooling | 4e297b808e9cc9c0a762690340bddedde6f2963e54bf27425a2a9fa1b74d759d |
| tools/hybrid_plans.py | experiment tooling | 325e43d027a6c8e47b56a24830bf39cbbe0b314cd48ed2f1ff9f8721ab99d24b |
| tools/hybrid_run.py | experiment tooling | 37b4b4dddd9205e8d9b7c8553ccd8924f369d586bd535d8fd49fd785bbda291c |
| tools/operational_gap.py | experiment tooling | add197187b4e35f986d0c7022032da03fc5e2daa471d7d4d077c96b3338e9c95 |
| tools/pstar_pilot_summary.py | experiment tooling | 39039c9268cbc8a98fdc68cc64a864b6c5672c33d7d62b9df7d066bfa75ee6a4 |
| tools/reasoning_report.py | experiment tooling | ebf8fde8701da44d562930cdaf77a2c017933791e77f2384334bb7c13cab98bd |
| tools/repro_test_deterministic.py | experiment tooling | 0c654a0ba5b084e74bb7190ce2142a3f56ac64327b1b71f3b3eb0530805898c7 |
| tools/run_autodk.py | experiment tooling | 0e27ad4d5509de33012f6688e61039bc74de25d38abb49f73720baf64a6ba918 |
| tools/run_battery.py | experiment tooling | 94643c0993681b7f979b303cfeb6a94e0bbbbba084c4ce917dd328411145aa9c |
| tools/run_discussion_bias.py | experiment tooling | 8c4a9d517d52f38e8d893711d2cb4f2c6a255bdbc884104713e932e49fd6ad78 |
| tools/run_dk_effectiveness.py | experiment tooling | dd819e707c00c76e838a09c62be555a06799ded279fbd079ca9e95c28bdebe41 |
| tools/run_hybrid_battery.py | experiment tooling | 62d87b23830b4d7b743ce49b69a46a2c1249a3c27be770290fc579b254583ad9 |
| tools/run_stress_battery.py | experiment tooling | da3547fd7bd1698793e06e3709e8e11289833f784616daa152a6b8baddbd570e |
| tools/run_stress_rct_collapse.py | experiment tooling | 20952375cfc4880545429c502e99591b567407520f9fd9cc7081101f0f01c5f3 |
| tools/stub_provider.py | experiment tooling | 10be114d4b016677f613267c802f880f87d5da90c9264c67aa0a528256ce17f4 |
| tools/trace_template.html | experiment tooling | c97f8ab9b61b95f1a350c9ffd7da853bbed1afd0659f738cefea93c940710b3a |
| tools/uptake_test.py | experiment tooling | fe76b394e90a9b660173560348159ac988050e2282dbc96d0e11b508e31cdd0a |
| tools/validate_normal.py | experiment tooling | 7d77ed9fc8daaa05a9b6194b91de49b65d0acdb61e344c4a633ec4f48652008b |
| tools/verify_dkrmm.py | experiment tooling | a0a99552be9236b46912c7a8add8ea48b8a25a12dc0d55f06a53ab523cc1b2c1 |

## Not copied

| source path | reason |
| --- | --- |
| post_office/agents/llm_async-1.py | review artifact: the user's saved copy of a reviewed patch, imported by nothing in the source package. It is in the user's source directory (ruling recorded in the build ledger) and absent from the read-only mirror this record was hashed from, so no source sha256 is given. |

## Trimmed tests

The simulator, rules, gate, peer-map and DK-RMM tests were copied from the source
`tests/` (LF-normalised). This record lists every change made to them in Task 2.

### Trimmed tests

One line per deleted test function: file, test name, reason.

| file | item | reason |
| --- | --- | --- |
| tests/test_urgent_route.py | test_an_attack_run_keeps_the_recorded_route_even_if_asked_otherwise | schedules a perturbation; the perturbation controller is removed |
| tests/test_discussion_peers.py | test_the_three_discussion_messages_exist | asserts MessageType.DISCUSS_*; replaced by CONSULT_* in this project |
| tests/test_decision_pipeline.py | test_normal_llm_is_the_normal_facility_with_the_always_policy | the `normal_llm` preset and its scenario are removed (settings has only `default`) |
| tests/test_gates.py | test_both_clerks_are_in_the_catalogue | uses `observability.tools`, which is removed (only `observability.context` is carried) |
| tests/test_dkrmm.py | test_the_monitor_is_served_and_the_gate_is_a_person_only_door | needs `post_office.api` (server/runner), which is not part of this task; Task 9 carries the API tests (restored in Task 9, see below) |
| tests/test_dkrmm.py | test_a_run_over_the_api_is_watched_without_being_altered | needs `post_office.api.runner.SimulationRunner`, not part of this task; Task 9 carries the API tests (restored in Task 9, see below) |
| tests/test_agents.py | test_the_probe_says_plainly_when_the_answer_came_from_the_rules | exercises the removed model brain's `probe` (removed framework) |
| tests/test_agents.py | test_the_probe_asks_a_question_of_the_shape_the_agents_ask | exercises the removed model brain's `parse` (removed framework) |
| tests/test_discussion_prompts.py | test_a_single_answer_after_a_closing_reasoning_tag_is_read | exercises the removed model brain's `parse`/`_reason` (removed framework); Task 5 `crew/parse.py` covers the case |

### Listed files not copied

| file | item | reason |
| --- | --- | --- |
| tests/test_header_digest.py | whole file | imports `post_office.api.digest` (Task 9) and `post_office.perturbation.model` (removed) at module level; most of it tests the perturbation digest, which is removed. Its `monitor_digest` cases belong with the Task 9 API tests. (carried in Task 9 without the removed digest's tests, see below) |

### Rewritten lines in carried tests

Settings now has only the `default` preset. Lines that named a source preset were rewritten;
nothing else in those files changed. `config("busy")` -> `busy_config()` and `config("normal")` ->
`config("default")` give the same dictionary as the source (`tests/presets.py` holds the source's
`busy` overrides, `arrival_interval` 20.0 and `initial_parcels` 16). `interactive_config(...)` ->
`normal_config()` is equivalent on the rules path only: the new dict drops `llm_async`/`discussions`
and adds `interceptors: []`.

| file | what |
| --- | --- |
| tests/test_ecosystem.py | import `busy_config` |
| tests/test_ecosystem.py | the source preset `config("busy")` -> `busy_config()` (tests/presets.py, same values) |
| tests/test_vehicles.py | import `busy_config` |
| tests/test_vehicles.py | the source preset `config("busy")` -> `busy_config()` (tests/presets.py, same values) |
| tests/test_throughput.py | import `busy_config` in place of the now unused `config` |
| tests/test_throughput.py | the source preset `config("busy")` -> `busy_config()` (tests/presets.py, same values) |
| tests/test_paid_service.py | import `busy_config` in place of the now unused `config` |
| tests/test_paid_service.py | the source preset `config("busy")` -> `busy_config()` (tests/presets.py, same values) |
| tests/test_queued_assignment.py | import `busy_config` in place of the now unused `config` |
| tests/test_queued_assignment.py | the source preset `config("busy")` -> `busy_config()` (tests/presets.py, same values) |
| tests/test_dispatch_priority.py | the source preset `config("busy")` -> `busy_config()` (tests/presets.py, same values) |
| tests/test_priority.py | the source preset `config("busy")` -> `busy_config()` (tests/presets.py, same values) |
| tests/test_urgent_route.py | import `normal_config` in place of `api.runner.interactive_config` |
| tests/test_urgent_route.py | drop the `perturbation` import (used only by the trimmed attack-run test) |
| tests/test_urgent_route.py | `api.runner.interactive_config(config("normal"))` -> `normal_config()` (equivalent on the rules path; the new dict drops `llm_async`/`discussions` and adds `interceptors: []`) |
| tests/test_urgent_route.py | the source alias `config("normal")` -> `config("default")` (same dictionary) |
| tests/test_discussion_peers.py | the source alias `config("normal")` -> `config("default")` (same dictionary) |
| tests/test_discussion_briefings.py | import `normal_config` in place of `api.runner.interactive_config` |
| tests/test_discussion_briefings.py | `api.runner.interactive_config(config("normal"))` -> `normal_config()` (equivalent on the rules path; the new dict drops `llm_async`/`discussions` and adds `interceptors: []`) |
| tests/test_discussion_briefings.py | the source alias `config("normal")` -> `config("default")` (same dictionary) |
| tests/test_policy_gate.py | proposal source label renamed to the CrewAI form (the removed framework's name may not appear) |
| tests/test_dkrmm.py | import `busy_config` |
| tests/test_dkrmm.py | the source preset `config("busy")` -> `busy_config()` (tests/presets.py, same values) |
| tests/test_discussion_peers.py | added `SOURCE_PEER_MAP` and `test_peer_map_is_the_source_table_verbatim` (brief Step 8) |

### Task 9: the API and UI tests

The source `tests/test_api.py`, `tests/test_controls.py` and `tests/test_header_digest.py` were
copied (LF-normalised) and trimmed of the routes spec 16 removes; the two DK-RMM API tests
Task 2 deleted are restored in `tests/test_dkrmm.py`. One line per deleted test function:
file, test name, reason.

| file | item | reason |
| --- | --- | --- |
| tests/test_api.py | test_an_operator_command_travels_the_message_bus | `runner.command_robot` and `POST /robots/{id}/command` are not in spec 16 |
| tests/test_api.py | test_commanding_a_robot_that_does_not_exist_is_refused_not_raised | `runner.command_robot` is not in spec 16 |
| tests/test_api.py | test_one_agent_reports_its_children_and_its_recent_messages | `GET /agents/{id}` is not in spec 16 |
| tests/test_api.py | test_one_robot_reports_its_position_battery_and_errands | `GET /robots/{id}` is not in spec 16 |
| tests/test_api.py | test_a_missing_thing_is_a_404_rather_than_a_crash | `GET /robots/{id}`, `/agents/{id}`, `/tasks/{id}` are not in spec 16 |
| tests/test_api.py | test_a_parcel_endpoint_returns_its_whole_conversation | `GET /parcels`, `/parcels/{id}` are not in spec 16 |
| tests/test_api.py | test_communications_can_be_filtered_to_one_parcel | `GET /parcels`, `/communications` are not in spec 16 |
| tests/test_api.py | test_the_simulation_can_be_stepped_over_http | `POST /simulation/step` is not in spec 16 (the carried tests step with `runner.step`) |
| tests/test_api.py | test_a_policy_change_takes_effect_and_is_recorded | `POST /simulation/policy` is not in spec 16 |
| tests/test_api.py | test_an_empty_policy_change_is_rejected | `POST /simulation/policy` is not in spec 16 |
| tests/test_api.py | test_a_task_can_be_injected_from_outside_the_hierarchy | `POST /tasks` is not in spec 16 |
| tests/test_api.py | test_an_injected_task_for_an_unknown_parcel_is_a_400 | `POST /tasks` is not in spec 16 |
| tests/test_api.py | test_the_settings_never_return_the_key | `POST /settings` and `/settings/reset` are removed (spec 16) |
| tests/test_api.py | test_a_run_with_no_trace_says_so_rather_than_erroring | the trace and `/ui/trace`, `/ui/trajectory` are removed |
| tests/test_api.py | test_a_model_can_be_put_behind_agents_over_http | `POST /settings/agents` is removed; asserts the removed framework's brain name |
| tests/test_api.py | test_changing_the_agents_starts_a_new_run | `POST /settings/agents` is removed |
| tests/test_api.py | test_the_agents_endpoint_refuses_an_agent_a_model_does_not_belong_behind | `POST /settings/agents` is removed |
| tests/test_api.py | test_an_empty_list_puts_every_agent_back_on_its_rules | `POST /settings/agents` is removed; asserts the removed framework's brain name |
| tests/test_api.py | test_a_model_backed_run_keeps_deciding_when_the_provider_is_unreachable | `POST /settings`, `/settings/agents` are removed and it drives the removed framework's brain; the CrewBrain fallback path is covered by the consultation fallback tests |
| tests/test_api.py | test_the_settings_panel_is_served_and_asks_for_nothing_else | `GET /settings/ui` (the settings panel) is removed |
| tests/test_api.py | test_anthropic_offers_a_model_without_being_asked_for_a_key | `GET /settings/providers` is removed |
| tests/test_api.py | test_an_empty_settings_change_is_rejected | `POST /settings` is removed |
| tests/test_api.py | test_changing_the_settings_is_itself_an_operator_action | `POST /settings` and `GET /actions` are removed |
| tests/test_api.py | test_the_tools_endpoint_describes_and_counts_them | `GET /tools` (trace-backed) is removed |
| tests/test_api.py | test_the_trace_can_be_tailed_by_row_id | `GET /trace` is removed; tailing the log is `GET /events?after=` (test_api_trimmed.py) |
| tests/test_api.py | test_one_parcel_is_one_request | `GET /trace/{id}` and `/parcels` are removed |
| tests/test_api.py | test_an_operator_action_has_an_owner_and_survives_a_refusal | `GET /actions`, `POST /robots/{id}/command`, `/simulation/policy` are removed |
| tests/test_api.py | test_a_policy_change_records_both_sides | `GET /actions`, `POST /simulation/policy` are removed |
| tests/test_api.py | test_a_reset_starts_a_new_run_rather_than_appending_to_the_old_one | `GET /runs`, `/trace` are removed; a reset's new run id is held by test_runner.py and test_api_trimmed.py |
| tests/test_api.py | test_a_probe_that_names_no_provider_never_echoes_the_key | `POST /settings/probe` is removed |
| tests/test_api.py | test_the_session_and_the_run_know_about_each_other | `/sessions`, `/runs` are removed |
| tests/test_api.py | test_the_trace_is_open_before_the_first_tick | the trace is removed |
| tests/test_api.py | test_a_second_launch_does_not_append_to_the_first_ones_run | the trace database is removed |
| tests/test_api.py | test_a_run_with_no_trace_keeps_the_name_it_was_given | the trace is removed |
| tests/test_api.py | test_the_trajectory_tail_returns_rows_the_page_can_append | `/ui/trajectory/tail` is removed |
| tests/test_api.py | test_the_trajectory_page_follows_the_run_rather_than_photographing_it | `/ui/trajectory` is removed |
| tests/test_api.py | test_a_new_run_takes_a_free_name_however_many_runs_came_before | the trace database is removed |
| tests/test_api.py | test_the_trajectory_shows_the_live_run_and_tails_it | `/ui/trajectory` is removed |
| tests/test_api.py | test_an_old_run_can_be_read_but_is_never_tailed | `/ui/trajectory` (history replay) is removed |
| tests/test_api.py | test_the_live_run_is_never_served_as_finished | `/ui/trajectory` is removed |
| tests/test_api.py | test_the_history_lists_every_run_and_marks_the_live_one | `/ui/history` is removed |
| tests/test_api.py | test_one_broken_extra_does_not_take_out_the_whole_monitor_tab | reads the removed disturbance schedule and propagation tracer (`eco.propagation`) |
| tests/test_api.py | test_a_pace_a_sleep_can_time_runs_one_tick_at_a_time | `runner.ticks_per_sleep` (tick batching) is not part of the Task 8 runner |
| tests/test_api.py | test_a_faster_pace_batches_and_keeps_the_rate_it_names | `ticks_per_sleep`, `MIN_SLEEP` are not part of the Task 8 runner |
| tests/test_api.py | test_a_very_small_pace_is_capped_rather_than_unbounded | `ticks_per_sleep`, `MAX_BATCH` are not part of the Task 8 runner |
| tests/test_api.py | test_no_pacing_still_runs_one_tick_at_a_time | `ticks_per_sleep` is not part of the Task 8 runner |
| tests/test_api.py | test_an_rct_reading_can_be_explained_from_the_run_itself | `GET /dkrmm/explain` and `/ui/dkrmm` are not in spec 16 |
| tests/test_api.py | test_every_rct_of_the_run_is_listed_with_when_it_was_detected | `GET /dkrmm/rcts` and `/ui/dkrmm` are not in spec 16 |
| tests/test_controls.py | test_the_scenario_can_be_switched_without_restarting_the_server | resets to the removed `busy` and `stress` presets; the one preset is `default`, and every other preset is refused (test_api_trimmed.py `test_only_the_default_scenario_can_be_chosen`, test_controls.py `test_an_unknown_scenario_is_refused_rather_than_guessed`) |
| tests/test_header_digest.py | test_every_family_has_an_entry_point_and_a_description | `SEAM_OF`/`DOES` and the removed `perturbation.model.FAMILIES` |
| tests/test_header_digest.py | test_the_descriptions_promise_a_mechanism_and_not_an_outcome | `DOES`, part of the removed disturbance digest |
| tests/test_header_digest.py | test_a_facility_with_nothing_scheduled_says_none | `perturbation_digest` is removed |
| tests/test_header_digest.py | test_due_and_injected_are_not_the_same_sentence | `perturbation_digest` and the removed `stress` preset |
| tests/test_header_digest.py | test_the_digest_says_where_the_stimulus_entered | `perturbation_digest` and the removed `stress` preset |
| tests/test_header_digest.py | test_provenance_stays_three_answers_rather_than_one_source | `perturbation_digest` and the removed `stress` preset |
| tests/test_header_digest.py | test_nothing_measured_yet_is_a_statement_and_not_a_blank | `perturbation_digest` and the removed `stress` preset |
| tests/test_header_digest.py | test_a_depth_never_travels_without_its_relation | `perturbation_digest` and the removed `stress` preset |
| tests/test_header_digest.py | test_more_than_one_in_force_is_counted | `perturbation_digest` and the removed `stress` preset |
| tests/test_header_digest.py | test_the_digest_carries_every_scheduled_disturbance | `perturbation_digest` and the removed `stress` preset |
| tests/test_header_digest.py | test_each_row_carries_its_own_phase_and_its_own_consequence | `perturbation_digest` and the removed `stress` preset |
| tests/test_header_digest.py | test_the_lead_row_is_one_of_the_rows_and_not_a_fourth_thing | `perturbation_digest` and the removed `stress` preset |
| tests/test_header_digest.py | test_the_shell_can_open_the_whole_schedule | the shell's disturbance schedule strip is removed |
| tests/test_header_digest.py | test_the_shell_paints_both_from_the_summary | renamed `test_the_shell_paints_the_verdict_from_the_summary`; its `paintPerturbation` half removed with the strip |
| tests/test_header_digest.py | test_the_summary_endpoint_offers_both_digests | renamed `test_the_summary_endpoint_offers_the_monitor_digest`; its `perturbation_digest` half removed with the digest |

#### Rewritten lines in the Task 9 carried tests

| file | what |
| --- | --- |
| tests/test_api.py, tests/test_controls.py | the fixtures set `server.runner = SimulationRunner(..., trace_db=..., session_id=...)`; now `server.use(SimulationRunner(..., rules_only=True))` (the Prototype II runner has no trace, and the module builds no runner at import) |
| tests/test_api.py | every `SimulationRunner(...)` gains `rules_only=True` and drops `trace=`, `trace_db=`, `session_id=` (not parameters of the Task 8 runner) |
| tests/test_api.py | `test_every_read_endpoint_answers_with_json` parametrize list trimmed to the spec 16 routes `/state`, `/events`, `/summary` |
| tests/test_api.py | `test_every_tracking_endpoint_answers_with_json` parametrize list trimmed to `/settings` |
| tests/test_api.py | `test_the_address_people_actually_type_serves_the_ui` asserts `GET /` serves the page (200) instead of redirecting to `/ui` (spec 16: `GET /` is the live page) |
| tests/test_api.py | `test_every_page_of_the_live_ui_is_served` parametrize list trimmed to `/` |
| tests/test_api.py | `test_no_served_page_repeats_an_element_id` scans `/` and the floor page (`live.robots_html`), which the shell carries as an escaped `srcdoc`, instead of `/ui`, `/ui/simple`, `/settings/ui` |
| tests/test_api.py | `test_the_live_shell_names_the_pages_it_mounts` checks the shell names the endpoints it polls (`/frame`, `/consultations`, `/llm/calls`, `/dkrmm/*`, `/settings`, `/ws`, `/summary`) instead of the removed `/ui/*` pages |
| tests/test_api.py | `test_the_floor_follows_the_run_one_frame_at_a_time` reads `/frame` (was `/ui/frame`), its key set adds `run_id`, `roster`, `llm_agents`, `busy`, `in_flight`, and it steps with `server.runner.step(4)` (was `POST /simulation/step`) |
| tests/test_api.py | `test_the_built_file_and_the_served_page_share_their_builders` reads `/frame` and asserts the built frame's keys are a subset of the served one's |
| tests/test_api.py | `test_the_settings_say_whether_any_agent_is_actually_using_a_model` drops the `workspace`, `tools` and `llm_wanted` keys (not in spec 16's `/settings`) |
| tests/test_api.py | `test_the_stream_answers_at_both_of_its_names` connects to `/ws` only (`WS /events` is not in spec 16) and still checks `GET /events` |
| tests/test_api.py | `test_the_websocket_opens_with_the_whole_state_then_streams` steps with `server.runner.step(2)` (was `POST /simulation/step`) |
| tests/test_api.py | `test_the_shell_offers_a_control_for_a_run_that_starts_paused` reads `/` (was `/ui`) |
| tests/test_api.py | `test_the_monitor_tab_renders_normally` and `test_a_failed_monitor_tab_shows_why_rather_than_four_words` read `/` (the DK-RMM pane is part of the shell; `/ui/dkrmm` is not in spec 16), and a failed pane leaves the page a 200 with the pane saying what it lost |
| tests/test_api.py | the pacing tests' comments drop the batching account (the Task 8 runner sleeps once per tick); `test_every_tick_is_broadcast_once_and_in_order`, `test_stopping_during_a_batch_is_not_deferred_to_the_end_of_it` and `test_the_pace_does_not_change_the_run` are otherwise as in the source |
| tests/test_controls.py | `config("busy")` -> `busy_config()` (tests/presets.py, same values) |
| tests/test_controls.py | `test_the_clock_speed_can_be_set_and_read_back` reads `tick_seconds` from `/summary` (`GET /simulation/speed` is not in spec 16) |
| tests/test_controls.py | `test_a_new_run_gets_a_new_seed_and_starts_over` steps with `server.runner.step(30)` (was `POST /simulation/step`) |
| tests/test_header_digest.py | imports `monitor_digest` only (no `perturbation_digest`, `SEAM_OF`, `DOES`, `perturbation.model`) |
| tests/test_dkrmm.py | `test_the_monitor_is_served_and_the_gate_is_a_person_only_door` reads `/dkrmm/state` (was `/dkrmm`), drives the gate over the wire as the source did (`POST /dkrmm/activate` refused before validation, now with 409, then `POST /dkrmm/validate` and `/dkrmm/activate`), also asserts the state reads `ACTIVE` afterwards, and reads `/` for the page (was `/ui/dkrmm`); runner built with `rules_only=True, config=busy_config()`, docstring names the trajectory and RCT log design's section 5. (Task 9 had asserted the three gate POSTs were 404, since spec 16 served no gate; the trajectory and RCT log design serves them, and its Task 2 put the source's assertions back.) |
| tests/test_dkrmm.py | `test_a_run_over_the_api_is_watched_without_being_altered` compares against `build(..., config=busy_config(), scenario="default")` (was `interactive_config(config("busy"))`): the Task 8 runner uses its configuration verbatim and builds with the scenario of its preset |

### Trajectory and RCT log, Task 1: the RCT explainer, log and recorder tests

The source `tests/test_rct_explain.py`, `tests/test_rct_log.py` and `tests/test_run_record.py`
were copied (LF) and adapted: discussions are consultations here, Normal is the one preset,
and the runner's recording (`record_dir`, `recorder`, `record_gate`) and the RCT log routes
come in Task 2 of the plan. One line per deleted test function: file, test name, reason.

| file | item | reason |
| --- | --- | --- |
| tests/test_rct_log.py | test_the_log_endpoint_lists_this_run_and_earlier_ones | needs `SimulationRunner(record_dir=...)` and `GET /dkrmm/rct-log`, which Task 2 adds; covered there by `tests/test_api_rcts.py` |
| tests/test_rct_log.py | test_the_log_endpoint_counts_rcts_per_scenario | needs the runner's recorder and `GET /dkrmm/rct-log` (Task 2); it also asserts the removed `stress` scenario |
| tests/test_rct_log.py | test_the_shell_has_an_rct_log_tab | needs the shell's RCT log tab and `GET /ui/rcts` (Tasks 3 and 4) |
| tests/test_run_record.py | test_without_a_record_folder_nothing_is_written | asserts `runner.recorder is None` and calls `runner.record_gate()`, which Task 2 adds; covered there by `tests/test_recording.py` |

#### Rewritten lines in the Task 1 carried tests

| file | item | reason |
| --- | --- | --- |
| tests/test_rct_explain.py |  | module docstring says "consultations" for "discussions" |
| tests/test_rct_explain.py |  | imports `pytest`, `tests.consult_helpers` (`ask`, `ecosystem_on`, `equally_placed`, `events`) and `tests.fake_ollama.deciding_script` for the added test |
| tests/test_rct_explain.py |  | the `discussion(...)` helper builds a consultation as `crew/events.py` writes it: `consult_opened` (actor owner, target peer, correlation the id; detail `consultation_id`, `peer`, `decision`, `options`), a `message` of type `CONSULT_REQUEST` (content `consultation_id`, `decision`, `text`; no options, as in a run), and `consult_closed` (detail `consultation_id`, `decision`, `outcome`, `choice`), in place of `discussion_opened`, `DISCUSS_OPEN` and `discussion_closed` |
| tests/test_rct_explain.py | test_a_discussion_on_the_same_task_is_a_strong_link_and_a_shared_robot_a_weak_one | two asserts added: `discussion_messages == 2` (the two `CONSULT_REQUEST` messages) and the summary says "strongly linked to a consultation" |
| tests/test_rct_explain.py |  | added test_an_open_consultation_keeps_the_options_it_was_opened_with: an open consultation (opened with options T-1/T-2, a CONSULT_REQUEST without options, no close) and a trouble event on T-1; the row is `open`, `closed` None, `strong >= 1` (pins reading options from `consult_opened` and the guard that a request without options keeps them) |
| tests/test_rct_explain.py |  | added test_a_consultation_with_no_peer_names_its_owner_alone: a peerless consultation leading the strong links is named by its owner alone in the summary, with no arrow |
| tests/test_rct_explain.py |  | added test_a_consultation_of_a_fake_model_run_is_explained_with_its_links: 60 ticks on the fake Ollama (`deciding_script`), a SCHEDULING consultation forced as the live UI tests force it if none arose, and the last consultation's row in `explain(...)["discussions"]` carries its id, owner, peer, decision, outcome, ticks and integer strong/weak counts; `discussion_messages` equals the window's `CONSULT_*` message rows |
| tests/test_rct_log.py |  | imports `settings.scenario_label` in place of `api.runner.SimulationRunner` and `dkrmm.states.OperationalState` (used only by the deleted fixture's tests) |
| tests/test_rct_log.py | test_each_listed_rct_names_its_scenario | the Normal label is `scenario_label()` (was "Normal Ecosystem"); the unknown `stress_actorattack` is labelled by its own name (was "Stress-ActorAttack") |
| tests/test_rct_log.py |  | the `recording_client` fixture deleted with the three tests that used it |
| tests/test_run_record.py |  | `runner_in` builds a `Recorded` (a NORMAL ecosystem from `build(seed=3, config=normal_config(), run_id="rec", log_path=..., scenario="default")`, `DKRMM(eco).attach()` and a `RunRecorder(root, run_id, scenario, seed=3, config={"llm_agents": []})`, stepped eco, monitor, recorder each tick as the source runner did) in place of `SimulationRunner(record_dir=...)` |
| tests/test_run_record.py | test_the_dkrmm_record_is_written_as_the_run_goes | asserts `record["control"] is True` |
| tests/test_run_record.py | test_each_rct_says_which_scenario_it_was_detected_in | runs the Normal preset (was `preset="stress"`): `scenario` is `normal`, `scenario_label` is `scenario_label()` in the RCT file and the record, and the record's `scenario` is the preset `default` |
| tests/test_run_record.py |  | added test_an_unknown_preset_is_recorded_under_its_own_name: the source's `stress` half of the test above, with `stress` as its own label (there is no stress preset) |
| tests/test_run_record.py |  | added test_the_normal_label_names_the_model_it_is_given: `scenario_of("default", model=...)` and `RunRecorder(..., model=...)` label Normal with `scenario_label(model)` |
| tests/test_run_record.py | test_a_gate_decision_is_kept_in_the_record | `runner.recorder.write(runner.monitor)` in place of `runner.record_gate()` (Task 2) |

### Trajectory and RCT log, Tasks 2 to 5: the carried tests changed again

| file | what |
| --- | --- |
| tests/test_dkrmm.py | the gate test's 404 loop replaced by the source's over-the-wire gate assertions (see the Task 9 entry above) |
| tests/test_rct_explain.py | added test_an_early_readings_window_starts_at_tick_0_whose_events_it_counts: a reading at tick 21 reports the window `[0, 21]` (the source reported `[-38, 21]`) and counts its tick-0 events |
| tests/test_rct_explain.py | added test_two_readers_of_a_fresh_cache_each_get_the_log_once: two threads read one 30000-line log through `events_from_log` on a fresh cache, four times; each gets every event once (unique `seq` count equals the length), both get the same events, the cache's offset is the file's size, and clearing a returned list leaves the cache whole |
| tests/test_rct_explain.py, tests/test_run_record.py | unchanged otherwise; the tests the Task 1 entries above say were deleted for want of the runner's recorder and routes are covered by the new `tests/test_recording.py` and `tests/test_api_rcts.py`, and the shell's RCT log tab by `tests/test_live_ui.py` |

The Task 9 entries above that give `GET /dkrmm/explain`, `GET /dkrmm/rcts`, `/ui/trajectory`
or `/ui/trajectory/tail` as not served record why those source tests were deleted then. The
trajectory and RCT log design serves these routes again. The deleted tests are not restored:
all but one also read the source's trace store or its `/ui/dkrmm` page, which are still not
part of this project, and the one that does not
(`test_the_trajectory_page_follows_the_run_rather_than_photographing_it`) is matched by
`tests/test_trajectory.py::test_the_page_is_the_template_filled_with_the_live_run`.
`tests/test_api_rcts.py` and `tests/test_trajectory.py` cover the routes as served here.

## Notes

Facts about files classified `unchanged` that a reader of the copied text
should know, recorded here rather than by editing the copied file.

| file | what |
| --- | --- |
| post_office/discussion/briefings.py | copied unchanged from the source, but its module docstring's claim "Read on the peer's tick ..., never from a worker thread" no longer holds in Prototype II. A consultation's owner runs in a worker thread (`crew/consultation.py`), and the peer's briefing is read from that worker, inside the owner's tool use (`crew/tools.py`), while the tick's thread is blocked in `join` waiting for it. It is still the floor as it is at the moment of the consultation, because the tick is not moving; and the read is made under the consultation service's lock and only while the consultation is open, so a worker abandoned at its deadline never reads the live world while the tick has moved on. |

### Adapted from a different source path

`tools/provenance.py` pairs a file with the source file at the same relative
path unless `tools/write_provenance.py::SOURCE_PATHS` names another one; that
map gives the `replaced` files the source file each takes over from (spec 2.1)
and gives the file below the source it was adapted from, so the Files table
shows those source paths and hashes. What was changed is recorded here.

| file | what |
| --- | --- |
| post_office/ui/floor.html | adapted from the source `tools/replay_template.html` (the floor, the interaction graph, the robot cards and the message feed that the source's `ui/live.py::robots_html` served at `/ui/robots`). The discussion strip, links, bubbles and log are removed (Prototype II consults through CrewAI and its frames carry no discussion rows), consultation messages (`CONSULT_*`) take the feed's highlight that discussion turns had, and the run line no longer claims every decision is deterministic. It is served inside the live page as an escaped `srcdoc`, so it needs no route of its own. |

### The runtime communication taxonomy (2026-10-02)

The second iteration added a labelling layer over the event log (the design
`docs/superpowers/specs/2026-10-02-runtime-communication-taxonomy-design.md` and
its plan). Its files, and the one class that changed:

| file | what |
| --- | --- |
| post_office/communication/taxonomy.py | new; the taxonomy (channels, types, `classify`, `table()`), a pure module with no source counterpart. |
| post_office/ui/feed.py | new; the Runtime communication pane's rules as pure functions over event dicts, mirrored by `ui/live.html`'s JavaScript. |
| tools/taxonomy_table.py | new; prints the interaction type table of `docs/events.md` from `taxonomy.table()`. |
| tests/test_taxonomy.py, tests/test_taxonomy_completeness.py, tests/test_event_stamping.py, tests/test_dkrmm_stamping_invariance.py, tests/test_api_taxonomy.py, tests/test_feed_integrity.py | new; the tests of the taxonomy design's section 8. |
| post_office/communication/bus.py | was `unchanged`, now `adapted`: the `message` / `subagent_message` event's detail gains `in_reply_to` (the message's own field, or ""); nothing else in the file differs from the source. |
| post_office/communication/events.py, post_office/ui/views.py, post_office/api/server.py, post_office/ui/live.html, post_office/ui/floor.html, post_office/ui/live.py, tools/normal_fingerprint.py | `adapted` before and after; changed again for the stamp (`Event` slots, `emit`), the `/frame` rows, `GET /taxonomy`, the Runtime communication tab and the typed graph, and the stamp filter beside `STRIP`. |

### The trajectory and RCT log panes (2026-10-02)

The third iteration brought back the source's trajectory page, its RCT log page and the three
observability modules behind them (the design
`docs/superpowers/specs/2026-10-02-trajectory-and-rct-log-design.md` and its plan). Their five
source files leave the Removed table, and so do the three source tests carried with them:

| file | what |
| --- | --- |
| post_office/observability/rct_explain.py | adapted; discussions are consultations (`consult_opened`, `consult_closed`, the `CONSULT_REQUEST` message, `CONSULT_*` messages counted), a consultation's options are kept from its opening when its request names none, a peerless lead consultation is named by its owner alone, and the reported window starts at tick 0 at the earliest (`[max(0, T - WINDOW + 1), T]`; the source reported a negative first tick for an early reading, whose tick-0 events it counted). `events_from_log` holds a module lock over its read and cache update and returns a copy of the cached list (the source's unlocked cache let two threads reading one log append its events twice). The result keys, kinds, links and baseline are the source's. |
| post_office/observability/rct_log.py | unchanged; the design called it adapted, but the one change it allowed (`scenario_of` from `.run_record`) is already the source's import, so the file is byte-identical. |
| post_office/observability/run_record.py | adapted; `scenario_of` reads Normal from `config.settings` (with an optional model for the label), the record is built with `control=True`, and two comments no longer name removed machinery. |
| post_office/ui/rcts.html | adapted; every user-visible "discussion" reads "consultation", em-dashes became hyphens, the leading comment no longer names a removed scenario family or discussions, and a consultation with no peer is shown by its owner alone, with no arrow. |
| post_office/ui/trajectory.html | adapted from the source `tools/trajectory_template.html` (paired in `tools/write_provenance.py::SOURCE_PATHS` and `ELSEWHERE`, as `ui/floor.html` is); the lanes map sub-agent requests and replies to tools and `simulation/*` to the operator, the discussion view is the Expert consultation view drawn from consultation and `llm_call` rows, the tail sends the page's run and stops on a 409, the link to the source's history page is removed, em-dashes and a literal NUL became a hyphen and `\u0000`, and a consultation with no peer is labelled by its owner alone, with no arrow. |
| tests/test_rct_explain.py, tests/test_rct_log.py, tests/test_run_record.py | adapted; carried and changed as `docs/provenance_trimmed_tests.md` lists. |
| tests/test_recording.py, tests/test_api_rcts.py, tests/test_trajectory.py | new. |
| post_office/observability/__init__.py | new; the package docstring. |
| post_office/api/runner.py, post_office/api/server.py, post_office/ui/views.py, post_office/ui/live.py, post_office/ui/live.html, main.py, tests/test_dkrmm.py | `adapted` before and after; changed again for the recorder, the seven DK-RMM routes and the three page routes, the trajectory rows, the two tabs and the gate, `--record-dir` and `--no-record`, and the gate test's over-the-wire assertions. |
| tests/test_api_trimmed.py, tests/test_live_ui.py | `new` before and after; the route table gains the ten routes, and the browser tests cover the two tabs, the gate and the explanation. |
| post_office/dkrmm/ | unchanged, and pinned by its tree hash in `tests/test_api_rcts.py`. |

### The C2-NEAR-SYSTEM-OVERRIDE experiment (2026-10-11)

A collapse-only experiment isolated from the Normal scenario (the design
`docs/superpowers/specs/2026-10-11-c2-near-system-override-design.md`, the report
`docs/c2-near-system-override.md`). Its files, and the two files that changed:

| file | what |
| --- | --- |
| post_office/stress/__init__.py, post_office/stress/c2near_system_override.py, post_office/stress/operational.py, post_office/stress/system_override.py, post_office/stress/measure.py, post_office/stress/collapse.py, post_office/stress/analysis.py | new; the experiment definition, the scheduled faults, the System Override campaign, the per-tick measurement, the collapse criterion and the attack-outcome join. `__init__.py` and `collapse.py` share a relative path with files of the source's removed `stress` package (experiment tooling), so the Files table shows the same-path source file's hash beside them and those two source paths no longer appear under Removed; the code is new and reads nothing from the source. |
| tools/run_c2near_system_override.py, tests/test_c2near_system_override.py, docs/c2-near-system-override.md | new; the driver, the 41 tests of the brief, the report. |
| post_office/crew/interception.py | `new` before and after; `from_config` returns the campaign as the agent hooks when a configuration carries a non-empty `c2near_system_override` block, and `Interception.inert()` as before otherwise. |
| post_office/simulation/ecosystem.py | `adapted` before and after; `_install_crew` calls `bind(eco)` on agent hooks that have one (the Normal `AgentHooks` has none), and `_install_interception` lists the key under the `interception` event's `active` when it is present (`[]` otherwise, as before). |
| post_office/stress/report.py, post_office/ui/c2near_report.html, tools/c2near_report.py, tests/test_c2near_report.py | new; the experiment's results page, one standalone HTML file made from a results directory (no server, no network; nothing under `results/normal` read or written), and its tests. |
| post_office/observability/zone_backlog.py, post_office/observability/decision_trace.py, post_office/observability/experiment.py, tests/test_live_experiment.py | new; the live M-S-DROP experiment's instrumentation: the backlog by zone per tick, the decision-to-action traces linked by identifiers only, and the run directory kept by the live runner under `--experiment-dir` (the layout `tools/run_collapse_scenarios.py` writes), with their tests. Read-only: no event is emitted, and a run's event stream is the same with them as without. |
| post_office/communication/bus.py | `adapted` before and after; `watch_inbox` adds read-only observers of `inbox` (called with the receiver, the tick and the messages taken; an empty list costs one `if`), used by the decision traces as the evidence that a message reached its receiver on time. |
| post_office/api/runner.py, post_office/api/server.py, post_office/ui/live.py, post_office/ui/live.html, main.py, tests/test_api_trimmed.py | `adapted` (the test: `new`) before and after; changed again for `stop_at` and `experiment_dir` (`--stop-at`, `--experiment-dir`), the zone series and the tracer beside every run, `GET /zones`, `GET /decision-traces` and `/summary`'s `kept`, the zone chart in the DK-RMM pane, the Decision to action table under the consultations and the kept-run line on the study strip; the route table gains the two routes. |
| docs/ms-drop-model-enabled-v1.md, docs/img/ms-drop-crewai-v3.svg, docs/img/ms-drop-zone-backlog-rules.svg, tools/zone_backlog_figure.py | new; version 1 of the M-S-DROP model-enabled report kept as it was when version 2 replaced `docs/ms-drop-model-enabled.md`, the version 3 schema, the per-seed zone figure of the rules-only live runs and the script that draws it (standard library only). |
| docs/img/ms-drop-zone-backlog-model.svg | new; the per-seed zone figure of the model-enabled live runs (made through the page on the user's machine), drawn by `tools/zone_backlog_figure.py`. |
| docs/dkrmm-backlog-level-deviation.md | new; the report of `backlog_level_deviation`, a DK-RMM indicator added and withdrawn on 2026-10-13, kept as the record of what was measured. |
| tests/test_dk_view.py | new; the live page's DK word (an RCT reading whose dragon-king test held), on the study strip, the badges, the DK-RMM tab and the API fields behind them. |
| tests/test_ms_stall.py | new; M-S-STALL, the fifth collapse scenario (every message held from 1800 and all delivered at 2100): the registry, the rule, the four scenarios unchanged, one rules-only run on seed 13 with what DK-RMM read, and the live page. |
| docs/img/ms-stall-dk-seed13-model.svg, tools/ms_stall_dk_figure.py | new; the schema of why the live page shows DK on the user's model-enabled M-S-STALL seed 13 run (record results/live/dkrmm/api-6-8.json) and the script that draws it from that record (standard library only). |
| docs/img/ms-stall-steps-seed13-model.svg, tools/ms_stall_steps_figure.py | new; the step-by-step schema of the user's model-enabled M-S-STALL seed 13 run (Normal, the slow task at 1641, the stall, the RCT shown as DK at 1881, the build-up, the release, the catch-up, the recovery) and the script that draws it from results/live/dkrmm/api-6-8.json (standard library only). |
