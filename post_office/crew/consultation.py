"""
Synchronous owner -> peer -> owner consultation through CrewAI (spec 8).

CrewAI replaces the implementation of model-backed peer consultation at the
Brain seam while preserving the existing peer map and consultation semantics.
`ConsultationService.run` is what a `CrewBrain` hands a decision to:

1. the peer is `peer_for(owner, kind, trigger.condition)` from the copied
   `discussion/peers.py`, the only source of truth for who may be consulted;
   a `CSL-%04d` id is minted and `consult_opened` written;
2. the owner's CrewAI `Task` is `render(question)`, plus, when there is a peer,
   the offer of one question or one delegated sub-question, plus the demand for
   a closing `DECISION:` line;
3. the owner gets `make_tools(ctx, peer_agent, self)` (tools bound to that one
   peer) when there is a peer and `tools=[]` otherwise;
4. `owner.execute_task(task, tools=...)` runs in a worker thread that the tick
   waits for up to `settings.consult_deadline_s` (`join_until`: short joins of
   `JOIN_STEP_S`, so Ctrl-C is honoured on Windows too). CrewAI never re-runs
   the task (`max_retry_limit=0` in `roles.py`): a failed model call, even the
   owner's after the peer answered, closes the consultation `model_failed`;
5. the owner's final text is read with `parse_choice`; a valid choice becomes
   `Answer(choice, <last visible line>, source="crewai:<model>", 1.0)`, anything
   else the rule's answer marked `[fallback: <why>]`; `consult_closed` is
   written with the outcome and `CONSULT_CLOSE` sent to the peer if it was asked.

The peer is a consultant, never a second controller: its CrewAI task runs with
no tools and returns advice. Only the owner's parsed `DECISION:` becomes an
`Answer`, which `BaseAgent._validate` (the policy gate) checks before the
agent's own Python applies it. Nothing here writes to the world.

Outcomes: `decided`, `no_valid_decision` (the reply named no allowed answer),
`timeout` (the deadline passed), `model_failed` (the owner's model call raised)
and `peer_failed` (the peer gave no answer and the owner reached no decision).

Deadline. On timeout the worker is abandoned, not killed (CrewAI cannot be
cancelled): its consultation is marked closed, so a tool use it still makes
writes nothing and asks the peer nothing, its eventual result is discarded, and
every model call whose record arrives after the deadline is recorded with
`phase="late"` (the audit callback reads the worker's consultation from a
context variable). Until the worker finishes, its owner and peer are busy; a
consultation that needs a busy expert falls back at once (outcome `timeout`)
rather than run two CrewAI loops on one agent. `drain()` waits for abandoned
workers, for a clean shutdown. A Ctrl-C (`KeyboardInterrupt`) while the tick
waits abandons the worker the same way and is then raised on: the consultation
stays without its `consult_closed`, and the run stops.

Every model call is also written as an `llm_call` event (spec 12) while its
consultation is open, under the consultation's tick; a late call is kept in
`llm_calls()` only, so an abandoned worker never writes into the log
concurrently with the tick. The owner's calls are counted as they arrive, and
`retries` is the owner model calls beyond the first call and the
post-exchange call (`expected_owner_calls`).

`interception.agent.after_answer` sees the owner's parsed answer before it is
returned; its result is checked against the question's options again, and an
answer outside them (or a hook that raises) closes the consultation as
`no_valid_decision` with the rule's answer, so nothing off the list reaches
the gate.
"""

from __future__ import annotations

import contextlib
import contextvars
import threading
import time
import warnings
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, Iterator, List, Optional

from crewai import Agent, Task

from ..agents.brain import Answer, Question
from ..config.ollama import OllamaSettings
from ..discussion.peers import peer_for
from .audit import LLMCallRecord, OllamaAudit, calling
from .events import ConsultEvents
from .interception import Interception
from .parse import last_visible_line, parse_choice, render
from .roles import ROLES
from .tools import ConsultationContext, make_tools

OUTCOMES = ("decided", "no_valid_decision", "timeout", "model_failed", "peer_failed")
#: The longest single `join` while the tick waits for a worker. A join without a
#: timeout (or a long one) is not interrupted by Ctrl-C on Windows.
JOIN_STEP_S = 0.2
EXPECTED_OUTPUT = "a DECISION line"
DECISION_DEMAND = "End with exactly one line `DECISION: <one allowed answer>`."

#: The consultation the current thread (or task) is working for.
_ACTIVE: contextvars.ContextVar[Optional[ConsultationContext]] = contextvars.ContextVar(
    "consultation_active", default=None)


@dataclass
class ConsultOutcome:
    answer: Answer
    consultation_id: str
    outcome: str
    peer: str
    turns: int
    latency_ms: float
    model: str
    #: Per-decision counts the brain adds to its stats: consultations, questions,
    #: delegations, timeouts, retries, parse_failures, rejected_answers.
    counts: Dict[str, int] = field(default_factory=dict)
    #: Why the model's answer was not used, "" when it was.
    error: str = ""
    #: The owner task description the model was given (None if none was).
    prompt: Optional[str] = None


@contextlib.contextmanager
def _quiet_crewai() -> Iterator[None]:
    """
    Ignore the DeprecationWarnings CrewAI 1.15 raises about its own fields.

    Validating an Agent (which every `Task(agent=...)` does) and building its
    executor read deprecated fields none of which is set here. The filter is
    entered on the tick's thread around the worker's start and join, never
    inside the worker, so the process-wide filter list is only ever saved and
    restored by one thread.
    """
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=DeprecationWarning, module=r"crewai\.")
        yield


def _role(agent_id: Optional[str]) -> str:
    spec = ROLES.get(agent_id or "")
    return spec.role if spec is not None else str(agent_id or "")


def join_until(worker: threading.Thread, timeout_s: float, step_s: float = JOIN_STEP_S) -> None:
    """
    Wait for `worker` to finish, at most `timeout_s` seconds, in joins of at
    most `step_s`, so a `KeyboardInterrupt` reaches the waiting thread within
    one step on every platform.
    """
    end = time.monotonic() + max(0.0, float(timeout_s))
    while worker.is_alive():
        left = end - time.monotonic()
        if left <= 0:
            return
        worker.join(min(step_s, left))


def expected_owner_calls(ctx: ConsultationContext) -> int:
    """
    The owner model calls a clean consultation makes: the first, plus the one
    after an exchange (whether the peer answered or "no answer" came back).
    Every owner call beyond these is a retry: CrewAI's executor looping again
    because a tool call could not be parsed, named a tool or coworker that is
    not on offer, or asked for a second exchange.
    """
    return 2 if ctx.exchanges_used else 1


def describe(question: Question, peer_id: Optional[str]) -> str:
    """The owner's task description (spec 8, step 2)."""
    parts = [render(question)]
    if peer_id:
        peer = _role(peer_id)
        parts.append(f"You may ask {peer} one question with the tool `Ask question to "
                     f"coworker`, or delegate one sub-question with `Delegate work to "
                     f"coworker`; the answer is advice, the decision is yours.")
    parts.append(DECISION_DEMAND)
    return "\n".join(parts)


class ConsultationService:
    def __init__(self, agents: Dict[str, Agent], world: Any, bus: Any, logger: Any,
                 interception: Interception, settings: OllamaSettings, audit: OllamaAudit,
                 briefing_source: Callable[[str], Any],
                 events: Optional[ConsultEvents] = None) -> None:
        self.agents = dict(agents)
        self.world = world
        self.bus = bus
        self.logger = logger
        self.interception = interception
        self.settings = settings
        self.audit = audit
        self.briefing_source = briefing_source
        self.events = events if events is not None else ConsultEvents(logger, bus,
                                                                      settings.model)
        # The audit reports each model call here.
        audit.on_call = self._on_call
        self._lock = threading.RLock()
        self._count = 0
        self._busy: Dict[str, int] = {}
        #: Consultations whose CrewAI worker is running, by id (`in_flight`).
        self._open: Dict[str, ConsultationContext] = {}
        self._workers: List[threading.Thread] = []
        self._history: Deque[Dict[str, Any]] = deque(maxlen=500)
        self._calls: Deque[Dict[str, Any]] = deque(maxlen=2000)
        self._outcomes: Counter = Counter()
        self._pairs: Counter = Counter()
        #: Decisions in which the owner actually asked or delegated to its peer.
        self._exchanges = 0
        self._latencies: List[float] = []

    # --------------------------------------------------------- shared state
    def guarded(self, ctx: ConsultationContext, write: Callable[[], Any]) -> bool:
        """Run `write` unless `ctx` has closed; whether it ran."""
        with self._lock:
            if ctx.closed:
                return False
            write()
            return True

    @contextlib.contextmanager
    def inside(self, ctx: ConsultationContext) -> Iterator[None]:
        """Mark the model calls made in this block as belonging to `ctx`."""
        token = _ACTIVE.set(ctx)
        try:
            yield
        finally:
            _ACTIVE.reset(token)

    def _on_call(self, record: LLMCallRecord) -> None:
        ctx = _ACTIVE.get()
        with self._lock:
            if ctx is not None and ctx.timed_out:
                record.phase = "late"
            if ctx is not None and not ctx.closed and record.phase == "owner":
                ctx.owner_calls += 1
            row = record.as_dict()
            row["consultation_id"] = ctx.consultation_id if ctx is not None else ""
            row["tick"] = ctx.tick if ctx is not None else self.world.tick
            self._calls.append(row)
            if ctx is not None and not ctx.closed:
                self.events.llm_call(record, ctx.tick, ctx)

    def _hold(self, *agent_ids: Optional[str]) -> None:
        with self._lock:
            for agent_id in agent_ids:
                if agent_id:
                    self._busy[agent_id] = self._busy.get(agent_id, 0) + 1

    def _release(self, *agent_ids: Optional[str]) -> None:
        with self._lock:
            for agent_id in agent_ids:
                if agent_id and agent_id in self._busy:
                    self._busy[agent_id] -= 1
                    if self._busy[agent_id] <= 0:
                        del self._busy[agent_id]

    def busy(self, agent_id: str) -> bool:
        """Whether an abandoned worker is still running this expert's CrewAI agent."""
        with self._lock:
            return agent_id in self._busy

    def in_flight(self) -> List[Dict[str, Any]]:
        """
        The consultations whose worker is running now, oldest first, and who
        in each is inside a model call: the peer between the owner's request
        and the peer's response, the owner otherwise. A worker abandoned at its
        deadline stays here, marked `late`, until it finishes.
        """
        with self._lock:
            rows = []
            for ctx in self._open.values():
                asking = bool(ctx.turns) and ctx.turns[-1]["interaction_type"] in (
                    "question", "delegation")
                rows.append({"consultation_id": ctx.consultation_id, "tick": ctx.tick,
                             "owner": ctx.owner_id, "peer": ctx.peer_id or "",
                             "kind": ctx.kind, "condition": ctx.condition,
                             "agent": (ctx.peer_id if asking and ctx.peer_id
                                       else ctx.owner_id),
                             "phase": "peer" if asking and ctx.peer_id else "owner",
                             "late": bool(ctx.timed_out)})
            return rows

    def drain(self, timeout: float = 30.0) -> bool:
        """Wait for abandoned workers to finish; whether all did within `timeout`."""
        end = time.monotonic() + timeout
        with _quiet_crewai():
            for worker in list(self._workers):
                join_until(worker, end - time.monotonic())
        self._workers = [w for w in self._workers if w.is_alive()]
        return not self._workers

    # ------------------------------------------------------------- the run
    def run(self, owner_id: str, question: Question, trigger: Any,
            rule_answer: Optional[Answer]) -> ConsultOutcome:
        condition = str(getattr(trigger, "condition", "") or "") if trigger is not None else ""
        peer = peer_for(owner_id, question.kind, condition) if condition else None
        if peer is not None and peer not in self.agents:
            peer = None  # the peer has no model behind it: the owner decides alone
        with self._lock:
            self._count += 1
            consultation_id = f"CSL-{self._count:04d}"
        ctx = ConsultationContext(consultation_id=consultation_id, owner_id=owner_id,
                                  peer_id=peer, tick=int(self.world.tick),
                                  decision_id=question.decision_id, kind=question.kind,
                                  condition=condition, options=tuple(question.options))
        self.events.opened(ctx, peer, question.options)

        busy = [a for a in (owner_id, peer) if a and self.busy(a)]
        if busy:
            return self._close(ctx, question, rule_answer, "timeout", 0.0, None,
                               why=f"{busy[0]} is still running a consultation past its "
                                   f"deadline")

        hooks = self.interception.agent
        description: Optional[str] = None
        try:
            description = hooks.before_prompt(owner_id, describe(question, peer))
            owner = self.agents[owner_id]
            tools = make_tools(ctx, self.agents[peer], self) if peer else []
            with _quiet_crewai():
                task = Task(description=description, expected_output=EXPECTED_OUTPUT,
                            agent=owner)
            hooks.before_llm_call(owner_id)
        except Exception as exc:  # an opened consultation is always closed
            return self._close(ctx, question, rule_answer, "model_failed", 0.0, description,
                               why=f"{type(exc).__name__}: {exc}")

        box: Dict[str, Any] = {}

        def work() -> None:
            try:
                with self.inside(ctx), calling(owner_id, "owner"):
                    box["text"] = owner.execute_task(task, tools=tools)
            except BaseException as exc:  # reported as model_failed, never raised into the tick
                box["error"] = exc
            finally:
                self._release(owner_id, peer)
                with self._lock:
                    self._open.pop(consultation_id, None)

        self._hold(owner_id, peer)
        with self._lock:
            self._open[consultation_id] = ctx
        worker = threading.Thread(target=contextvars.copy_context().run, args=(work,),
                                  name=f"consult-{consultation_id}", daemon=True)
        started = time.perf_counter()
        with _quiet_crewai():
            worker.start()
            try:
                join_until(worker, self.settings.consult_deadline_s)
            except BaseException:  # Ctrl-C: abandon the worker as at a deadline, then stop
                with self._lock:
                    ctx.timed_out = ctx.closed = True
                self._workers.append(worker)
                raise
        latency_ms = round((time.perf_counter() - started) * 1000.0, 1)

        if worker.is_alive():
            with self._lock:  # from here on the worker writes nothing for ctx
                ctx.timed_out = ctx.closed = True
            self._workers.append(worker)
            return self._close(ctx, question, rule_answer, "timeout", latency_ms, description,
                               why=f"no decision within {self.settings.consult_deadline_s:g} s")
        if "error" in box:
            exc = box["error"]
            return self._close(ctx, question, rule_answer, "model_failed", latency_ms,
                               description, why=f"{type(exc).__name__}: {exc}")

        text = str(box.get("text") or "")
        choice = parse_choice(text, question.options)
        if choice is None or (question.options and choice not in tuple(question.options)):
            from ..discussion.prompts import parse_decision

            has_line, _ = parse_decision(text, question.options)
            outcome = "peer_failed" if ctx.peer_failed else "no_valid_decision"
            why = ("the DECISION line named no allowed answer" if has_line
                   else "no allowed answer in the reply")
            if ctx.peer_failed:
                why = f"no answer from {_role(peer)} and {why}"
            return self._close(ctx, question, rule_answer, outcome, latency_ms, description,
                               why=why,
                               counts={"rejected_answers" if has_line else "parse_failures": 1})
        answer = Answer(choice, last_visible_line(text), source=f"crewai:{self.settings.model}",
                        confidence=1.0)
        try:
            answer = hooks.after_answer(owner_id, answer)
        except Exception as exc:  # an opened consultation is always closed
            return self._close(ctx, question, rule_answer, "no_valid_decision", latency_ms,
                               description, why=f"{type(exc).__name__}: {exc}",
                               counts={"rejected_answers": 1})
        # What a hook hands back is checked against the options again: only
        # an allowed answer may reach the gate.
        if not isinstance(answer, Answer) or answer.choice is None or (
                question.options and answer.choice not in tuple(question.options)):
            shown = getattr(answer, "choice", answer)
            return self._close(ctx, question, rule_answer, "no_valid_decision", latency_ms,
                               description,
                               why=f"the answer {shown!r} was not among the allowed answers",
                               counts={"rejected_answers": 1})
        return self._close(ctx, question, rule_answer, "decided", latency_ms, description,
                           answer=answer)

    def _close(self, ctx: ConsultationContext, question: Question,
               rule_answer: Optional[Answer], outcome: str, latency_ms: float,
               prompt: Optional[str], why: str = "", answer: Optional[Answer] = None,
               counts: Optional[Dict[str, int]] = None) -> ConsultOutcome:
        from ..agents.base import BaseAgent

        if answer is None:
            answer = BaseAgent._fallback(rule_answer, why)
        turns = len(ctx.turns)
        with self._lock:
            ctx.closed = True
            retries = max(0, ctx.owner_calls - expected_owner_calls(ctx))
            self.events.closed(ctx, outcome, answer.choice if outcome == "decided" else None,
                               turns, latency_ms,
                               error=why or (ctx.peer_error if ctx.peer_failed else ""))
            self._outcomes[outcome] += 1
            if ctx.peer_id and (ctx.questions or ctx.delegations):
                self._exchanges += 1
                self._pairs[f"{ctx.owner_id}->{ctx.peer_id}"] += 1
            self._latencies.append(float(latency_ms))
            self._history.append(self._row(ctx, answer, outcome, latency_ms))
        tally = {"consultations": 1 if (ctx.questions or ctx.delegations) else 0,
                 "questions": ctx.questions, "delegations": ctx.delegations,
                 "timeouts": 1 if outcome == "timeout" else 0, "retries": retries}
        tally.update(counts or {})
        return ConsultOutcome(answer=answer, consultation_id=ctx.consultation_id,
                              outcome=outcome, peer=ctx.peer_id or "", turns=turns,
                              latency_ms=latency_ms, model=self.settings.model,
                              counts=tally, error=why, prompt=prompt)

    def _row(self, ctx: ConsultationContext, answer: Answer, outcome: str,
             latency_ms: float) -> Dict[str, Any]:
        said = {t["interaction_type"]: t["text"] for t in reversed(ctx.turns)}
        request = said.get("question", said.get("delegation", ""))
        return {"id": ctx.consultation_id, "tick": ctx.tick, "owner": ctx.owner_id,
                "peer": ctx.peer_id or "", "kind": ctx.kind, "condition": ctx.condition,
                "decision_id": ctx.decision_id, "request": request,
                "response": said.get("response", ""),
                "decision": None if answer.choice is None else str(answer.choice),
                "source": answer.source, "outcome": outcome, "latency_ms": latency_ms,
                "model": self.settings.model}

    # ------------------------------------------------------------- reading
    def recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in list(self._history)[-limit:]]

    def llm_calls(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in list(self._calls)[-limit:]]

    def summary(self) -> Dict[str, Any]:
        """
        The service's counts.

        `model_decisions` is every model decision opened (every `CSL-` id,
        with or without a peer, however it closed); `exchanges` the decisions
        in which the owner actually asked or delegated to its peer, which is
        what `CrewBrain.stats()["consultations"]` counts per expert; `by_pair`
        counts those exchanges by `owner->peer`. `outcomes` and
        `mean_latency_ms` cover every model decision.
        """
        with self._lock:
            mean = (round(sum(self._latencies) / len(self._latencies), 1)
                    if self._latencies else None)
            return {"model_decisions": self._count, "exchanges": self._exchanges,
                    "by_pair": dict(sorted(self._pairs.items())),
                    "outcomes": dict(sorted(self._outcomes.items())),
                    "mean_latency_ms": mean}
