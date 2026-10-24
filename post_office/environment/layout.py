"""
The floor plan the demonstration runs on, and the function that builds it.

The layout is deliberately awkward. Three internal walls mean that most
journeys have to pass through one of a handful of doorways, so robots contend
for space instead of gliding past each other on an empty plane, and the routing
and collision-avoidance sub-agents have something real to do. An open field
would make the simulation look healthier than any real facility ever is.

    0         1         2
    0123456789012345678901234
  0 .....#......#....#.......
  1 iiii.#.sssss#....#..ddddd
  ...
  6 iiii..ssssss#....#..ddddd     <- the only gaps in the first wall
  ...
 10 iiii.#.tttt.....ddddd         <- the doorways in the second wall
 11 iiii.#.tttt.....ddddd
 12 iiii.#.tttt.#.CCCC..ddddd     <- charge points, and where robots park
    i intake   s sorting   t temporary storage   d dispatch   C charge point

Nothing else in the package imports this module except `config/`, so a
different building is a different `build_environment()` call, not a patch.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from .facility import ChargingStation, PostOfficeEnvironment
from .grid import Grid, Position
from .zones import Rect, Zone, ZoneMap

#: Grid size of the default facility.
DEFAULT_WIDTH = 24
DEFAULT_HEIGHT = 14

#: Where each functional area sits on that grid.
DEFAULT_ZONES: Dict[Zone, Rect] = {
    Zone.INTAKE: Rect(0, 1, 3, 12),
    Zone.SORTING: Rect(6, 1, 10, 5),
    Zone.TEMPORARY_STORAGE: Rect(6, 8, 10, 12),
    Zone.CHARGING: Rect(13, 10, 16, 12),
    Zone.DISPATCH: Rect(19, 1, 22, 12),
}

#: Internal walls, as (x, gap_ys) -- a full-height wall with a few doorways.
DEFAULT_WALLS: Sequence = (
    (5, (4, 5, 6, 7, 8)),  # intake wall: everything to sorting goes through here
    (12, (3, 4, 10, 11)),   # mid wall: one doorway high, one low
    (17, (5, 6)),       # dispatch wall: plus the open floor below y=10
)

#: Charge points, in the charging zone, one short of the fleet size on purpose.
#:
#: On the bottom row of the zone rather than its top. The robots park on these
#: (see `DEFAULT_ROBOT_HOME`), and the top row runs along the mid wall's low
#: doorways at (12, 10) and (12, 11) -- so a robot parked there stood in the
#: exit of a doorway a third of the floor's traffic goes through. Moving the
#: row down one cell is worth about a point of blocked time and two parcels a
#: run, which is a lot for a cell.
DEFAULT_STATION_CELLS: Sequence = ((13, 12), (14, 12), (15, 12), (16, 12))

#: Where the five robots stand at tick zero, and where they return when idle.
#:
#: On the charge points, which is where a real fleet parks. Idle time is the
#: cheapest charge a facility can buy: the robot was going to stand somewhere
#: anyway, and standing on a plug turns waiting into charging at no cost in
#: travel. Parking them on a depot row three cells away instead -- which is
#: what this used to do -- meant every percent of charge had to be fetched,
#: and a robot spent twelve ticks walking to gain six ticks of charge.
#:
#: Four points and five robots, so the fifth parks beside them and takes its
#: turn. That is the contest the resource agent exists for, and it is now a
#: contest over parking as well as over charging.
#:
#: Clear of every doorway, which took some care: the mid wall's low doorways are
#: at (12, 10) and (12, 11), so the points sit on the bottom row of the zone
#: rather than the top. Where robots wait matters more than it sounds -- in a
#: building with four doorways one badly parked robot can close a third of the
#: floor, and the first version of this parked four of them in one.
DEFAULT_ROBOT_HOME: Dict[str, Position] = {
    "R1": Position(13, 12),
    "R2": Position(14, 12),
    "R3": Position(15, 12),
    "R4": Position(16, 12),
    "R5": Position(15, 11),
}

DEFAULT_STORAGE_CAPACITY = 20


def default_obstacles(height: int = DEFAULT_HEIGHT,
                      walls: Sequence = DEFAULT_WALLS) -> List[Position]:
    """Expand the compact wall description into the cells it blocks."""
    cells: List[Position] = []
    for x, gaps in walls:
        gap_set = set(gaps)
        # the wall stops short of y=17's lower half, which is open floor
        top = height if x != 17 else 10
        for y in range(0, top):
            if y not in gap_set:
                cells.append(Position(x, y))
    return cells


#: Battery percent a charge point delivers per tick.
#:
#: It used to be 8, which took a robot from half to nearly full in six ticks --
#: a full charge in a quarter of a minute at one second per tick, while the
#: walk to the point cost twelve. A charge that costs less than the trip to it
#: is not a constraint on anything. At 1.2 a committed charge is about fifty
#: ticks: long enough that a robot is genuinely out of service, short enough
#: that a facility with four points and five robots keeps working.
CHARGE_RATE = 1.2


def build_environment(width: int = DEFAULT_WIDTH,
                      height: int = DEFAULT_HEIGHT,
                      zones: Optional[Dict[Zone, Rect]] = None,
                      obstacles: Optional[Sequence[Position]] = None,
                      station_cells: Sequence = DEFAULT_STATION_CELLS,
                      storage_capacity: int = DEFAULT_STORAGE_CAPACITY,
                      charge_rate: float = CHARGE_RATE,
                      van_interval: int = 0,
                      van_capacity: int = 0) -> PostOfficeEnvironment:
    """Build the facility. Every argument has a default, so tests can vary one."""
    grid = Grid(width, height,
                obstacles if obstacles is not None else default_obstacles(height))
    zone_map = ZoneMap(dict(zones or DEFAULT_ZONES))

    stations = []
    for index, cell in enumerate(station_cells, start=1):
        position = Position.of(cell)
        if not grid.is_free(position):
            raise ValueError(f"charge point {index} sits on a wall: {position}")
        stations.append(ChargingStation(station_id=f"CS-{index}",
                                        position=position, rate=charge_rate))

    env = PostOfficeEnvironment(grid=grid, zones=zone_map,
                                charging_stations=stations,
                                storage_capacity=storage_capacity)

    # The outbound timetable. Part of the building rather than of an agent: a
    # van leaves whether or not anybody managed to load it, and a cut-off an
    # agent could quietly move would not be a cut-off.
    from .vehicles import (DEFAULT_CAPACITY, DEFAULT_INTERVAL, DepartureBoard)
    from ..agents.subagents.sorting_subagents import ROUTES

    env.departures = DepartureBoard(
        routes=ROUTES,
        interval=van_interval or DEFAULT_INTERVAL,
        capacity=van_capacity or DEFAULT_CAPACITY)

    # The bag room, for the same reason: a sealed bag is a physical thing
    # standing on the floor, and it should still be there if the gate that
    # filled it stops answering.
    from .receptacles import BagRoom

    env.bags = BagRoom()

    # A floor plan that cannot be crossed is a bug worth finding at build time,
    # not thirty ticks into a run when a robot quietly stops moving.
    anchors = {z: zone_map.anchor(z) for z in zone_map.zones()}
    for zone, anchor in anchors.items():
        if not grid.is_free(anchor):
            raise ValueError(f"{zone.value} anchor {anchor} sits on a wall")
    intake = anchors[Zone.INTAKE]
    for zone, anchor in anchors.items():
        if grid.path(intake, anchor) is None:
            raise ValueError(f"{zone.value} is unreachable from INTAKE")
    for station in stations:
        if grid.path(intake, station.position) is None:
            raise ValueError(f"{station.station_id} is unreachable from INTAKE")

    return env
