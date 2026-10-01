# Provenance

## Source identity

- Source commit: no git repository
- source_tree_sha256: b8ef01c738db9f84bcf1664ad39dfacb86a8b81226366db30342643d21588474
- source_tree_sha256_at_start: b8ef01c738db9f84bcf1664ad39dfacb86a8b81226366db30342643d21588474
- Date: 2026-10-01

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
| docs/camel-removal.md | new |  |  |
| docs/consultation.md | new |  |  |
| docs/crewai-ollama.md | new |  |  |
| docs/dkrmm.md | new |  |  |
| docs/events.md | new |  |  |
| docs/limitations.md | new |  |  |
| docs/perturbation-seams.md | new |  |  |
| docs/provenance.json | new |  |  |
| docs/provenance.md | new |  |  |
| docs/provenance_classification.json | new |  |  |
| docs/provenance_notes.md | new |  |  |
| docs/provenance_trimmed_tests.md | new |  |  |
| docs/running.md | new |  |  |
| docs/superpowers/plans/2026-10-01-prototype-ii-implementation-plan.md | new |  |  |
| docs/superpowers/specs/2026-10-01-prototype-ii-crewai-ollama-design.md | new |  |  |
| docs/verification.md | new |  |  |
| main.py | adapted | main.py | 8baed660dfe95c8af04cd57574c748b3afdf92f46b91aedd6a9814d81af5fc23 |
| post_office/__init__.py | new | post_office/__init__.py | 863f3f72fd18f93ef2eb1bc95f271ed2a3a34710ac69bd374163f817e9d59e32 |
| post_office/agents/__init__.py | adapted | post_office/agents/__init__.py | 8fa78aa155123d7f5009961d2312ceda36dc9d5b44ff84072933d5fab151d9eb |
| post_office/agents/assignment_metrics.py | unchanged | post_office/agents/assignment_metrics.py | fa4fe216eb98609db9309dbf04691e5c4b762654d3c36adf845abde2111e1bd6 |
| post_office/agents/base.py | adapted | post_office/agents/base.py | a03a514b2003adda9ff963fee4319071473aad056593181d55032a2d9c25e0d2 |
| post_office/agents/brain.py | adapted | post_office/agents/brain.py | 50410aae4af071423da9e87cfa3091685f53fa93bef740b52c11f0e3d80fd922 |
| post_office/agents/deferral.py | replaced |  |  |
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
| post_office/communication/bus.py | unchanged | post_office/communication/bus.py | 595eca2b45d2816c2ed31b599be8e962ef5c20ff0c5346743de08c27b5f86570 |
| post_office/communication/directory.py | unchanged | post_office/communication/directory.py | 320d996b6c703620a8c725dfad22da617e61a14c2d57081507cca33fdcab2bfd |
| post_office/communication/events.py | adapted | post_office/communication/events.py | f82dce0907e359e88d486024fcbbec616b4a0ca9186c491c67389edbe70eeafa |
| post_office/communication/message.py | adapted | post_office/communication/message.py | f380eb74c68e13d0b2d5180e27c0868dddd291015f88698857fbf5a06bcb6714 |
| post_office/communication/provenance.py | unchanged | post_office/communication/provenance.py | c39ef03439d8aed4b4534f9ea3a3266f0907e4d0d5fd3eff1f52d15c71433af7 |
| post_office/communication/topics.py | unchanged | post_office/communication/topics.py | d99d52889fe43338713c26d2ab82f546b0fccd410ff2afb465828e146bea41b7 |
| post_office/config/__init__.py | adapted | post_office/config/__init__.py | 6591670a7c26d2b675d4cafbad0fdcac765ac6a377f1a665bc3f3968dee5dc35 |
| post_office/config/ollama.py | new |  |  |
| post_office/config/settings.py | adapted | post_office/config/settings.py | ca13210faf1a0163d726b6f44f55cb6267be6f69b064e8d7e6d35b492e810641 |
| post_office/core/__init__.py | unchanged | post_office/core/__init__.py | 289e9528ee6ac26d8784352deba4b85d30bec5511b96045fa1165411a015f404 |
| post_office/core/ids.py | unchanged | post_office/core/ids.py | 65393c4e93748ec47398f781bdf30857b6c26d417815b216110fefa5044c7378 |
| post_office/core/rng.py | unchanged | post_office/core/rng.py | 0f380ece390064587b51bcf48716e41d47330a8f90f311af91971932837e92fd |
| post_office/core/visible.py | unchanged | post_office/core/visible.py | 2e70896fa015972a9c635354190dcea1065605170804dd1ab42f154a52cfd8f3 |
| post_office/core/world.py | unchanged | post_office/core/world.py | bd8b3e21dacd63a4cd8eff68797e1a3c25a4612897bb55b6b2a7dfec8ea17eeb |
| post_office/crew/__init__.py | new |  |  |
| post_office/crew/audit.py | new |  |  |
| post_office/crew/brain.py | new |  |  |
| post_office/crew/console.py | new |  |  |
| post_office/crew/consultation.py | new |  |  |
| post_office/crew/events.py | new |  |  |
| post_office/crew/identity.py | new |  |  |
| post_office/crew/interception.py | new |  |  |
| post_office/crew/llm.py | new |  |  |
| post_office/crew/parse.py | new |  |  |
| post_office/crew/roles.py | new |  |  |
| post_office/crew/tools.py | new |  |  |
| post_office/discussion/__init__.py | adapted | post_office/discussion/__init__.py | d8d0414ee82525c079e7488b860ce09a9b656e1bd79d0bb25e064f7b4b91086c |
| post_office/discussion/briefings.py | unchanged | post_office/discussion/briefings.py | fcf1f69be4bd3496e29bf086fec6ea3ba94e51d94e3ac69a587fde8e2e9fb22a |
| post_office/discussion/peers.py | unchanged | post_office/discussion/peers.py | 44cc7043d000eae88e1959d4fce570b09bebc8a61cbf11a3aee90458d5263727 |
| post_office/discussion/prompts.py | unchanged | post_office/discussion/prompts.py | f0e67185e88adc6fc8f263be74e51b8b202ebcf803415d7f4988546cb7f6d725 |
| post_office/dkrmm/__init__.py | unchanged | post_office/dkrmm/__init__.py | 9a883f6af1e136d70e3a09493487ff8527f3f62455292d066ce4d4dcd3449127 |
| post_office/dkrmm/indicators.py | unchanged | post_office/dkrmm/indicators.py | e7dcee122a8524c4665a15062c598d67297d2d8a5d389e9bff11e3d13ea180b9 |
| post_office/dkrmm/monitor.py | unchanged | post_office/dkrmm/monitor.py | b27b918ab8137d7b1e9f321c26cc01ab2b05d7aa52c1318c7fc87225203d63c7 |
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
| post_office/tasks/__init__.py | unchanged | post_office/tasks/__init__.py | 4c8cb6ab0f714f0c9cb7250bcc8945e379d4eba85b06913afee31d042dfb91ae |
| post_office/tasks/registry.py | unchanged | post_office/tasks/registry.py | a7050a9124175330893842b636616218ee3318260b4fd069f885b59ad4a6902f |
| post_office/tasks/task.py | unchanged | post_office/tasks/task.py | df760aa00fa1e8b44cf39f1461cc2529eb4c6b2ff15b1de5699f95d7736940fc |
| post_office/ui/__init__.py | adapted | post_office/ui/__init__.py | 3973b855d7da8162d5cce8913577489e5950593ec1b722702eac48f34215c6e4 |
| post_office/ui/floor.html | adapted |  |  |
| post_office/ui/live.html | adapted | post_office/ui/live.html | a7a5f8cbed3a2bb4b3b43c887b110ac6752d31360975d329496e3703e3c57cd8 |
| post_office/ui/live.py | adapted | post_office/ui/live.py | 0799d6f836d7fbd3de7d8cf7ee0c5c88095fedb3381542dc49b23c75ad17242a |
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
| tests/test_api_trimmed.py | new |  |  |
| tests/test_base_sync_decide.py | new |  |  |
| tests/test_charging.py | unchanged | tests/test_charging.py | 7b9513ea35b07687c94dda99fff3c2b933fcb4a0820025abfbf6c7dd22e6dac7 |
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
| tests/test_dkrmm.py | adapted | tests/test_dkrmm.py | 2ea9bb2f99f9307281e64ec1c4e509dc283fcfc30aa2374db494f582c55a78dd |
| tests/test_dkrmm_independence.py | new |  |  |
| tests/test_dkrmm_receives_consultations.py | new |  |  |
| tests/test_dkrmm_record.py | unchanged | tests/test_dkrmm_record.py | 44e23d5dcf263a3d6b048cc31f2e01c07eb80e209b7773f8e6111e8350d7e357 |
| tests/test_docs_present.py | new |  |  |
| tests/test_ecosystem.py | adapted | tests/test_ecosystem.py | 20d580d17022e15b23a01718192b510c6effaafcd95c0e2e1557eea3072c47b4 |
| tests/test_ecosystem_normal_guards.py | new |  |  |
| tests/test_environment.py | unchanged | tests/test_environment.py | ed1ab8b90988bd3ce6fb3a65c8b0b40f48db22addfb415458b6ce0a2163ca9de |
| tests/test_events_consultation.py | new |  |  |
| tests/test_fake_ollama.py | new |  |  |
| tests/test_gates.py | adapted | tests/test_gates.py | f6c9e8ca665210924d523cb1b1c29eb2956461947034cc7eeb05b477db389354 |
| tests/test_header_digest.py | adapted | tests/test_header_digest.py | cc53486223e58cdabe4b7ebbb00270fc2d8843fd2032a39f7007c85cf2184148 |
| tests/test_judgement.py | unchanged | tests/test_judgement.py | 4142d04aaf03b65efb57346d1a3ea48875fe684b982482cabd98f6c071ed3b9e |
| tests/test_live_ui.py | new |  |  |
| tests/test_llm_call_logging.py | new |  |  |
| tests/test_model_identity.py | new |  |  |
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
| tests/test_reasoning_trigger.py | unchanged | tests/test_reasoning_trigger.py | a752dc59c55796c4debecae95805994a372b20fc97331effd719548f539a73fd |
| tests/test_recovery.py | unchanged | tests/test_recovery.py | e54e1bc8540e6c1335040fe98cf7031b139daddd0789f312c100cf3f0bc5881e |
| tests/test_resource_priority.py | unchanged | tests/test_resource_priority.py | 87f71d1d63dc52c3a04ef5b937630201a2871b1697281321e9af043bba4a6c05 |
| tests/test_robots.py | unchanged | tests/test_robots.py | add4734efe6f97d78a7347ada51d8679e1cbe2f00148604362ea19b9a2630928 |
| tests/test_roles_preserved.py | new |  |  |
| tests/test_rules_first.py | new |  |  |
| tests/test_run_normal_tool.py | new |  |  |
| tests/test_runner.py | new |  |  |
| tests/test_seams_noop.py | new |  |  |
| tests/test_simulator_authority.py | new |  |  |
| tests/test_sorting_process.py | unchanged | tests/test_sorting_process.py | 2634ff5c12e2f8d16bcb43a9ee05ac11b52b9096a864553690229733562c2bbc |
| tests/test_throughput.py | adapted | tests/test_throughput.py | 538ff2d4523ca82bfa864b2675408cfaeb1b5cc1b68cb3fd5cd265ae50274975 |
| tests/test_urgent_route.py | adapted | tests/test_urgent_route.py | 725c37605e90ef243195a8e59de9aaddaabe522f94b7ec5d4e8a2fa6c7783595 |
| tests/test_validation.py | unchanged | tests/test_validation.py | 85ea72f78a107310daa38ee7f5f3da7ebf8c11b709a9e9854f3d3c3b5fedbe27 |
| tests/test_vehicles.py | adapted | tests/test_vehicles.py | 248eff6ffaecd3e5133dd1fae10683d652bcd85258aa11cf37809119049ad3f7 |
| tests/test_where_judgement_lives.py | unchanged | tests/test_where_judgement_lives.py | d9d7f4b9656e631da4e37f40d6546cb6f58e116b1813c003edd1157cdcf6b22c |
| tools/normal_fingerprint.py | adapted | tools/normal_fingerprint.py | 5680976f3d0503f60e94b92816466a7eca54d463ca5a5df63c06927f20b5fdf8 |
| tools/provenance.py | new |  |  |
| tools/run_normal.py | new |  |  |
| tools/verify_ollama.py | new |  |  |
| tools/write_provenance.py | new |  |  |

Classes: `unchanged` (byte-identical to the source file except for line endings, normalised to LF), `adapted` (copied and changed), `replaced` (a new file that takes over a removed source file's job), `new` (no source counterpart).

## Removed

Every file of the source `post_office/` package that has no counterpart in this project, with its reason class.

- model layer: the source's model framework, asynchronous dispatch, response cache, provider factory and discussion manager; replaced by `post_office/crew/` and `config/ollama.py`.
- perturbation machinery: attacks, injections and biased discussions; no perturbation is part of this phase (see docs/perturbation-seams.md).
- experiment tooling: stress batteries, experiment families, the trace store and the RCT explainers; Normal is the only scenario and the event log and `results/` files replace the trace.
- UI pages: pages of the source UI that served removed features; the consultation, Ollama and DK-RMM panes of `ui/live.html` replace them.

| source path | reason class | source sha256 |
| --- | --- | --- |
| post_office/agents/camel_brain.py | model layer | 73e248ebc4eeda9daa98015c1e2bd3b5f8f6bf3bd00fcde2f43f76990db9a6bf |
| post_office/agents/llm_async.py | model layer | 503db4fb088c3a9911d5a2f404e358503eaf11cc2c56d0a7432a695736c53721 |
| post_office/agents/response_cache.py | model layer | 2b5f065a2b3e6204fb7e0a440ca6430e034aff23dfa235ead0ef9908f83be8cb |
| post_office/api/injections.py | perturbation machinery | 2ec2999d7dc226e4f0aa74832b8bb050cd9060cbe936f64649b4e0180ea987b6 |
| post_office/config/experiments.py | experiment tooling | 8c60b1da8fd77dd098a87a14246e68b72722e868f00bf3a8d12ec082012fed22 |
| post_office/config/providers.py | model layer | 654ff78be71e5454fdb826bd06e21e95e0f685915e03c6eac518f25e181bd04b |
| post_office/discussion/bias.py | perturbation machinery | 297aece5fa167a47cced4bb579b95bca162e18a4deaf163524a08075aa310b94 |
| post_office/discussion/manager.py | model layer | 975b9724352163f03db191d46edee9eb3239c0c6bb7823107fa7a4613a4081d3 |
| post_office/observability/instrumentation.py | model layer | c6fe975dbc1bfcc42471658d9550bede4d644d5fda3274bfdd1577271186d9f8 |
| post_office/observability/rct_explain.py | experiment tooling | 8c82265f3070144439af375f62e0323a75f5832a7839647d986bafca4d79cdcc |
| post_office/observability/rct_log.py | experiment tooling | 9e3f5bb241762c493bf10eb9125e40f536616fc572327e2f253338f3cb213efc |
| post_office/observability/run_record.py | experiment tooling | 677a3226c36ed2f922147bda343763eee9745790c803730efdb4043370d7954d |
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
| post_office/stress/__init__.py | experiment tooling | cf8707ce438257f5028f6bce44768ecdcae7ead1553faffe7795f51eb4ab37da |
| post_office/stress/autodk.py | experiment tooling | 9a3788cd368eaeee5ec2958b78b427fed9d196baa49d48393f776c75ac1e4fc9 |
| post_office/stress/battery.py | experiment tooling | 71f46e7a6bc517135bb407bd8e652109f13c1ec0b63240ccd7ea5fb6af106eac |
| post_office/stress/collapse.py | experiment tooling | f6ec9e7abf3ae413efa254faac852b48ecfc011a9b7a3aa6566af1b24f9931f8 |
| post_office/stress/collapse_driver.py | experiment tooling | 2a072a3a18d0bea9a6440267f2547cff2daccb94cc468636564db3fe7bd5dbca |
| post_office/stress/discussion_bias.py | experiment tooling | 4b004227ea644335e062a60c2acf9444b82d8019495c66e741f94e0bf311be7e |
| post_office/stress/driver.py | experiment tooling | 0199911f9c4dc061bf07ca37dde502104d0ef591dca25a4089eda9bed75e2385 |
| post_office/stress/effectiveness.py | experiment tooling | b277871251b2fc3253a6be770dbeab38af05e1c341a3355880d51e6f29f9a870 |
| post_office/stress/effectiveness_driver.py | experiment tooling | 52f504e23239c97885eb79cd7b34d61596fb0d452b15692126009f0795b0cac0 |
| post_office/stress/outcome.py | experiment tooling | 1b8b768b768735acd8d7c799496c688b68b4cf8766af75cb73fe6f4167439a71 |
| post_office/stress/precursors.py | experiment tooling | 4b80408ebfb87ac2bae6566003490d86ad27a0f66d04290f88c098e7b1a49851 |
| post_office/stress/pulsed_demo.py | experiment tooling | 42f93af56f5f6c841460f68c5a3f0954c4674893821a5587c70f67b7fca73d6b |
| post_office/ui/discussions.html | UI pages | aa67019c74c294f31419cba664d75497674b28c2c6cf2eda0145b526d38268d1 |
| post_office/ui/rcts.html | UI pages | d50df474b984699ddcd5509b80f445750e60b01dfe0de3d8a6690c9b53b21294 |
| post_office/ui/settings.html | UI pages | a0202ba0b76832f679e20338bbb649655c94c2b311e50472c9a8ed49acef920b |
| post_office/ui/viewer.html | UI pages | 3f62af64ed8ef55d9fba088b91d5c0b4aad126440c08003c0ebf6e25dd28f72f |

## Not copied

| source path | reason |
| --- | --- |
| post_office/agents/llm_async-1.py | review artifact: the user's saved copy of a reviewed patch, imported by nothing in the source package. It is in the user's source directory (ruling recorded in the build ledger) and absent from the read-only mirror this record was hashed from, so no source sha256 is given. |

## Trimmed tests

The simulator, rules, gate, peer-map and DK-RMM tests were copied from the source
`tests/` (LF-normalised). This file records every change made to them in Task 2.

### Trimmed tests

One line per deleted test function: file, test name, reason.

- tests/test_urgent_route.py :: test_an_attack_run_keeps_the_recorded_route_even_if_asked_otherwise :: schedules a perturbation; the perturbation controller is removed
- tests/test_discussion_peers.py :: test_the_three_discussion_messages_exist :: asserts MessageType.DISCUSS_*; replaced by CONSULT_* in this project
- tests/test_decision_pipeline.py :: test_normal_llm_is_the_normal_facility_with_the_always_policy :: the `normal_llm` preset and its scenario are removed (settings has only `default`)
- tests/test_gates.py :: test_both_clerks_are_in_the_catalogue :: uses `observability.tools`, which is removed (only `observability.context` is carried)
- tests/test_dkrmm.py :: test_the_monitor_is_served_and_the_gate_is_a_person_only_door :: needs `post_office.api` (server/runner), which is not part of this task; Task 9 carries the API tests (restored in Task 9, see below)
- tests/test_dkrmm.py :: test_a_run_over_the_api_is_watched_without_being_altered :: needs `post_office.api.runner.SimulationRunner`, not part of this task; Task 9 carries the API tests (restored in Task 9, see below)
- tests/test_agents.py :: test_the_probe_says_plainly_when_the_answer_came_from_the_rules :: exercises the removed model brain's `probe` (removed framework)
- tests/test_agents.py :: test_the_probe_asks_a_question_of_the_shape_the_agents_ask :: exercises the removed model brain's `parse` (removed framework)
- tests/test_discussion_prompts.py :: test_a_single_answer_after_a_closing_reasoning_tag_is_read :: exercises the removed model brain's `parse`/`_reason` (removed framework); Task 5 `crew/parse.py` covers the case

### Listed files not copied

- tests/test_header_digest.py :: whole file :: imports `post_office.api.digest` (Task 9) and `post_office.perturbation.model` (removed) at module level; most of it tests the perturbation digest, which is removed. Its `monitor_digest` cases belong with the Task 9 API tests. (carried in Task 9 without the removed digest's tests, see below)

### Rewritten lines in carried tests

Settings now has only the `default` preset. Lines that named a source preset were rewritten;
nothing else in those files changed. `config("busy")` -> `busy_config()` and `config("normal")` ->
`config("default")` give the same dictionary as the source (`tests/presets.py` holds the source's
`busy` overrides, `arrival_interval` 20.0 and `initial_parcels` 16). `interactive_config(...)` ->
`normal_config()` is equivalent on the rules path only: the new dict drops `llm_async`/`discussions`
and adds `interceptors: []`.

- tests/test_ecosystem.py :: import `busy_config`
- tests/test_ecosystem.py :: the source preset `config("busy")` -> `busy_config()` (tests/presets.py, same values)
- tests/test_vehicles.py :: import `busy_config`
- tests/test_vehicles.py :: the source preset `config("busy")` -> `busy_config()` (tests/presets.py, same values)
- tests/test_throughput.py :: import `busy_config` in place of the now unused `config`
- tests/test_throughput.py :: the source preset `config("busy")` -> `busy_config()` (tests/presets.py, same values)
- tests/test_paid_service.py :: import `busy_config` in place of the now unused `config`
- tests/test_paid_service.py :: the source preset `config("busy")` -> `busy_config()` (tests/presets.py, same values)
- tests/test_queued_assignment.py :: import `busy_config` in place of the now unused `config`
- tests/test_queued_assignment.py :: the source preset `config("busy")` -> `busy_config()` (tests/presets.py, same values)
- tests/test_dispatch_priority.py :: the source preset `config("busy")` -> `busy_config()` (tests/presets.py, same values)
- tests/test_priority.py :: the source preset `config("busy")` -> `busy_config()` (tests/presets.py, same values)
- tests/test_urgent_route.py :: import `normal_config` in place of `api.runner.interactive_config`
- tests/test_urgent_route.py :: drop the `perturbation` import (used only by the trimmed attack-run test)
- tests/test_urgent_route.py :: `api.runner.interactive_config(config("normal"))` -> `normal_config()` (equivalent on the rules path; the new dict drops `llm_async`/`discussions` and adds `interceptors: []`)
- tests/test_urgent_route.py :: the source alias `config("normal")` -> `config("default")` (same dictionary)
- tests/test_discussion_peers.py :: the source alias `config("normal")` -> `config("default")` (same dictionary)
- tests/test_discussion_briefings.py :: import `normal_config` in place of `api.runner.interactive_config`
- tests/test_discussion_briefings.py :: `api.runner.interactive_config(config("normal"))` -> `normal_config()` (equivalent on the rules path; the new dict drops `llm_async`/`discussions` and adds `interceptors: []`)
- tests/test_discussion_briefings.py :: the source alias `config("normal")` -> `config("default")` (same dictionary)
- tests/test_policy_gate.py :: proposal source label renamed to the CrewAI form (the removed framework's name may not appear)
- tests/test_dkrmm.py :: import `busy_config`
- tests/test_dkrmm.py :: the source preset `config("busy")` -> `busy_config()` (tests/presets.py, same values)
- tests/test_discussion_peers.py :: added `SOURCE_PEER_MAP` and `test_peer_map_is_the_source_table_verbatim` (brief Step 8)

### Task 9: the API and UI tests

The source `tests/test_api.py`, `tests/test_controls.py` and `tests/test_header_digest.py` were
copied (LF-normalised) and trimmed of the routes spec 16 removes; the two DK-RMM API tests
Task 2 deleted are restored in `tests/test_dkrmm.py`. One line per deleted test function:
file, test name, reason.

- tests/test_api.py :: test_an_operator_command_travels_the_message_bus :: `runner.command_robot` and `POST /robots/{id}/command` are not in spec 16
- tests/test_api.py :: test_commanding_a_robot_that_does_not_exist_is_refused_not_raised :: `runner.command_robot` is not in spec 16
- tests/test_api.py :: test_one_agent_reports_its_children_and_its_recent_messages :: `GET /agents/{id}` is not in spec 16
- tests/test_api.py :: test_one_robot_reports_its_position_battery_and_errands :: `GET /robots/{id}` is not in spec 16
- tests/test_api.py :: test_a_missing_thing_is_a_404_rather_than_a_crash :: `GET /robots/{id}`, `/agents/{id}`, `/tasks/{id}` are not in spec 16
- tests/test_api.py :: test_a_parcel_endpoint_returns_its_whole_conversation :: `GET /parcels`, `/parcels/{id}` are not in spec 16
- tests/test_api.py :: test_communications_can_be_filtered_to_one_parcel :: `GET /parcels`, `/communications` are not in spec 16
- tests/test_api.py :: test_the_simulation_can_be_stepped_over_http :: `POST /simulation/step` is not in spec 16 (the carried tests step with `runner.step`)
- tests/test_api.py :: test_a_policy_change_takes_effect_and_is_recorded :: `POST /simulation/policy` is not in spec 16
- tests/test_api.py :: test_an_empty_policy_change_is_rejected :: `POST /simulation/policy` is not in spec 16
- tests/test_api.py :: test_a_task_can_be_injected_from_outside_the_hierarchy :: `POST /tasks` is not in spec 16
- tests/test_api.py :: test_an_injected_task_for_an_unknown_parcel_is_a_400 :: `POST /tasks` is not in spec 16
- tests/test_api.py :: test_the_settings_never_return_the_key :: `POST /settings` and `/settings/reset` are removed (spec 16)
- tests/test_api.py :: test_a_run_with_no_trace_says_so_rather_than_erroring :: the trace and `/ui/trace`, `/ui/trajectory` are removed
- tests/test_api.py :: test_a_model_can_be_put_behind_agents_over_http :: `POST /settings/agents` is removed; asserts the removed framework's brain name
- tests/test_api.py :: test_changing_the_agents_starts_a_new_run :: `POST /settings/agents` is removed
- tests/test_api.py :: test_the_agents_endpoint_refuses_an_agent_a_model_does_not_belong_behind :: `POST /settings/agents` is removed
- tests/test_api.py :: test_an_empty_list_puts_every_agent_back_on_its_rules :: `POST /settings/agents` is removed; asserts the removed framework's brain name
- tests/test_api.py :: test_a_model_backed_run_keeps_deciding_when_the_provider_is_unreachable :: `POST /settings`, `/settings/agents` are removed and it drives the removed framework's brain; the CrewBrain fallback path is covered by the consultation fallback tests
- tests/test_api.py :: test_the_settings_panel_is_served_and_asks_for_nothing_else :: `GET /settings/ui` (the settings panel) is removed
- tests/test_api.py :: test_anthropic_offers_a_model_without_being_asked_for_a_key :: `GET /settings/providers` is removed
- tests/test_api.py :: test_an_empty_settings_change_is_rejected :: `POST /settings` is removed
- tests/test_api.py :: test_changing_the_settings_is_itself_an_operator_action :: `POST /settings` and `GET /actions` are removed
- tests/test_api.py :: test_the_tools_endpoint_describes_and_counts_them :: `GET /tools` (trace-backed) is removed
- tests/test_api.py :: test_the_trace_can_be_tailed_by_row_id :: `GET /trace` is removed; tailing the log is `GET /events?after=` (test_api_trimmed.py)
- tests/test_api.py :: test_one_parcel_is_one_request :: `GET /trace/{id}` and `/parcels` are removed
- tests/test_api.py :: test_an_operator_action_has_an_owner_and_survives_a_refusal :: `GET /actions`, `POST /robots/{id}/command`, `/simulation/policy` are removed
- tests/test_api.py :: test_a_policy_change_records_both_sides :: `GET /actions`, `POST /simulation/policy` are removed
- tests/test_api.py :: test_a_reset_starts_a_new_run_rather_than_appending_to_the_old_one :: `GET /runs`, `/trace` are removed; a reset's new run id is held by test_runner.py and test_api_trimmed.py
- tests/test_api.py :: test_a_probe_that_names_no_provider_never_echoes_the_key :: `POST /settings/probe` is removed
- tests/test_api.py :: test_the_session_and_the_run_know_about_each_other :: `/sessions`, `/runs` are removed
- tests/test_api.py :: test_the_trace_is_open_before_the_first_tick :: the trace is removed
- tests/test_api.py :: test_a_second_launch_does_not_append_to_the_first_ones_run :: the trace database is removed
- tests/test_api.py :: test_a_run_with_no_trace_keeps_the_name_it_was_given :: the trace is removed
- tests/test_api.py :: test_the_trajectory_tail_returns_rows_the_page_can_append :: `/ui/trajectory/tail` is removed
- tests/test_api.py :: test_the_trajectory_page_follows_the_run_rather_than_photographing_it :: `/ui/trajectory` is removed
- tests/test_api.py :: test_a_new_run_takes_a_free_name_however_many_runs_came_before :: the trace database is removed
- tests/test_api.py :: test_the_trajectory_shows_the_live_run_and_tails_it :: `/ui/trajectory` is removed
- tests/test_api.py :: test_an_old_run_can_be_read_but_is_never_tailed :: `/ui/trajectory` (history replay) is removed
- tests/test_api.py :: test_the_live_run_is_never_served_as_finished :: `/ui/trajectory` is removed
- tests/test_api.py :: test_the_history_lists_every_run_and_marks_the_live_one :: `/ui/history` is removed
- tests/test_api.py :: test_one_broken_extra_does_not_take_out_the_whole_monitor_tab :: reads the removed disturbance schedule and propagation tracer (`eco.propagation`)
- tests/test_api.py :: test_a_pace_a_sleep_can_time_runs_one_tick_at_a_time :: `runner.ticks_per_sleep` (tick batching) is not part of the Task 8 runner
- tests/test_api.py :: test_a_faster_pace_batches_and_keeps_the_rate_it_names :: `ticks_per_sleep`, `MIN_SLEEP` are not part of the Task 8 runner
- tests/test_api.py :: test_a_very_small_pace_is_capped_rather_than_unbounded :: `ticks_per_sleep`, `MAX_BATCH` are not part of the Task 8 runner
- tests/test_api.py :: test_no_pacing_still_runs_one_tick_at_a_time :: `ticks_per_sleep` is not part of the Task 8 runner
- tests/test_api.py :: test_an_rct_reading_can_be_explained_from_the_run_itself :: `GET /dkrmm/explain` and `/ui/dkrmm` are not in spec 16
- tests/test_api.py :: test_every_rct_of_the_run_is_listed_with_when_it_was_detected :: `GET /dkrmm/rcts` and `/ui/dkrmm` are not in spec 16
- tests/test_controls.py :: test_the_scenario_can_be_switched_without_restarting_the_server :: resets to the removed `busy` and `stress` presets; the one preset is `default`, and every other preset is refused (test_api_trimmed.py `test_only_the_default_scenario_can_be_chosen`, test_controls.py `test_an_unknown_scenario_is_refused_rather_than_guessed`)
- tests/test_header_digest.py :: test_every_family_has_an_entry_point_and_a_description :: `SEAM_OF`/`DOES` and the removed `perturbation.model.FAMILIES`
- tests/test_header_digest.py :: test_the_descriptions_promise_a_mechanism_and_not_an_outcome :: `DOES`, part of the removed disturbance digest
- tests/test_header_digest.py :: test_a_facility_with_nothing_scheduled_says_none :: `perturbation_digest` is removed
- tests/test_header_digest.py :: test_due_and_injected_are_not_the_same_sentence :: `perturbation_digest` and the removed `stress` preset
- tests/test_header_digest.py :: test_the_digest_says_where_the_stimulus_entered :: `perturbation_digest` and the removed `stress` preset
- tests/test_header_digest.py :: test_provenance_stays_three_answers_rather_than_one_source :: `perturbation_digest` and the removed `stress` preset
- tests/test_header_digest.py :: test_nothing_measured_yet_is_a_statement_and_not_a_blank :: `perturbation_digest` and the removed `stress` preset
- tests/test_header_digest.py :: test_a_depth_never_travels_without_its_relation :: `perturbation_digest` and the removed `stress` preset
- tests/test_header_digest.py :: test_more_than_one_in_force_is_counted :: `perturbation_digest` and the removed `stress` preset
- tests/test_header_digest.py :: test_the_digest_carries_every_scheduled_disturbance :: `perturbation_digest` and the removed `stress` preset
- tests/test_header_digest.py :: test_each_row_carries_its_own_phase_and_its_own_consequence :: `perturbation_digest` and the removed `stress` preset
- tests/test_header_digest.py :: test_the_lead_row_is_one_of_the_rows_and_not_a_fourth_thing :: `perturbation_digest` and the removed `stress` preset
- tests/test_header_digest.py :: test_the_shell_can_open_the_whole_schedule :: the shell's disturbance schedule strip is removed
- tests/test_header_digest.py :: test_the_shell_paints_both_from_the_summary :: renamed `test_the_shell_paints_the_verdict_from_the_summary`; its `paintPerturbation` half removed with the strip
- tests/test_header_digest.py :: test_the_summary_endpoint_offers_both_digests :: renamed `test_the_summary_endpoint_offers_the_monitor_digest`; its `perturbation_digest` half removed with the digest

#### Rewritten lines in the Task 9 carried tests

- tests/test_api.py, tests/test_controls.py :: the fixtures set `server.runner = SimulationRunner(..., trace_db=..., session_id=...)`; now `server.use(SimulationRunner(..., rules_only=True))` (the Prototype II runner has no trace, and the module builds no runner at import)
- tests/test_api.py :: every `SimulationRunner(...)` gains `rules_only=True` and drops `trace=`, `trace_db=`, `session_id=` (not parameters of the Task 8 runner)
- tests/test_api.py :: `test_every_read_endpoint_answers_with_json` parametrize list trimmed to the spec 16 routes `/state`, `/events`, `/summary`
- tests/test_api.py :: `test_every_tracking_endpoint_answers_with_json` parametrize list trimmed to `/settings`
- tests/test_api.py :: `test_the_address_people_actually_type_serves_the_ui` asserts `GET /` serves the page (200) instead of redirecting to `/ui` (spec 16: `GET /` is the live page)
- tests/test_api.py :: `test_every_page_of_the_live_ui_is_served` parametrize list trimmed to `/`
- tests/test_api.py :: `test_no_served_page_repeats_an_element_id` scans `/` and the floor page (`live.robots_html`), which the shell carries as an escaped `srcdoc`, instead of `/ui`, `/ui/simple`, `/settings/ui`
- tests/test_api.py :: `test_the_live_shell_names_the_pages_it_mounts` checks the shell names the endpoints it polls (`/frame`, `/consultations`, `/llm/calls`, `/dkrmm/*`, `/settings`, `/ws`, `/summary`) instead of the removed `/ui/*` pages
- tests/test_api.py :: `test_the_floor_follows_the_run_one_frame_at_a_time` reads `/frame` (was `/ui/frame`), its key set adds `run_id`, `roster`, `llm_agents`, `busy`, `in_flight`, and it steps with `server.runner.step(4)` (was `POST /simulation/step`)
- tests/test_api.py :: `test_the_built_file_and_the_served_page_share_their_builders` reads `/frame` and asserts the built frame's keys are a subset of the served one's
- tests/test_api.py :: `test_the_settings_say_whether_any_agent_is_actually_using_a_model` drops the `workspace`, `tools` and `llm_wanted` keys (not in spec 16's `/settings`)
- tests/test_api.py :: `test_the_stream_answers_at_both_of_its_names` connects to `/ws` only (`WS /events` is not in spec 16) and still checks `GET /events`
- tests/test_api.py :: `test_the_websocket_opens_with_the_whole_state_then_streams` steps with `server.runner.step(2)` (was `POST /simulation/step`)
- tests/test_api.py :: `test_the_shell_offers_a_control_for_a_run_that_starts_paused` reads `/` (was `/ui`)
- tests/test_api.py :: `test_the_monitor_tab_renders_normally` and `test_a_failed_monitor_tab_shows_why_rather_than_four_words` read `/` (the DK-RMM pane is part of the shell; `/ui/dkrmm` is not in spec 16), and a failed pane leaves the page a 200 with the pane saying what it lost
- tests/test_api.py :: the pacing tests' comments drop the batching account (the Task 8 runner sleeps once per tick); `test_every_tick_is_broadcast_once_and_in_order`, `test_stopping_during_a_batch_is_not_deferred_to_the_end_of_it` and `test_the_pace_does_not_change_the_run` are otherwise as in the source
- tests/test_controls.py :: `config("busy")` -> `busy_config()` (tests/presets.py, same values)
- tests/test_controls.py :: `test_the_clock_speed_can_be_set_and_read_back` reads `tick_seconds` from `/summary` (`GET /simulation/speed` is not in spec 16)
- tests/test_controls.py :: `test_a_new_run_gets_a_new_seed_and_starts_over` steps with `server.runner.step(30)` (was `POST /simulation/step`)
- tests/test_header_digest.py :: imports `monitor_digest` only (no `perturbation_digest`, `SEAM_OF`, `DOES`, `perturbation.model`)
- tests/test_dkrmm.py :: `test_the_monitor_is_served_and_the_gate_is_a_person_only_door` reads `/dkrmm/state` (was `/dkrmm`), asserts that `POST /dkrmm/validate|activate|dismiss` are 404 (spec 16 serves no gate), exercises the gate through the monitor's own methods, and reads `/` for the page (was `/ui/dkrmm`); runner built with `rules_only=True, config=busy_config()`
- tests/test_dkrmm.py :: `test_a_run_over_the_api_is_watched_without_being_altered` compares against `build(..., config=busy_config(), scenario="default")` (was `interactive_config(config("busy"))`): the Task 8 runner uses its configuration verbatim and builds with the scenario of its preset

## Notes

Facts about files classified `unchanged` that a reader of the copied text
should know, recorded here rather than by editing the copied file.

- post_office/discussion/briefings.py :: copied unchanged from the source, but its
  module docstring's claim "Read on the peer's tick ..., never from a worker
  thread" no longer holds in Prototype II. A consultation's owner runs in a
  worker thread (`crew/consultation.py`), and the peer's briefing is read from
  that worker, inside the owner's tool use (`crew/tools.py`), while the tick's
  thread is blocked in `join` waiting for it. It is still the floor as it is
  at the moment of the consultation, because the tick is not moving; and the
  read is made under the consultation service's lock and only while the
  consultation is open, so a worker abandoned at its deadline never reads the
  live world while the tick has moved on.

### Adapted from a different source path

`tools/provenance.py` pairs a file with the source file at the same relative
path. These were adapted from a file elsewhere in the source tree, so their
source path is recorded here.

- post_office/ui/floor.html :: adapted from the source `tools/replay_template.html`
  (the floor, the interaction graph, the robot cards and the message feed that the
  source's `ui/live.py::robots_html` served at `/ui/robots`). The discussion strip,
  links, bubbles and log are removed (Prototype II consults through CrewAI and its
  frames carry no discussion rows), consultation messages (`CONSULT_*`) take the
  feed's highlight that discussion turns had, and the run line no longer claims
  every decision is deterministic. It is served inside the live page as an
  escaped `srcdoc`, so it needs no route of its own.
