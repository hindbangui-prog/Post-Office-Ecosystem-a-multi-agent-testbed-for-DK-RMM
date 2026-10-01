import json

from post_office.config.settings import config, normal_config
from post_office.discussion.briefings import briefing_for
from post_office.simulation import build

PEERS = ("RESOURCE", "SCHEDULING", "DISPATCH", "ROUTING", "PLANNER", "SORTING")


def test_each_peer_can_say_what_it_knows_in_a_few_hundred_characters():
    eco = build(seed=1, config=normal_config())
    eco.start()
    try:
        for _ in range(300):
            eco.step()
        for peer in PEERS:
            facts = briefing_for(eco.agents[peer])
            assert facts and "error" not in facts, (peer, facts)
            assert len(json.dumps(facts, default=str)) < 2500, peer
        assert {"robots", "charge_points", "storage"} <= set(briefing_for(eco.agents["RESOURCE"]))
        assert {"transports", "free_robots"} <= set(briefing_for(eco.agents["SCHEDULING"]))
        assert "vans" in briefing_for(eco.agents["DISPATCH"])
        assert "robots" in briefing_for(eco.agents["ROUTING"])
        assert "open_transports" in briefing_for(eco.agents["PLANNER"])
        assert "routes" in briefing_for(eco.agents["SORTING"])
    finally:
        eco.close()


def test_an_agent_with_no_briefing_says_so_rather_than_failing():
    eco = build(seed=1, config=config("default"))
    try:
        assert briefing_for(eco.agents["INTAKE"]) == {"note": "no briefing for INTAKE"}
    finally:
        eco.close()
