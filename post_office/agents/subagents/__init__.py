"""
The thirteen sub-agents, each owned by exactly one expert.

    intake      SUB-REGISTRATION
    sorting     SUB-BARCODE      SUB-DESTINATION   SUB-PRIORITY
    routing     SUB-ROUTE        SUB-COLLISION
    scheduling  SUB-QUEUE        SUB-DEADLINE      SUB-ASSIGNMENT
    resource    SUB-BATTERY      SUB-CHARGING      SUB-STORAGE
    dispatch    SUB-MANIFEST     SUB-PACKING

A sub-agent may address its parent and nothing else. That is not a convention
here -- `communication/directory.py` refuses anything else and the refusal is
written to the event log, so a violation is a measurable event rather than a
code review comment.
"""

from .sorting_subagents import (BarcodeSubAgent,
                                DestinationClassificationSubAgent,
                                PriorityClassificationSubAgent,
                                make_barcode, parse_barcode, ROUTES,
                                SERVICE_CODES)
from .routing_subagents import CollisionAvoidanceSubAgent, RoutePlanningSubAgent
from .scheduling_subagents import (DeadlineMonitorSubAgent,
                                   QueueManagementSubAgent)
from .resource_subagents import (BatteryManagementSubAgent,
                                 ChargingStationSubAgent,
                                 StorageMonitoringSubAgent)
from .gate_subagents import (ManifestSubAgent, PackingSubAgent,
                             RegistrationSubAgent, ValidationSubAgent)
from .assignment_subagent import AssignmentSubAgent

__all__ = [
    "BarcodeSubAgent", "DestinationClassificationSubAgent",
    "PriorityClassificationSubAgent",
    "RoutePlanningSubAgent", "CollisionAvoidanceSubAgent",
    "QueueManagementSubAgent", "DeadlineMonitorSubAgent",
    "BatteryManagementSubAgent", "ChargingStationSubAgent",
    "StorageMonitoringSubAgent",
    "ValidationSubAgent", "RegistrationSubAgent", "ManifestSubAgent",
    "PackingSubAgent",
    "AssignmentSubAgent",
    "make_barcode", "parse_barcode", "ROUTES", "SERVICE_CODES",
]
