# post_office.environment

The physical facility and nothing else: the floor plan, the five functional zones, the parcels, the charge points and storage shelves, the outbound van timetable, the bag room and the queue of recovery requests. `PostOfficeEnvironment` is the building; it holds a `Grid` (cells, walls and deterministic A* paths over `Position` cells), a `ZoneMap` (which `Zone` each `Rect` of cells is), the `ChargingStation`s and the `StorageArea`, the `Parcel`s still inside and those that have left, a `DepartureBoard` of `Vehicle`s per route and a `BagRoom` of `Receptacle`s. It answers questions (free cells, distances, free charge points) and accepts changes (add, lift, drop and remove a parcel, claim and release a station or a shelf), announcing each change through an optional event sink. `layout.build_environment()` assembles the default 24 by 14 building, attaches the departure board (with the route list from `agents.subagents.sorting_subagents.ROUTES`) and the bag room, and checks that every zone and charge point is reachable from intake. Nearly every package depends on it (`agents`, `robots`, `tasks`, `core`, `policy`, `state`, `config`, `simulation`), and it depends on no other package except that one route list. The rule to know: the environment holds no agents, sends no messages and makes no decisions; capacity is finite and a request that cannot be granted is refused and announced, never queued, and agents act on it only through the simulation.

## Class diagram

### Facility and layout

```mermaid
classDiagram
  direction LR
  class PostOfficeEnvironment {
    +Grid grid
    +ZoneMap zones
    +dict stations
    +StorageArea storage
    +dict parcels
    +dict departed
    +DepartureBoard departures
    +BagRoom bags
    +list recovery_requests
    +int tick
    +add_parcel(parcel, at) Parcel
    +lift_parcel(parcel_id, robot_id) bool
    +drop_parcel(parcel_id, at) bool
    +remove_parcel(parcel_id, dispatched, returned) Parcel
    +free_cell_in(zone, near) Position
    +claim_storage(parcel_id) bool
    +claim_station(robot_id, station_id) ChargingStation
    +release_station(robot_id) None
    +place_robot(robot_id, p) None
    +occupied_by_robot(p, excluding) str
    ...
  }
  class Grid {
    +int width
    +int height
    +Set~Position~ obstacles
    -dict _path_cache
    +is_free(p) bool
    +in_bounds(p) bool
    +add_obstacle(p) None
    +path(start, goal) List~Position~
    +distance(start, goal) int
    +as_text(marks) str
    ...
  }
  class Position {
    <<dataclass>>
    +int x
    +int y
    +manhattan(other) int
    +neighbours() tuple
    +of(value)$ Position
  }
  class Zone {
    <<enumeration>>
    INTAKE
    SORTING
    TEMPORARY_STORAGE
    DISPATCH
    CHARGING
  }
  class Rect {
    <<dataclass>>
    +int x0
    +int y0
    +int x1
    +int y1
    +Position centre
    +cells() Iterator~Position~
    +of(value)$ Rect
  }
  class ZoneMap {
    -dict _rects
    -dict _index
    +zones() List~Zone~
    +zone_at(p) Zone
    +cells_of(zone) List~Position~
    +anchor(zone) Position
  }
  class ChargingStation {
    <<dataclass>>
    +str station_id
    +Position position
    +str occupant
    +float rate
    +int served
    +bool free
  }
  class StorageArea {
    <<dataclass>>
    +int capacity
    +Set~str~ held
    +int refusals
    +int used
    +int free
    +float load
  }
  class layout {
    <<module>>
    +build_environment(width, height, zones, ...) PostOfficeEnvironment
    +default_obstacles(height, walls) List~Position~
    +dict DEFAULT_ROBOT_HOME
    +int DEFAULT_STORAGE_CAPACITY
    +float CHARGE_RATE
  }
  class DepartureBoard {
    <<see part 2>>
  }
  class BagRoom {
    <<see part 2>>
  }

  PostOfficeEnvironment o-- Grid : grid
  PostOfficeEnvironment o-- ZoneMap : zones
  PostOfficeEnvironment "1" o-- "*" ChargingStation : stations
  PostOfficeEnvironment *-- StorageArea : storage
  Grid --> Position : obstacles
  ZoneMap "1" o-- "*" Rect : per zone
  ZoneMap --> Zone : keys
  Rect ..> Position : cells()
  ChargingStation --> Position : position
  layout ..> PostOfficeEnvironment : creates
  layout ..> Grid : creates
  layout ..> ZoneMap : creates
  layout ..> ChargingStation : creates
  layout ..> DepartureBoard : creates
  layout ..> BagRoom : creates
```

![environment class diagram, facility and layout](img/environment-1.svg)

### Parcels, receptacles, vehicles, recovery

```mermaid
classDiagram
  direction LR
  class Parcel {
    <<dataclass>>
    +str parcel_id
    +Zone origin
    +Zone destination
    +ParcelPriority priority
    +ParcelSize size
    +ParcelStatus status
    +str assigned_robot
    +Position position
    +Zone current_zone
    +str address
    +str barcode
    +str route_label
    +int due_by
    +str bagged_in
    +str loaded_on
    +dict timestamps
    +list processing_history
    +record(tick, actor, action) None
    +set_status(status, tick, actor) None
    +late_at(tick) bool
    +int dwell
    ...
  }
  class ParcelPriority {
    <<enumeration>>
    NORMAL
    EXPRESS
    URGENT
    +int rank
  }
  class ParcelSize {
    <<enumeration>>
    SMALL
    MEDIUM
    LARGE
    +int units
  }
  class ParcelStatus {
    <<enumeration>>
    ARRIVED
    REGISTERED
    CLASSIFIED
    AWAITING_PICKUP
    IN_TRANSIT
    SORTED
    STORED
    AWAITING_DISPATCH
    DISPATCHED
    REFUSED
    ...
  }
  class parcels {
    <<module>>
    +frozenset OPEN_STATUSES
    +int MAX_HISTORY
  }
  class DepartureBoard {
    +List~str~ routes
    +int interval
    +int capacity
    +int departures
    -dict _bay
    -list _gone
    +open(tick) None
    +advance(tick) List~Vehicle~
    +at_bay(route) Vehicle
    +nth_departure_after(route, tick, nth) int
    +promise_for(service_or_priority, tick, route) int
    ...
  }
  class Vehicle {
    <<dataclass>>
    +str vehicle_id
    +str route
    +int capacity
    +int departs_at
    +List~str~ loaded
    +int units
    +int departed_at
    +bool has_gone
    +load(parcel_id, units) bool
  }
  class vehicles {
    <<module>>
    +dict PROMISED_DEPARTURE
    +int DEFAULT_INTERVAL
    +int HANDLING_ALLOWANCE
    +int DEFAULT_CAPACITY
  }
  class BagRoom {
    +int capacity
    +List~Receptacle~ sealed
    -dict _open
    +open_bag(route, mail_class, tick) Receptacle
    +seal(bag, tick) Receptacle
    +open_bags() List~Receptacle~
    +waiting(route) List~Receptacle~
    +all_bags() List~Receptacle~
    +summary() dict
  }
  class Receptacle {
    <<dataclass>>
    +str receptacle_id
    +str route
    +str mail_class
    +int capacity
    +List~str~ parcel_ids
    +int units
    +int sealed_at
    +str loaded_on
    +accepts(route, mail_class) bool
    +put(parcel_id, units) bool
    +seal(tick) None
    ...
  }
  class RecoveryRequest {
    <<dataclass>>
    +str action
    +str robot_id
    +str requested_by
    +int tick
    +str reason
    +str target
    +int attempts
    +as_dict() dict
  }
  class PostOfficeEnvironment {
    <<see part 1>>
  }
  class Zone {
    <<see part 1>>
  }

  PostOfficeEnvironment "1" o-- "*" Parcel : parcels, departed
  PostOfficeEnvironment o-- DepartureBoard : departures
  PostOfficeEnvironment o-- BagRoom : bags
  PostOfficeEnvironment "1" o-- "*" RecoveryRequest : recovery_requests
  Parcel --> ParcelPriority : priority
  Parcel --> ParcelSize : size
  Parcel --> ParcelStatus : status
  Parcel --> Zone : origin, destination
  parcels ..> ParcelStatus
  DepartureBoard "1" *-- "*" Vehicle : creates per route
  DepartureBoard ..> vehicles : promise rules
  Vehicle --> Parcel : loaded (by id)
  BagRoom "1" *-- "*" Receptacle : open_bag() creates
  Receptacle --> Parcel : parcel_ids (by id)
```

![environment class diagram, parcels, receptacles, vehicles, recovery](img/environment-2.svg)

## Classes

| Class | Module | Role |
|---|---|---|
| `PostOfficeEnvironment` | `facility.py` | The building: grid, zones, charge points, storage, parcels inside and departed, timetable, bag room and recovery queue; answers questions and accepts physical changes, emitting an event for each. |
| `ChargingStation` | `facility.py` | Dataclass for one charge point, occupied by at most one robot, with its charge rate and use count. |
| `StorageArea` | `facility.py` | Dataclass for temporary storage with a finite shelf count, the parcels held and the refusals counted. |
| `Grid` | `grid.py` | Rectangle of cells with walls; cached, deterministic 4-connected A* paths and distances. |
| `Position` | `grid.py` | Frozen, ordered dataclass for one cell; Manhattan distance and neighbours in a fixed order. |
| `Zone` | `zones.py` | Enumeration of the five functional areas. |
| `Rect` | `zones.py` | Frozen dataclass for an inclusive rectangle of cells, with its centre. |
| `ZoneMap` | `zones.py` | Which zone each cell belongs to, where each zone is, and each zone's anchor cell. |
| `Parcel` | `parcels.py` | Dataclass for one parcel: its classification, place, promise, bag and van, timestamps and capped processing history. |
| `ParcelPriority` | `parcels.py` | Enumeration NORMAL, EXPRESS, URGENT, with a numeric `rank` for queue ordering. |
| `ParcelSize` | `parcels.py` | Enumeration SMALL, MEDIUM, LARGE, with the load `units` each consumes. |
| `ParcelStatus` | `parcels.py` | Enumeration of a parcel's life stages, ending in DISPATCHED, REFUSED or RETURNED (11 members). |
| `Receptacle` | `receptacles.py` | Dataclass for one bag of parcels sharing a route and mail class; refuses parcels once full or sealed. |
| `BagRoom` | `receptacles.py` | The one open bag per (route, mail class) and the sealed bags waiting for a van. |
| `Vehicle` | `vehicles.py` | Dataclass for one outbound van: route, departure tick, capacity in size units and the parcels loaded. |
| `DepartureBoard` | `vehicles.py` | The staggered per-route timetable, the van at each bay, departures on `advance()`, and the departure a parcel class is promised. |
| `RecoveryRequest` | `recovery.py` | Dataclass for an agent asking the facility to tow a flat robot; queued on the environment, acted on by `simulation.RecoveryService`. |
| `layout` (module) | `layout.py` | `build_environment()` and `default_obstacles()`, plus the default zones, walls, charge points, robot homes, storage capacity and charge rate. |
| `parcels` (module) | `parcels.py` | Constants `OPEN_STATUSES` (statuses that still need work) and `MAX_HISTORY`. |
| `vehicles` (module) | `vehicles.py` | Timetable constants: `PROMISED_DEPARTURE` per service class, `DEFAULT_INTERVAL`, `HANDLING_ALLOWANCE`, `DEFAULT_CAPACITY`. |
