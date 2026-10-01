"""
How a consultation is written down (spec 12): `consult_*` events and `CONSULT_*` messages.

Nothing here is a second event system. Every `consult_*` event goes through the
ecosystem's `EventLogger` (category `agent`) and every `CONSULT_*` message
through its `MessageBus`, which logs it as an ordinary `message` event between
two experts, the traffic DK-RMM's message indicators read.

Each event carries `tick`, `actor` (the sender), `target` (the receiver) and
`correlation_id` (the consultation id), and in `detail` the consultation id,
the decision id, the decision kind, the trigger condition, the interaction
type and the model, plus the topic's own fields:

    consult_opened      peer (or ""), options                    interaction_type decision
    consult_question    text, context                            question
    consult_delegation  text, context                            delegation
    consult_response    text, latency_ms                         response
    consult_refused     reason                                   the refused attempt's type
    consult_closed      outcome, choice, turns, latency_ms        decision
    llm_call            agent_role, call_id, url, ..., phase     llm_call

`opened` registers the consultation and `closed` forgets it, so a request or a
response, which names only its consultation id, is written with the decision's
fields.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Sequence

from ..communication.events import EventCategory
from ..communication.message import MessageType
from .audit import LLMCallRecord
from .interception import ConsultRequest, ConsultResponse
from .roles import ROLES


def _role(agent_id: str) -> str:
    spec = ROLES.get(agent_id)
    return spec.role if spec is not None else ""


class ConsultEvents:
    def __init__(self, logger: Any, bus: Any, model: str) -> None:
        self.logger = logger
        self.bus = bus
        self.model = model
        self._open: Dict[str, Any] = {}

    # ------------------------------------------------------------- helpers
    def _common(self, ctx: Any, interaction_type: str) -> Dict[str, Any]:
        return {"consultation_id": ctx.consultation_id, "decision_id": ctx.decision_id,
                "decision": ctx.kind, "condition": ctx.condition,
                "interaction_type": interaction_type, "model": self.model}

    def _emit(self, topic: str, ctx: Any, actor: str, target: str, interaction_type: str,
              **extra: Any) -> Any:
        return self.logger.emit(EventCategory.AGENT, topic, tick=ctx.tick, actor=actor,
                                target=target, correlation_id=ctx.consultation_id,
                                **self._common(ctx, interaction_type), **extra)

    def _ctx(self, consultation_id: str) -> Any:
        return self._open[consultation_id]

    # -------------------------------------------------------------- events
    def opened(self, ctx: Any, peer: Optional[str], options: Sequence[Any]) -> Any:
        self._open[ctx.consultation_id] = ctx
        return self._emit("consult_opened", ctx, ctx.owner_id, peer or "", "decision",
                          peer=peer or "", options=[str(o) for o in options])

    def _request(self, topic: str, req: ConsultRequest) -> Any:
        ctx = self._ctx(req.consultation_id)
        event = self._emit(topic, ctx, req.sender, req.receiver, req.interaction_type,
                           text=req.text, context=req.context)
        self.bus.send(req.sender, req.receiver, MessageType.CONSULT_REQUEST,
                      {"consultation_id": req.consultation_id, "decision": ctx.kind,
                       "condition": ctx.condition, "interaction_type": req.interaction_type,
                       "text": req.text},
                      correlation_id=req.consultation_id, text=req.text)
        return event

    def question(self, req: ConsultRequest) -> Any:
        return self._request("consult_question", req)

    def delegation(self, req: ConsultRequest) -> Any:
        return self._request("consult_delegation", req)

    def response(self, resp: ConsultResponse) -> Any:
        ctx = self._ctx(resp.consultation_id)
        event = self._emit("consult_response", ctx, resp.sender, resp.receiver, "response",
                           text=resp.text, latency_ms=resp.latency_ms)
        self.bus.send(resp.sender, resp.receiver, MessageType.CONSULT_RESPONSE,
                      {"consultation_id": resp.consultation_id, "text": resp.text,
                       "latency_ms": resp.latency_ms, "model": resp.model},
                      correlation_id=resp.consultation_id, text=resp.text)
        return event

    def refused(self, ctx: Any, reason: str, interaction_type: str = "question",
                target: Optional[str] = None) -> Any:
        return self._emit("consult_refused", ctx, ctx.owner_id,
                          target if target is not None else (ctx.peer_id or ""),
                          interaction_type, reason=reason)

    def closed(self, ctx: Any, outcome: str, choice: Any, turns: int, latency_ms: float,
               error: str = "") -> Any:
        """`consult_closed`, and `CONSULT_CLOSE` to the peer if a request reached it."""
        extra = {"error": error} if error else {}
        event = self._emit("consult_closed", ctx, ctx.owner_id, ctx.peer_id or "", "decision",
                           outcome=outcome, choice=None if choice is None else str(choice),
                           turns=turns, latency_ms=latency_ms, **extra)
        if ctx.peer_id and (ctx.questions or ctx.delegations):
            self.bus.send(ctx.owner_id, ctx.peer_id, MessageType.CONSULT_CLOSE,
                          {"consultation_id": ctx.consultation_id, "outcome": outcome,
                           "choice": None if choice is None else str(choice)},
                          correlation_id=ctx.consultation_id, text=outcome)
        self._open.pop(ctx.consultation_id, None)
        return event

    def llm_call(self, record: LLMCallRecord, tick: int, ctx: Any = None) -> Any:
        """One model call as the transport audit saw it, inside consultation `ctx` if given."""
        common = (self._common(ctx, "llm_call") if ctx is not None
                  else {"consultation_id": "", "decision_id": "", "decision": "",
                        "condition": "", "interaction_type": "llm_call", "model": self.model})
        return self.logger.emit(
            EventCategory.AGENT, "llm_call", tick=tick, actor=record.agent_id,
            correlation_id=common["consultation_id"], **common,
            agent_role=_role(record.agent_id), call_id=record.call_id, url=record.url,
            requested_model=record.requested_model, served_model=record.served_model,
            latency_ms=record.latency_ms, prompt_tokens=record.prompt_tokens,
            completion_tokens=record.completion_tokens, status=record.status,
            phase=record.phase, error=record.error)
