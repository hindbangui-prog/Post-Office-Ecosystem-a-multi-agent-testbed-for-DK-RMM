"""
The interception seams of a consultation (spec 15), identity in this phase.

Two layers sit on the path of every consultation. `CommunicationLayer` sees
each owner-to-peer request and each peer-to-owner response as it crosses
between the two experts; `AgentHooks` sees the owner's prompt before its
model is asked, the moment before the model call, and the answer once it has
been read back. In NORMAL every method hands its argument back unchanged.

A `None` from `on_request` or `on_response` means the message did not get
through: the owner's tool returns "no answer from <Peer>", and if the owner
then reaches no decision the consultation closes as `peer_failed`.

The communication layer is called under the consultation service's lock and
only while the consultation is open, so a worker abandoned at its deadline
never drives it concurrently with the tick. A layer must therefore return
promptly: one that wants to delay a message cannot sleep inside `on_request`
(the tick would wait on the lock past the deadline); that is a design point
for the perturbation work, not something this phase does.

`after_answer` may only change the answer within the question's options: the
service checks its result against them again before it can reach the gate,
and an answer outside them is the rule's fallback (`no_valid_decision`).

`Interception.inert()` is the arrangement a NORMAL run uses, and
`from_config(cfg)` is how the ecosystem builds the one its service consumes:
an empty `interceptors` list gives the inert arrangement, anything else is
refused, because perturbations are not part of this phase.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from ..agents.brain import Answer


@dataclass
class ConsultRequest:
    """One owner-to-peer message: a question or a delegated sub-question."""

    consultation_id: str
    tick: int
    sender: str
    receiver: str
    interaction_type: str
    text: str
    context: str


@dataclass
class ConsultResponse:
    """The peer's advice on its way back to the owner."""

    consultation_id: str
    tick: int
    sender: str
    receiver: str
    text: str
    latency_ms: float
    model: str


class CommunicationLayer:
    """What passes between owner and peer. Identity: everything gets through as sent."""

    def on_request(self, req: ConsultRequest) -> Optional[ConsultRequest]:
        return req

    def on_response(self, resp: ConsultResponse) -> Optional[ConsultResponse]:
        return resp


class AgentHooks:
    """What happens around the owner's model. Identity: nothing is changed."""

    def before_prompt(self, agent_id: str, text: str) -> str:
        return text

    def before_llm_call(self, agent_id: str) -> None:
        return None

    def after_answer(self, agent_id: str, answer: Answer) -> Answer:
        return answer


@dataclass
class Interception:
    communication: CommunicationLayer = field(default_factory=CommunicationLayer)
    agent: AgentHooks = field(default_factory=AgentHooks)

    @classmethod
    def inert(cls) -> "Interception":
        """The NORMAL arrangement: both layers are identity."""
        return cls(CommunicationLayer(), AgentHooks())

    @property
    def active(self) -> bool:
        """Whether anything other than the identity layers is installed."""
        return type(self.communication) is not CommunicationLayer \
            or type(self.agent) is not AgentHooks


def from_config(cfg: Dict[str, Any]) -> Interception:
    """
    The interception a run's configuration asks for.

    `cfg.get("interceptors", [])` empty: `Interception.inert()`. Anything else
    is `NotImplementedError`: no interceptor exists in this phase, and a run
    asking for one must not build silently as NORMAL.
    """
    interceptors = cfg.get("interceptors", [])
    if interceptors == [] or interceptors == ():  # the ecosystem's own test, exactly
        return Interception.inert()
    raise NotImplementedError("perturbations are not part of this phase")


__all__ = ["AgentHooks", "CommunicationLayer", "ConsultRequest", "ConsultResponse",
           "Interception", "from_config"]
