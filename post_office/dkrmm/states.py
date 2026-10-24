"""
What the monitor can say, and how far a finding has got.

Two small vocabularies, kept in a file of their own because they are the part
of DK-RMM that other people read. The names match the model as it is written
up and as the sibling prototype implements it, so a STABLE here and a STABLE
there mean the same thing and a result can be carried between them.
"""

from __future__ import annotations

from enum import Enum


class OperationalState(str, Enum):
    """
    The collective condition of the ecosystem, as the monitor reads it.

    Collective is the operative word. None of these is a statement about an
    agent: a facility where one robot fails repeatedly and nothing else changes
    is not unstable, it is a facility with a broken robot. The states are about
    what the population is doing together.
    """

    #: Nothing outside the ordinary. The baseline the rest are measured against.
    STABLE = "STABLE"
    #: Something has moved. One kind of evidence, not yet spreading.
    DEVIATING = "DEVIATING"
    #: Several kinds of evidence at once, or one that will not settle.
    UNSTABLE = "UNSTABLE"
    #: A Runtime Critical Transition: the system is changing regime rather than
    #: having a bad minute. Independent evidence converging, and the statistics
    #: of a system at a critical point rather than of a noisy one.
    RCT = "RCT"
    #: Back to ordinary from one of the three above. Reported rather than
    #: folded into STABLE because the transition out is itself the finding.
    RECOVERY = "RECOVERY"


#: The three above STABLE, in order of severity. Used for "was it worse before".
ESCALATED = (OperationalState.DEVIATING, OperationalState.UNSTABLE,
             OperationalState.RCT)


class DiscoveryStatus(str, Enum):
    """
    How far a finding has come through the human gate.

    The gate is the point of the model rather than a formality around it: an
    automatic monitor that declares a critical transition and acts on it is an
    automatic monitor that will one day be confidently wrong at scale. So the
    machine discovers, a person validates, and only a validated finding is
    allowed to mean anything.
    """

    #: The monitor said so. Nobody has looked yet.
    DISCOVERED = "DISCOVERED"
    #: A person looked and agreed.
    VALIDATED = "VALIDATED"
    #: A validated finding that is being acted on.
    ACTIVE = "ACTIVE"
    #: A person looked and disagreed. Kept, not deleted: a false positive is
    #: evidence about the model, and a monitor whose mistakes are erased can
    #: never be shown to have any.
    DISMISSED = "DISMISSED"
