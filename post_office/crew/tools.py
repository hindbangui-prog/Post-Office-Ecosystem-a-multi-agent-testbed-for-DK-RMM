"""
The owner's two ways to reach its peer, bound to exactly one coworker (spec 7 and 8.3).

CrewAI replaces the implementation of model-backed peer consultation at the
Brain seam while preserving the existing peer map and consultation semantics.
These tools are where the two meet. `make_tools` is given the one peer the
copied `discussion/peers.py` names for this owner, decision kind and trigger
condition, and builds CrewAI's own `Ask question to coworker` and `Delegate
work to coworker` tools around that agent alone (`agents=[peer_agent]`). CrewAI's
coworker graph is never built: no other expert can be reached from here.

The peer is a consultant, never a second controller. When the owner calls a
tool, `_run` (spec 8, step 3):

  a. builds a `ConsultRequest` (owner -> peer, question or delegation);
  b. passes it through `interception.communication.on_request`;
  c. writes `consult_question` / `consult_delegation` and sends `CONSULT_REQUEST`;
  d. hands it to CrewAI's own `_run`, with the peer's briefing, taken from the
     live world at this moment, as the context, prefixed with "You are consulted
     by <Owner>; ...". CrewAI then runs `peer.execute_task(...)`: the peer's own
     model call(s), with no tools, so the peer can only return advice;
  e. builds a `ConsultResponse`, passes it through `on_response`, writes
     `consult_response`, sends `CONSULT_RESPONSE` and returns the advice to the
     owner's reasoning loop as the tool's result.

The two tools share one `ConsultationContext`, which allows one exchange per
consultation. A second use returns "You have already consulted <Peer> for this
decision; decide now."; a call naming any other coworker returns "<Name> is not
available to you for this decision; only <Peer> is." and asks no model. Both
are logged as `consult_refused`.

A request or a response the communication layer withholds (`None`), or a peer
whose own model call fails, gives the owner "no answer from <Peer>" and marks
the consultation, so it closes as `peer_failed` if no decision follows.

Once the consultation is closed (its deadline passed), a tool use still running
in the abandoned worker writes nothing and asks nothing further: it returns
`CLOSED`.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

from crewai.tools.agent_tools.ask_question_tool import AskQuestionTool
from crewai.tools.agent_tools.delegate_work_tool import DelegateWorkTool
from crewai.tools.base_tool import BaseTool
from crewai.utilities.i18n import I18N_DEFAULT
from pydantic import PrivateAttr

from ..core.visible import visible
from .audit import calling
from .interception import ConsultRequest, ConsultResponse
from .roles import ROLES

#: What CrewAI's agent tool returns when the coworker's execute_task raised.
_PEER_ERROR = I18N_DEFAULT.errors("agent_tool_execution_error").split("{")[0]

#: What a tool use returns once its consultation has been closed.
CLOSED = "This consultation is closed; nothing was asked."


@dataclass
class ConsultationContext:
    consultation_id: str
    owner_id: str
    peer_id: Optional[str]
    tick: int
    decision_id: str
    kind: str
    condition: str
    options: Sequence[Any]
    exchanges_used: int = 0
    max_exchanges: int = 1
    #: Every utterance, in order: {"speaker", "interaction_type", "text"}.
    turns: List[Dict[str, Any]] = field(default_factory=list)
    questions: int = 0
    delegations: int = 0
    #: Set when a request or response did not get through, or the peer's model failed.
    peer_failed: bool = False
    peer_error: str = ""
    #: Set once the consultation has closed; nothing more is written for it.
    closed: bool = False
    #: Set when it closed because the deadline passed.
    timed_out: bool = False


def _role(agent_id: Optional[str]) -> str:
    spec = ROLES.get(agent_id or "")
    return spec.role if spec is not None else str(agent_id or "")


def _id_of(name: str) -> str:
    """The expert id a coworker name refers to, or the name itself."""
    wanted = " ".join(str(name or "").split()).replace('"', "").casefold()
    for agent_id, spec in ROLES.items():
        if spec.role.casefold() == wanted or agent_id.casefold() == wanted:
            return agent_id
    return str(name or "")


class _PeerTool:
    """Spec 8, step 3, shared by the two tools. A mixin: it declares no fields."""

    _ctx: ConsultationContext
    _service: Any

    def _consult(self, interaction_type: str, text: str, context: str,
                 coworker: Optional[str], kwargs: Dict[str, Any],
                 ask_peer: Callable[[str, str, str], Any]) -> str:
        ctx, service = self._ctx, self._service
        events = service.events
        peer_agent = self.agents[0]  # type: ignore[attr-defined]
        peer_role = peer_agent.role
        named = self._get_coworker(coworker, **kwargs) or ""  # type: ignore[attr-defined]
        same = self.sanitize_agent_name  # type: ignore[attr-defined]

        if same(named) != same(peer_role):
            who = named.strip() or "That coworker"
            if not service.guarded(ctx, lambda: events.refused(
                    ctx, f"disallowed coworker {who}: only {peer_role} may be consulted",
                    interaction_type, target=_id_of(named))):
                return CLOSED
            return f"{who} is not available to you for this decision; only {peer_role} is."
        if ctx.exchanges_used >= ctx.max_exchanges:
            if not service.guarded(ctx, lambda: events.refused(
                    ctx, f"second exchange: {peer_role} was already consulted",
                    interaction_type)):
                return CLOSED
            return f"You have already consulted {peer_role} for this decision; decide now."

        no_answer = f"no answer from {peer_role}"
        request = ConsultRequest(consultation_id=ctx.consultation_id, tick=ctx.tick,
                                 sender=ctx.owner_id, receiver=str(ctx.peer_id),
                                 interaction_type=interaction_type, text=str(text or ""),
                                 context=str(context or ""))
        ctx.exchanges_used += 1
        request = service.interception.communication.on_request(request)
        if request is None:
            ctx.peer_failed, ctx.peer_error = True, "the request did not reach the peer"
            return no_answer

        def write_request() -> None:
            (events.question if interaction_type == "question" else events.delegation)(request)
            ctx.turns.append({"speaker": ctx.owner_id, "interaction_type": interaction_type,
                              "text": request.text})
            if interaction_type == "question":
                ctx.questions += 1
            else:
                ctx.delegations += 1

        if not service.guarded(ctx, write_request):
            return CLOSED

        briefing = service.briefing_source(str(ctx.peer_id))
        peer_context = (f"You are consulted by {_role(ctx.owner_id)}; answer in at most three "
                        f"sentences; recommend, do not act.\n\n"
                        f"Your current state:\n"
                        f"{json.dumps(briefing, sort_keys=True, default=str)}\n\n"
                        f"What {_role(ctx.owner_id)} told you:\n{request.context}")
        started = time.perf_counter()
        with service.inside(ctx), calling(str(ctx.peer_id), "peer"):
            reply = ask_peer(request.text, peer_context, peer_role)
        latency_ms = round((time.perf_counter() - started) * 1000.0, 1)
        reply_text = str(reply if reply is not None else "")
        if reply_text.startswith(_PEER_ERROR):
            ctx.peer_failed, ctx.peer_error = True, reply_text
            return no_answer

        response = ConsultResponse(consultation_id=ctx.consultation_id, tick=ctx.tick,
                                   sender=str(ctx.peer_id), receiver=ctx.owner_id,
                                   text=visible(reply_text), latency_ms=latency_ms,
                                   model=service.settings.model)
        response = service.interception.communication.on_response(response)
        if response is None:
            ctx.peer_failed, ctx.peer_error = True, "the response did not reach the owner"
            return no_answer

        def write_response() -> None:
            events.response(response)
            ctx.turns.append({"speaker": response.sender, "interaction_type": "response",
                              "text": response.text})

        if not service.guarded(ctx, write_response):
            return CLOSED
        return response.text


class AskPeerTool(_PeerTool, AskQuestionTool):
    """CrewAI's `Ask question to coworker`, bound to the one allowed peer."""

    _ctx: ConsultationContext = PrivateAttr()
    _service: Any = PrivateAttr()

    def _run(self, question: str, context: str, coworker: Optional[str] = None,
             **kwargs: Any) -> str:
        return self._consult("question", question, context, coworker, kwargs,
                             lambda text, brief, role: AskQuestionTool._run(
                                 self, question=text, context=brief, coworker=role))


class DelegateToPeerTool(_PeerTool, DelegateWorkTool):
    """CrewAI's `Delegate work to coworker`, bound to the one allowed peer."""

    _ctx: ConsultationContext = PrivateAttr()
    _service: Any = PrivateAttr()

    def _run(self, task: str, context: str, coworker: Optional[str] = None,
             **kwargs: Any) -> str:
        return self._consult("delegation", task, context, coworker, kwargs,
                             lambda text, brief, role: DelegateWorkTool._run(
                                 self, task=text, context=brief, coworker=role))


def make_tools(ctx: ConsultationContext, peer_agent: Any, service: Any) -> List[BaseTool]:
    """The ask and delegate tools for one consultation, both bound to `[peer_agent]`."""
    coworkers = peer_agent.role
    ask = AskPeerTool(agents=[peer_agent],
                      description=I18N_DEFAULT.tools("ask_question").format(coworkers=coworkers))
    delegate = DelegateToPeerTool(
        agents=[peer_agent],
        description=I18N_DEFAULT.tools("delegate_work").format(coworkers=coworkers))
    for tool in (ask, delegate):
        tool._ctx = ctx
        tool._service = service
    return [ask, delegate]
