"""
What every agent in the ecosystem has in common.

An agent here is a small, self-contained thing: it has an identity, a place in
the hierarchy, an inbox, a brain for its judgement calls, and one method that
runs once per tick. It reaches the outside world through exactly two handles --
`send`, which the bus gives it, and `world`, which holds the facility, the
tasks and the fleet.

What an agent may not do, anywhere in this package:

  * call another agent's methods, or touch another agent's attributes;
  * send a message as somebody else (the bus closes over the sender's id);
  * take a judgement call without asking its brain, which is what keeps the
    LLM seam real rather than decorative.

`step()` is deliberately shaped as "read the inbox, then do your own work".
Agents that only react implement `handle`; agents that also have standing
duties -- the resource agent watching batteries, the planner watching the
intake dock -- implement `tick_work` as well.
"""

from __future__ import annotations

import contextlib
import time

from typing import Any, Callable, Dict, List, Optional, Sequence

from ..communication.bus import MessageBus
from ..communication.directory import AgentKind
from ..communication.events import EventCategory
from ..communication.message import Message, MessageType
from ..core.world import World
from ..policy import PolicyGate, Proposal
from .brain import Answer, Brain, DeterministicBrain, Question
from .deferral import (DETERMINISTIC, LLM_ACCEPTED, LLM_FAILED, LLM_PENDING,
                       LLM_REJECTED, LLM_TIMEOUT, PENDING_LLM_DECISION, Deferral)
from .reasoning import (DEFAULT_POLICY, POLICIES, REASONS, Trigger, TriggerSet,
                        rule_insufficient)



@contextlib.contextmanager
def _nothing():
    """A bracket that does nothing, for a run with no tracing available."""
    yield


class BaseAgent:
    """An addressable participant with a brain and one tick of work to do."""

    kind: AgentKind = AgentKind.EXPERT

    def __init__(self, agent_id: str, role: str,
                 parent_id: Optional[str] = None,
                 brain: Optional[Brain] = None) -> None:
        self.agent_id = agent_id
        self.role = role
        self.parent_id = parent_id
        self.brain: Brain = brain or DeterministicBrain()
        self.world: Optional[World] = None
        self.bus: Optional[MessageBus] = None
        self._send: Optional[Callable[..., Optional[Message]]] = None
        self.received = 0
        self.sent = 0
        #: A perturbation's hand on what this agent is told, or None -- which
        #: is what it is for every agent in every ordinary run. Installed by
        #: an injector for the length of a window and removed afterwards, so
        #: that "no perturbation" is the absence of a filter rather than a
        #: filter that does nothing.
        self.facts_filter = None
        self.decisions: List[Dict[str, Any]] = []
        #: Serial for this agent's decisions, so each one has an id the
        #: model requests made inside it can be joined to.
        self._decisions_made = 0
        #: When this agent's decisions stop being routine. Empty means every
        #: decision is routine, which is the right default for an agent that
        #: has not thought about the question.
        self.triggers = TriggerSet()
        #: When the model is consulted: `insufficient` (the rule answers
        #: first; the model only when that answer cannot stand) or
        #: `any_trigger` (every fired trigger goes to the model, as the
        #: recorded battery was run). Set from the configuration by the
        #: ecosystem; see `reasoning.rule_insufficient`.
        self.consult_policy = DEFAULT_POLICY
        #: Running tally, so a stressed run can be read without the trace.
        #: `gate_refusals` is spelled out rather than called `refused`,
        #: because more than one agent already counts something it turned
        #: away under that name and a silent collision here would report
        #: refused parcels as refused decisions.
        self.reasoned = 0
        self.gate_refusals = 0
        self.trigger_counts: Dict[str, int] = {}
        #: Conditions that fired while the rule's answer stood, by reason.
        self.noted_counts: Dict[str, int] = {}
        #: Where each decision's answer came from, counted:
        #: `deterministic`, `llm/<trigger>`, or `fallback` (the model was
        #: asked and the rule answered after all).
        self.path_counts: Dict[str, int] = {}
        #: Decisions whose trigger would have called the model while the
        #: facility was idle, answered by the rule instead
        #: (`simulation.activity`).
        self.idle_skips = 0
        #: In a live run, decisions whose model was still busy with an earlier
        #: question, answered by the rule instead (`decide`).
        self.busy_skips = 0
        #: Decisions by how they were handled (`rule_sufficient`,
        #: `llm_insufficient`, `idle_rule`, `idle_no_rule`, `rule_no_model`,
        #: and in a live run `busy_rule`, `busy_no_rule`).
        self.handling_counts: Dict[str, int] = {}
        #: Whether a condition that says the rule covers its case is believed:
        #: `authoritative` (it is -- the rule answers and the model is not
        #: asked) or `legacy` (conditions are read as they always were). Only
        #: the app's Normal-scenario runs are authoritative; every experiment
        #: and every headless run keeps `legacy`, so a recorded run and its
        #: replay take the same decisions to the model. Set by the ecosystem.
        self.rule_coverage = "legacy"
        #: Whether a decision that goes to the model may finish on a later
        #: tick (`decide` returns a pending answer and the caller's `Deferral`
        #: applies the real one when it comes). Off: the tick waits for the
        #: model, which is what every headless run and experiment does, so a
        #: recorded run and its replay take the same decisions on the same
        #: ticks. The live page turns it on (`api/runner.py`), so a slow model
        #: holds up one parcel, robot or task -- not the fleet. Set by the
        #: ecosystem from `async_decisions`.
        self.async_decisions = False
        #: How many ticks a pending model decision may take before the rule's
        #: answer is used instead (`llm_timeout`); 0 waits for the model up to
        #: the consultation service's own deadline. From `llm_deadline_ticks`.
        self.llm_deadline_ticks = 0
        #: Model decisions under way, by (kind, deferral key): one at a time
        #: per subject, so a robot reported blocked on every tick is not asked
        #: about once per tick while its first question is with the model.
        self._pending: Dict[Any, Dict[str, Any]] = {}
        self.install_rules()
        self.install_triggers()

    # ----------------------------------------------------------------- setup
    def install_rules(self) -> None:
        """
        Register this agent's deterministic rules on its brain.

        Subclasses override this rather than the constructor, so that an agent
        given a `CrewBrain` still contributes its rules as that brain's
        fallback -- an LLM agent that loses its model server degrades to the
        deterministic agent instead of stopping.
        """

    def install_triggers(self) -> None:
        """
        Declare when this agent's decisions stop being routine.

        Overridden beside `install_rules`, because the two are halves of the
        same statement: the rule says what the ordinary answer is, and the
        trigger says when the ordinary answer is not good enough. An agent
        that declares nothing here reasons about nothing, and runs entirely on
        its rules.
        """

    def rules(self) -> Optional[DeterministicBrain]:
        """The deterministic brain to register rules on, whichever brain is in use."""
        if isinstance(self.brain, DeterministicBrain):
            return self.brain
        fallback = getattr(self.brain, "fallback", None)
        return fallback if isinstance(fallback, DeterministicBrain) else None

    def attach(self, bus: MessageBus, world: World) -> None:
        """Join the ecosystem. Registration is what makes the agent addressable."""
        self.bus = bus
        self.world = world
        bus.register(self.agent_id, self.kind, role=self.role,
                     parent_id=self.parent_id)
        self._send = bus.sender_for(self.agent_id)
        self.on_attach()

    def on_attach(self) -> None:
        """Anything an agent wants to do once it knows who it is."""

    def _rule_covered(self) -> Optional[bool]:
        """
        What a condition says when its rule has an explicit branch for the case.

        For a condition to return as `Trigger(..., rule_sufficient=...)`: True
        when rule coverage is authoritative -- the condition is noted and the
        rule answers -- and None otherwise, which leaves the reason to decide
        exactly as it did before rule coverage was a setting.
        """
        return True if self.rule_coverage == "authoritative" else None

    def rule_covers(self, kind: str, answer: Answer, question: Question) -> bool:
        """
        Whether the rule's `answer` settles the case a fired condition describes.

        A condition reads the facts and says "this is a hard case"; it cannot
        see the rule's answer. An agent that knows its rule has a branch for
        exactly that case, and can tell from the answer that the branch was
        taken, says so here, and the model is not asked. False (the default)
        leaves the decision to the condition, as before.
        """
        return False

    # -------------------------------------------------------------- speaking
    def send(self, receiver: str, message_type: MessageType,
             content: Optional[Dict[str, Any]] = None,
             correlation_id: str = "", text: str = "",
             in_reply_to: Optional[str] = None) -> Optional[Message]:
        if self._send is None:
            raise RuntimeError(f"{self.agent_id} is not attached to a bus")
        message = self._send(receiver, message_type, content or {},
                             correlation_id, text, in_reply_to)
        if message is not None:
            self.sent += 1
        return message

    def reply(self, to: Message, message_type: MessageType,
              content: Optional[Dict[str, Any]] = None,
              text: str = "") -> Optional[Message]:
        return self.send(to.sender, message_type, content or {},
                         correlation_id=to.correlation_id, text=text,
                         in_reply_to=to.message_id)

    # -------------------------------------------------------------- thinking
    def decide(self, kind: str, prompt: str, options: Sequence[Any] = (),
               correlation_id: str = "", deferral: Optional[Deferral] = None,
               **facts) -> Answer:
        """
        Take one decision, the whole way through, and write down what happened.

            perceive  the facts this decision was given
            triage    routine, or is there a named reason to think about it?
            answer    the rule, or the brain
            validate  schema, then policy, then the state of the floor
            record    mode, trigger, verdict, rationale

        The triage step is what keeps an LLM run affordable and, more to the
        point, interesting: a model asked to confirm two hundred obvious
        answers is a model whose interesting answers cannot be found. The
        validation step is what keeps it safe to let the model be interesting
        at all -- nothing it proposes reaches the floor unchecked, so the
        authority granted to it can be generous within its own domain.

        A refusal is not an error and does not stop the decision. The agent's
        own rule answers instead, the refusal is counted by stage, and the run
        carries on; under stress those counts are a measurement rather than a
        fault report.

        `deferral` says how to finish the decision on a later tick. It is
        used only when `async_decisions` is on (the live page) and the rule
        was insufficient: the consultation is started, a pending answer
        (`is_pending`) comes back at once, and `_collect_decisions` checks and
        applies the model's answer when it arrives -- so only this decision's
        subject waits, not the tick. Otherwise every decision, the model's
        included, is answered inside this call. When the brain can consult a
        peer (`answer_consulting`), the consultation also happens here, and
        its id, peer and turn count are written on the decision record.
        """
        # The facts this decision is taken from, as they reach the agent. A
        # perturbation may sit here and hand it a picture of the facility that
        # is wrong but well-formed; outside one this is a None check. What the
        # agent then does with that picture is its own, and whatever it
        # proposes still goes through the gate below.
        given = dict(facts)
        if self.facts_filter is not None:
            try:
                given = dict(self.facts_filter(kind, given))
            except Exception:
                given = dict(facts)      # a broken filter must not stop a run
        self._decisions_made += 1
        decision_id = f"{self.agent_id}:{kind}:{self.tick}:{self._decisions_made}"
        # Minted before the question rather than after, so the question can
        # carry it. An observer at the brain sees the answer and nothing else;
        # without this it has to guess which record the answer became, and
        # `(tick, kind)` is not a key -- two robots blocked in one tick give
        # this agent two `resolve_block` decisions with identical coordinates.
        question = Question(kind=kind, asked_by=self.agent_id, prompt=prompt,
                            options=tuple(options), facts=given,
                            correlation_id=correlation_id,
                            decision_id=decision_id)

        # ---- triage ----------------------------------------------------
        # Conditional automation. The Python rule answers first, whenever
        # there is one. The model is invoked only when that answer is
        # insufficient: no rule, no admissible answer, a rule that says it is
        # unsure, or a condition the agent declared that means its rule
        # cannot be trusted here (ambiguity, conflict, a previous attempt
        # that failed, a condition that could not be judged). A condition
        # that merely describes pressure -- contention, a deadline near -- is
        # noted on the decision, and the rule stands.
        # Every request made while answering this question -- by the rule, a
        # brain it is wrapped in, or a model -- belongs to this decision and
        # is logged with its id. Without the bracket a request is attributed
        # to nothing: an expert decides between messages rather than inside
        # a sub-agent call, so there is no other scope for it to inherit, and
        # "what did SORTING ask its model about P-0042" would have to be
        # guessed from agent and tick -- which is not a key, because two
        # parcels can be graded in one tick.
        def bracket():
            try:
                from ..observability import context as _context
                return _context.inside(decision_id, correlation_id, self.agent_id)
            except Exception:                              # tracing is optional
                return _nothing()

        if self.rule_coverage == "authoritative":
            # A condition the rule covers is noted, not acted on -- and must
            # not hide one after it that the rule does not cover.
            fired = self.triggers.fired(kind, question.facts)
            noticed = next((t for t in fired if t.rule_sufficient is not True),
                           fired[0] if fired else None)
        else:
            noticed = self.triggers.check(kind, question.facts)
        rules = self.rules()
        rule_answer: Optional[Answer] = None
        rule_error = ""                  # why the rule could not answer, if it raised
        if rules is not None and rules.knows(kind):
            try:
                with bracket():
                    rule_answer = rules.answer(question)
            except Exception as error:
                # A rule that cannot run is a rule that is insufficient; the
                # decision still has to be taken, the careful way.
                rule_error = f"rule failed: {type(error).__name__}: {error}"
                noticed = noticed or Trigger(REASONS.UNKNOWN,
                                             f"rule failed: {type(error).__name__}")
        # Whether the rule's own answer settles the case the condition
        # describes (`rule_covers`): judged on the answer, which a condition,
        # reading only the facts, cannot see. It decides whether a model is
        # asked, so it applies only to an agent that has one; on the rules
        # path the record keeps the source's labels (`handling` still says
        # `rule_sufficient` for a covered case).
        covered = False
        if noticed is not None and rule_answer is not None and not rule_error:
            try:
                covered = bool(self.rule_covers(kind, rule_answer, question))
            except Exception:
                covered = False
        has_model = self.brain is not rules
        trigger = rule_insufficient(rule_answer, question.options, noticed,
                                    policy=self.consult_policy,
                                    covered=covered and has_model)
        noted = noticed.reason if (noticed is not None and trigger is None) else ""

        # ---- idle facility -------------------------------------------
        # While the floor has not started work (no robot holds an errand
        # yet), a decision whose rule is insufficient does not call the model.
        # See `simulation.activity`. Only a decision that would have gone to a
        # model is affected; the gate exists only in a run with an expert on
        # the model.
        #   - The rule gave an admissible answer (perhaps an unsure one): the
        #     rule answers (`idle_rule`).
        #   - The rule gave nothing usable (no rule, a rule that raised, or an
        #     answer off the options): the model is still not called. The
        #     decision takes the first admissible option, the same default a
        #     `DeterministicBrain` gives a question it has no rule for, marked
        #     with confidence 0 and logged as `idle_no_rule`.
        # Either way the policy gate below validates the answer as usual.
        idle_skipped: Optional[Trigger] = None
        idle_no_rule = False
        activity = getattr(self.world, "activity", None) if self.world is not None else None
        if (trigger is not None and self.brain is not rules
                and activity is not None and activity.idle):
            idle_skipped, trigger = trigger, None
            idle_no_rule = not self._admissible(rule_answer, question.options)
            self.idle_skips += 1
            activity.skip(self.agent_id, kind, decision_id, idle_skipped.reason,
                          idle_skipped.detail, self.tick,
                          no_rule=idle_no_rule, rule_error=rule_error)

        # ---- model busy (live runs) ------------------------------------
        # A live run does not wait for the model (`async_decisions`), so an
        # expert can be asked a second question while its model is still on
        # the first. One CrewAI loop runs per expert at a time; the second
        # question is the rule's, exactly as on the idle floor above:
        # recorded as `busy_rule` (or `busy_no_rule`, the first admissible
        # option), with the trigger that would have called the model. The
        # same subject asked again while its own question is out simply
        # stays pending.
        busy_skipped: Optional[Trigger] = None
        busy_no_rule = False
        later = ((kind, deferral.key) if (deferral is not None and self.async_decisions
                                           and self.brain is not rules
                                           and hasattr(self.brain, "start_consulting"))
                 else None)
        if later is not None and later in self._pending:
            # Already with the model: the subject holds -- it is not decided
            # again, by the rule or the model, until that answer is in, has
            # gone stale or has missed its deadline. The answer will be
            # checked against, and applied to, the newest picture of the floor.
            self._pending[later]["deferral"] = deferral
            return self._pending_answer()
        if trigger is not None and later is not None:
            if not self.brain.free_to_consult(question, trigger):
                busy_skipped, trigger = trigger, None
                busy_no_rule = not self._admissible(rule_answer, question.options)
                self.busy_skips += 1

        # ---- answer ----------------------------------------------------
        status = ""                     # how the model's part ended, if it had one
        latency_ms = None
        if idle_skipped is not None:
            answer = (self._default_answer(question, rule_answer, rule_error,
                                           "facility idle, model not called")
                      if idle_no_rule else rule_answer)
            mode = "deterministic"
            handling = "idle_no_rule" if idle_no_rule else "idle_rule"
        elif busy_skipped is not None:
            answer = (self._default_answer(question, rule_answer, rule_error,
                                           "model busy with an earlier question")
                      if busy_no_rule else rule_answer)
            mode = "deterministic"
            handling = "busy_no_rule" if busy_no_rule else "busy_rule"
        elif trigger is None:
            answer = rule_answer
            mode = "deterministic"
            handling = "rule_sufficient"
        else:
            mode = "llm" if self.brain is not rules else "deterministic"
            handling = ("llm_insufficient" if mode == "llm"
                        else "rule_sufficient" if covered else "rule_no_model")
            # A live run's model decision finishes on a later tick, when the
            # caller has said how (`deferral`): see `_collect_decisions`.
            if mode != "llm":
                later = None
            self.reasoned += 1
            self.trigger_counts[trigger.reason] = \
                self.trigger_counts.get(trigger.reason, 0) + 1
            started = time.perf_counter()
            with bracket():
                if later is not None:
                    answer = self.brain.start_consulting(question, trigger)
                elif mode == "llm" and hasattr(self.brain, "answer_consulting"):
                    answer = self.brain.answer_consulting(question, trigger)
                elif mode == "llm":
                    answer = self.brain.answer(question)
                elif rule_error:
                    # No model in this run and the rule raised: asking it
                    # again would raise again and stop the tick.
                    answer = self._default_answer(question, rule_answer, rule_error,
                                                  "no model for this agent")
                else:
                    answer = self.brain.answer(question)
            if later is not None and not isinstance(answer, Answer):
                # The model has it; the tick, and every robot, carry on.
                self._model_busy()
                self._pending[later] = {
                    **self._decision_context(kind, question, rules, rule_error, mode,
                                             trigger, noted, handling, rule_answer,
                                             idle_skipped, correlation_id,
                                             decision_id, facts, busy_skipped),
                    "handle": answer, "deferral": deferral, "started": started,
                    "bracket": bracket}
                return self._pending_answer()
            if mode == "llm":
                latency_ms = round((time.perf_counter() - started) * 1000.0, 1)

        if deferral is not None and (kind, deferral.key) in self._pending:
            # Decided now, without waiting for the model (the clock was
            # stopped and a tick taken by hand): the answer still out for the
            # same subject has been overtaken by this one.
            self._pending[(kind, deferral.key)]["superseded"] = True
        return self._conclude(
            self._decision_context(kind, question, rules, rule_error, mode, trigger,
                                   noted, handling, rule_answer, idle_skipped,
                                   correlation_id, decision_id, facts, busy_skipped),
            answer, status, latency_ms)

    def _decision_context(self, kind, question, rules, rule_error, mode, trigger,
                          noted, handling, rule_answer, idle_skipped, correlation_id,
                          decision_id, facts, busy_skipped=None) -> Dict[str, Any]:
        """What `_conclude` needs to validate and record a decision, now or later."""
        return {"kind": kind, "question": question, "rules": rules,
                "rule_error": rule_error, "mode": mode, "trigger": trigger,
                "noted": noted, "handling": handling, "rule_answer": rule_answer,
                "idle_skipped": idle_skipped, "correlation_id": correlation_id,
                "decision_id": decision_id, "facts": facts, "request_tick": self.tick,
                "busy_skipped": busy_skipped}

    def _note_outcome(self, consultation_id: Optional[str], answer: Answer, verdict: Any,
                      status: str, stale: str) -> None:
        """Say on the consultation what became of the model's answer (the live page shows it)."""
        note = getattr(self.brain, "note_outcome", None)
        if not consultation_id or not callable(note):
            return
        reason = str(answer.reason or "")
        if stale:
            used, detail = "stale", stale
        elif not verdict.ok:
            used, detail = "refused", verdict.violation
        elif status == LLM_TIMEOUT:
            used, detail = "deadline", "the model had not answered in time"
        elif status == LLM_FAILED:
            used = "rule"
            detail = (reason.rsplit("[fallback:", 1)[-1].rstrip("] ").strip()
                      if "[fallback:" in reason else "no usable reply")
        else:
            used, detail = "applied", ""
        try:
            note(consultation_id, used, detail, answer.choice, self.tick)
        except Exception:
            pass                                 # the page's account never stops a decision

    @staticmethod
    def _pending_answer() -> Answer:
        """The placeholder a caller gets while the model decides (`is_pending`)."""
        return Answer(PENDING_LLM_DECISION, "waiting for the model",
                      source=LLM_PENDING, confidence=0.0)

    def _conclude(self, c: Dict[str, Any], answer: Answer, status: str = "",
                  latency_ms: Optional[float] = None, stale: str = "") -> Answer:
        """
        Validate an answer at the gate and record the decision.

        The same for an answer reached inside `decide` and for one that came
        back from the model ticks later (`_collect_decisions`), which is then
        checked against the floor as it is now. `stale` records an answer
        that is not applied at all: the subject it was about has moved on.
        """
        kind, question, rules = c["kind"], c["question"], c["rules"]
        rule_error, mode, trigger = c["rule_error"], c["mode"], c["trigger"]
        noted, handling, rule_answer = c["noted"], c["handling"], c["rule_answer"]
        idle_skipped, correlation_id = c["idle_skipped"], c["correlation_id"]
        decision_id, facts, request_tick = c["decision_id"], c["facts"], c["request_tick"]

        # ---- validate --------------------------------------------------
        if stale:
            from ..policy.gate import Verdict
            verdict = Verdict(False, "stale", stale)
        else:
            verdict = self._validate(kind, answer, question)
        if not verdict.ok and not stale:
            self.gate_refusals += 1
            # The decision still has to be taken. The rule takes it, and the
            # answer says plainly that it is a second attempt -- a refused
            # proposal silently replaced by a lawful one is how a run comes to
            # look healthier than it was.
            replacement = None
            if rules is not None and rules.knows(kind) and not rule_error:
                try:
                    replacement = rules.answer(question)
                except Exception as error:      # a refusal must not become a crash
                    rule_error = f"rule failed: {type(error).__name__}: {error}"
            if replacement is not None:
                answer = Answer(replacement.choice,
                                f"{verdict.violation}; {replacement.reason}",
                                source=f"{answer.source}:rule-after-refusal",
                                confidence=replacement.confidence)
            else:
                answer = Answer(None, verdict.violation,
                                source=f"{answer.source}:refused", confidence=0.0)

        # ---- record ----------------------------------------------------
        # One word for where the answer came from, so a run can say how much
        # of it the rules carried: `deterministic`; `llm/<trigger>` when the
        # model answered; `fallback` when the model was asked and the rule
        # answered after all (an empty or off-list reply, or a refusal at the
        # gate). Counted per agent and summarised by the ecosystem.
        source_text = str(answer.source or "")
        if mode != "llm":
            path = "deterministic"
        elif "fallback" in source_text or source_text.endswith("rule-after-refusal") \
                or source_text.endswith(":refused"):
            path = "fallback"
        else:
            path = f"llm/{trigger.reason if trigger else 'unknown'}"
        self.path_counts[path] = self.path_counts.get(path, 0) + 1
        if not status:
            status = self._status_of(mode, source_text, verdict.ok)
        record = {"tick": self.tick, "kind": kind, "decision_id": decision_id,
                  "choice": answer.choice, "source": answer.source, "path": path,
                  "mode": mode, "reason": answer.reason,
                  "trigger": trigger.reason if trigger else "",
                  "trigger_detail": trigger.detail if trigger else "",
                  # Pressure the agent noticed while its rule still answered:
                  # observed, counted, and not a reason to call the model.
                  "noted": noted,
                  "validation": "ok" if verdict.ok else verdict.stage,
                  "status": status,
                  # How the decision was handled: `rule_sufficient` (the rule
                  # answered and the model was not needed), `llm_insufficient`
                  # (the rule was insufficient and the model was asked),
                  # `idle_rule` / `idle_no_rule` (insufficient while the
                  # facility was idle: the rule, or the default option, and no
                  # model), `rule_no_model` (insufficient, but this agent has
                  # no model: the rule answered).
                  "handling": handling}
        if rule_error:
            record["rule_error"] = rule_error
        timing = {}
        if mode == "llm":
            # Only a model decision has a latency worth writing down, and a
            # deterministic one must not carry a wall-clock figure: the same
            # seed has to give the same log.
            timing = {"request_tick": request_tick, "response_tick": self.tick,
                      "latency_ms": latency_ms,
                      # What the rule had answered, beside the reason it was
                      # not enough, so every model call can be audited
                      # against the rule it was asked to improve on.
                      "rule_choice": (str(rule_answer.choice) if rule_answer is not None
                                      else None)}
            record.update(timing)
        # A consultation the brain held for this decision, if it held one:
        # its id, the peer it asked, and how many turns it took. Read only
        # when the brain was asked, so a rule decision never carries the
        # previous model decision's consultation.
        consultation = (getattr(self.brain, "last_consultation", None)
                        if mode == "llm" else None)
        consult = {}
        if isinstance(consultation, dict):
            consult = {"consultation_id": consultation.get("consultation_id"),
                       "peer": consultation.get("peer"),
                       "turns": consultation.get("turns")}
            record.update(consult)
            self._note_outcome(consult["consultation_id"], answer, verdict, status, stale)
        # A model call not made because the facility was idle: the trigger
        # that would have made it, beside the rule's answer. Absent on every
        # other decision, so a run without the gate logs exactly as before.
        skipped = {}
        if idle_skipped is not None:
            skipped = {"llm_skipped": "idle",
                       "skipped_trigger": idle_skipped.reason,
                       "skipped_trigger_detail": idle_skipped.detail}
            record.update(skipped)
        elif c.get("busy_skipped") is not None:
            busy = c["busy_skipped"]
            skipped = {"llm_skipped": "busy", "skipped_trigger": busy.reason,
                       "skipped_trigger_detail": busy.detail}
            record.update(skipped)
        self.handling_counts[handling] = self.handling_counts.get(handling, 0) + 1
        if noted:
            self.noted_counts[noted] = self.noted_counts.get(noted, 0) + 1
        self.decisions.append(record)
        if len(self.decisions) > 200:
            del self.decisions[:100]
        if self.world is not None:
            self.world.logger.emit(
                EventCategory.AGENT, "decision", tick=self.tick,
                actor=self.agent_id, correlation_id=correlation_id,
                decision=kind, choice=str(answer.choice),
                source=answer.source, reason=answer.reason, facts=dict(facts),
                call_id=decision_id, mode=mode, path=path,
                trigger=record["trigger"], trigger_detail=record["trigger_detail"],
                noted=record["noted"],
                validation=record["validation"], violation=verdict.violation,
                status=status, handling=handling,
                **({"rule_error": rule_error} if rule_error else {}),
                **timing, **consult, **skipped,
            )
        return answer

    # ------------------------------------------------ how a decision ended
    @staticmethod
    def _status_of(mode: str, source_text: str, gate_ok: bool) -> str:
        """The telemetry word for a decision that has reached its answer."""
        if mode != "llm":
            return DETERMINISTIC
        if "fallback" in source_text.split(":")[0]:
            return LLM_FAILED          # the model gave nothing usable
        if not gate_ok:
            return LLM_REJECTED        # the model answered and the gate said no
        return LLM_ACCEPTED

    @staticmethod
    def _admissible(answer: Optional[Answer], options: Sequence[Any]) -> bool:
        """Whether an answer can stand at all: a choice, and one of the options if any."""
        if answer is None or answer.choice is None:
            return False
        return not options or answer.choice in tuple(options)

    @staticmethod
    def _default_answer(question: Question, rule_answer: Optional[Answer],
                        rule_error: str, why: str) -> Answer:
        """
        The answer when the rule gave nothing usable and the model is not asked.

        The first admissible option, as `DeterministicBrain` answers a question
        it has no rule for, with confidence 0 and the reason spelled out. A
        free-form question (no options) has no default and gets no answer.
        """
        cause = rule_error or ("no rule answer" if rule_answer is None
                               else f"rule answer {rule_answer.choice!r} is not admissible")
        first = question.options[0] if question.options else None
        return Answer(first, f"{cause}; {why}; first admissible option",
                      source="default", confidence=0.0)

    @staticmethod
    def _fallback(rule_answer: Optional[Answer], why: str) -> Answer:
        """The rule's answer, labelled as the model's stand-in."""
        if rule_answer is None:
            return Answer(None, f"no rule to fall back on [fallback: {why}]",
                          source="fallback", confidence=0.0)
        return Answer(rule_answer.choice, f"{rule_answer.reason} [fallback: {why}]",
                      source="fallback", confidence=rule_answer.confidence)

    def _validate(self, kind: str, answer: Answer, question: Question):
        """
        Put the proposed action through the gate, whoever proposed it.

        The gate belongs to the world rather than to the agent: an agent that
        owned the thing permitting its own actions would be permitting them.
        A run assembled without one is still valid -- a bare agent in a unit
        test, for instance -- and then nothing is refused.
        """
        gate = getattr(self.world, "gate", None) if self.world is not None else None
        if gate is None:
            from ..policy.gate import PERMITTED
            return PERMITTED
        return gate.check(Proposal(
            kind=kind, agent_id=self.agent_id, choice=answer.choice,
            options=question.options, facts=question.facts,
            reason=answer.reason, source=answer.source))

    # ------------------------------------------------------------------ tick
    @property
    def tick(self) -> int:
        return self.world.tick if self.world is not None else 0

    def step(self) -> None:
        """Read the inbox, then do whatever this agent does unprompted."""
        if self.bus is None:
            return
        self._collect_decisions()
        for message in self.bus.inbox(self.agent_id):
            self.received += 1
            if message.message_type.name.startswith("CONSULT_"):
                # The record of a consultation that has already finished,
                # synchronously, inside the decision that asked for it.
                continue
            self.handle(message)
        self.tick_work()

    def _collect_decisions(self) -> None:
        """
        Finish the model decisions that have come back, and give up on late ones.

        Each answer is first checked against the floor as it is now by the
        caller's own `still_valid` (the parcel still at the door, the robot
        still blocked and on the same errand, the task still unassigned...),
        then validated at the policy gate exactly as an answer reached inside
        `decide` is -- schema, policy, and the state of the floor now -- and
        only then applied. An answer whose subject has moved on is recorded as
        stale and not applied, and the caller's `reevaluate` asks again from
        where things stand, rules first. A decision the model has not
        answered within `llm_deadline_ticks` is closed with the rule's answer
        (`llm_timeout`), which goes through the same checks.
        """
        if not self._pending:
            return
        self._model_busy()
        for key, c in list(self._pending.items()):
            overdue = (self.llm_deadline_ticks > 0
                       and self.tick - c["request_tick"] >= self.llm_deadline_ticks)
            with c["bracket"]():
                answer = self.brain.finish_consulting(
                    c["handle"], give_up=self.llm_deadline_ticks if overdue else 0)
            if answer is None:
                continue                       # still with the model
            del self._pending[key]
            latency_ms = round((time.perf_counter() - c["started"]) * 1000.0, 1)
            status = LLM_TIMEOUT if overdue else ""
            deferral: Deferral = c["deferral"]
            if c.get("superseded"):
                self._conclude(c, answer, LLM_REJECTED, latency_ms,
                               stale="overtaken by a later decision on the same subject")
                continue
            try:
                why = deferral.still_valid(answer) or ""
            except Exception as error:            # a check that cannot run is a no
                why = f"could not check the answer: {type(error).__name__}: {error}"
            if why:
                self._conclude(c, answer, LLM_REJECTED, latency_ms, stale=why)
                deferral.reevaluate(why)
                continue
            final = self._conclude(c, answer, status, latency_ms)
            if final is not answer:
                # The gate refused the model's answer and the rule's took its
                # place; that one is checked against the floor as well.
                try:
                    why = deferral.still_valid(final) or ""
                except Exception as error:
                    why = f"could not check the answer: {type(error).__name__}: {error}"
                if why:
                    deferral.reevaluate(why)
                    continue
            deferral.apply(final)

    def _model_busy(self) -> None:
        """
        Mark on the world that a model decision is out on this tick.

        Read by timers that must not mistake a model's thinking time for a
        lost message (`SchedulingAgent._model_allowance`): they allow for it
        only while some expert is, or a moment ago was, waiting on its model.
        """
        if self.world is not None:
            try:
                self.world.model_busy_tick = self.tick
            except Exception:
                pass

    def pending_decisions(self) -> List[Dict[str, Any]]:
        """The model decisions this agent is waiting on: kind, subject, since when."""
        return [{"kind": kind, "key": str(subject), "decision_id": c["decision_id"],
                 "since_tick": c["request_tick"]}
                for (kind, subject), c in self._pending.items()]

    def handle(self, message: Message) -> None:
        """React to one message. Most agents spend most of their life here."""

    def tick_work(self) -> None:
        """Standing duties that nobody has to ask for."""

    # ----------------------------------------------------------------- state
    def state(self) -> Dict[str, Any]:
        """Agent-specific state, for the API. Subclasses extend this."""
        return {}

    def as_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "role": self.role,
            "kind": self.kind.value,
            "parent_id": self.parent_id,
            "brain": getattr(self.brain, "name", "brain"),
            "messages_received": self.received,
            "messages_sent": self.sent,
            "recent_decisions": [dict(d) for d in self.decisions[-10:]],
            "state": self.state(),
        }


class SubAgent(BaseAgent):
    """
    A specialist owned by exactly one expert.

    The only structural difference from an expert is the one the spec insists
    on: a sub-agent answers to its parent and to nobody else. It is enforced by
    the bus rather than by this class, but `to_parent` exists so that the
    ordinary case reads as what it is.
    """

    kind = AgentKind.SUBAGENT

    def __init__(self, agent_id: str, role: str, parent_id: str,
                 brain: Optional[Brain] = None) -> None:
        if not parent_id:
            raise ValueError(f"{agent_id}: a sub-agent must have a parent")
        super().__init__(agent_id, role, parent_id=parent_id, brain=brain)

    def to_parent(self, message_type: MessageType,
                  content: Optional[Dict[str, Any]] = None,
                  correlation_id: str = "", text: str = "",
                  in_reply_to: Optional[str] = None) -> Optional[Message]:
        return self.send(self.parent_id, message_type, content or {},
                         correlation_id, text, in_reply_to)

    def handle(self, message: Message) -> None:
        """
        Do the work and answer the parent.

        Sub-agents in this system are request/response by design: they hold no
        long-lived state, which makes them the easiest components in the
        ecosystem to swap for an LLM and the easiest to test.
        """
        if message.message_type is not MessageType.SUBTASK_REQUEST:
            return
        result = self.perform(message)
        if result is None:
            return
        self.to_parent(MessageType.SUBTASK_RESULT, result,
                       correlation_id=message.correlation_id,
                       in_reply_to=message.message_id,
                       text=result.pop("_text", ""))

    def perform(self, message: Message) -> Optional[Dict[str, Any]]:
        """The one thing this sub-agent knows how to do."""
        raise NotImplementedError
