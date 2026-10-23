# The operation watch: the fleet's and the work's condition as facts, beside DK-RMM

Added 2026-10-18 (`post_office/observability/operation.py`, the runner's
`operation` beside its `monitor`, the live page's "operation" row and chip).
DK-RMM is unchanged: no indicator, threshold, state, learning rule or record
format is touched (`DKRMM_TREE_SHA` as before), and the watch reads the
monitor only to quote its current state and propagation beside its own.

## 1. Why

On the ON-OFF scenario's seed 11977 two robots stand locked head to head,
holding no errand, from tick 1210 to the horizon (`docs/p7-onoff.md`). DK-RMM
reads RCT at 1341 and again in the first OFF phase, then DEVIATING and STABLE
for most of the rest of the run: its evidence is behavioural, each indicator a
deviation from a rolling 24-window baseline, and a failure that lasts becomes
the baseline (the mean execution latency it measures against is 4.1 at tick
1341 and 513 at tick 3001). Its propagation counts actors, not robots, so two
of five robots is two of about thirteen actors, below the half the RCT rule
asks for; in the first OFF phase, with three kinds of evidence confirmed, the
monitor read UNSTABLE and not RCT for that reason alone (`REPORT_DKRMM_ONOFF`,
section 2.4, and the discussion that followed it). The watch reports what the
fleet is doing in terms that cannot drift, so that the two accounts can be
compared on the same reading.

## 2. What it reads

Every tick, after the ecosystem has stepped, the watch reads every robot's
status, its errand, and, when it is blocked, which robot stands on the next
cell of its route (the same reading `OnOffFaults` makes for the ON-OFF tab).
From these it keeps each robot's consecutive blocked ticks and, for two robots
each blocked by the other, the consecutive ticks of that pair.

Every 20 ticks, on DK-RMM's clock (ticks 1, 21, 41, ...), it assesses. Six
facts, each a kind of evidence present or not; five are about the robots, one
about the work:

| kind | present when |
|---|---|
| blocked | a robot has been BLOCKED for 20 consecutive ticks or more and holds an errand |
| orphaned | the same, holding no errand |
| deadlock | two robots have each been blocked by the other for 20 ticks or more |
| fleet | the robots in such a block, or in unintentional blockage, number 2 or more (on a fleet of five, three or fewer available) |
| unintentional | unintentional blockage: a robot not in a block itself whose way ahead has been held, at some tick of the last 20, by a robot that is in one; counted as having no errand |
| overdue | a parcel is inside the building past the departure the intake gate promised it (`due_by`) and has not been bagged or loaded |

Twenty ticks is one monitor cadence and above anything Normal shows: over
2,000 ticks of Normal on seeds 1 and 11 the longest blocked streak of any
robot is 15 ticks (95th percentile 8 to 9), and ROUTING re-asks about a block
at 1, 3, 6 and 9 ticks, so by 20 its rules have had every look they take. A
robot is "blocked" or "orphaned", never both, so a pair of errand-less robots
is one kind, not two. A streak that reaches 300 ticks is the Phase 7 trap
(`TRAP_TICKS`, the same count the Phase 7 study keeps), and the reading flags
the robot `trapped`; it is not a further kind, since 300 ticks is exactly
fifteen readings, the PERSISTENT state's own definition. So a trapped robot
has been in `blocked` or `orphaned` since its 20th tick and is what makes the
row PERSISTENT.

`unintentional` is the blockage the streak cannot see. At the horizon of seed
11977 R5 stands on (13,13), directly in front of R2, with a route through the
pair and an errand in hand; it has not got past for 600 ticks, but its status
churns as it re-plans (BLOCKED, WAITING when ROUTING answers, IDLE when its
errand is reassigned, MOVING, and a shuffle to the next cell and back), so no
BLOCKED streak of its own reaches 20 ticks and neither the watch's streak
kinds nor the Phase 7 trap counter, which keeps the same streak, ever name it.
The fact is the queue: its way ahead held, within the last reading period, by
a robot in a block. Remembering the holder for 20 ticks is what survives the
churn. A robot in unintentional blockage is counted as having no errand (the
one it holds is not in progress) and so as unavailable, like an orphaned one;
the reading names it and the robot it stands behind. Normal has none by
construction, since no Normal robot is ever in a block. Measured alternatives:
counting the streak by the cell (not moved, next cell held) rather than by the
status is clean on Normal (longest 16 ticks) but changes only 8 of 220
readings on seed 11977 and still misses the shuffle, so the streak stays the
Phase 7 study's.

`overdue` is the fact the robot facts cannot see: the work standing still
while they stand. The threshold is presence, because Normal (seeds 1 and 11,
3,000 ticks each) never has a parcel past its promised departure. A parcel
already bagged or loaded is excluded: the parcel model calls it "committed to
the outbound stream", and it waits for the van timetable, not for the fleet.
Other work facts were measured and rejected: the longest wait of a parcel in
intake reaches 429 ticks on Normal (the parcels seeded on the dock before
tick 1), Normal goes 207 ticks without a van leaving, and the count of
parcels in intake (Normal's peak 15) is crossed by the trapped seed only at
tick 2077, some 850 ticks after the block, at a level that follows the
arrival rate as much as the fleet. The intake count is reported in every
reading for the words, not as a kind.

## 3. The states

The paper's words, applied to facts (`classify`):

- STABLE: no kind present.
- DEVIATING: one or more kinds present.
- UNSTABLE: the paper's equation (3): two kinds persisting from the previous
  assessment, or one kind present with the three preceding assessments
  non-STABLE.
- PERSISTENT: a kind has been present for fifteen consecutive assessments
  (300 ticks, the project's trap definition, `TRAP_TICKS`).

A state holds exactly as long as its condition does. A robot leaves its streak
the tick it moves or is given an errand; there is no baseline and nothing to
habituate. The watch does not beep (the beep stays DK-RMM's) and feeds nothing
back to the monitor or the run.

Each reading carries the robots' facts (with `trapped` at 300 ticks), the
pairs, the fleet available (robots not in a block of 20 ticks or more, over
the fleet), ρ_fleet (the complement), the work (`overdue`, how many of them
URGENT, by zone with "carried" for a parcel on a robot, the earliest miss in
ticks, and `intake`), and DK-RMM's state and propagation for the same
reading. The digest
(`OperationWatch.state()`) is in `/summary` as `operation` on every preset and
in the runner's frame; it is not written into DK-RMM's record.

## 4. What it shows

On the study strip, an "operation" row under DK-RMM's: one segment per reading
on the same clock, the state pill, and the facts in words ("R1 and R2 blocked
by each other since 1,331 (471 and 351 ticks), neither holding an errand ·
fleet 3 of 5 available · DK-RMM reads UNSTABLE, 42% of acting actors in
trouble (fleet: 40%) · off STABLE since 1,221, PERSISTENT since 1,521"). On
the scenario line of every preset, Normal included, an "operation" chip with
the state, the kinds present and the fleet, placed before the DK-RMM chip
(the line's sentence now gives way with an ellipsis instead of running past
the window, which it did before on the long study descriptions). On the ON-OFF
tab's final summary, one sentence with the first tick of each state and the
state at the end. On Normal the chip reads STABLE throughout, which is the
check that the watch invents nothing.

## 5. What it reads on the runs we have

Seed 11977, rules only: DEVIATING first at 1221, UNSTABLE at 1261 (two kinds
persisting), PERSISTENT at 1521 and every reading after it to the horizon,
with orphaned, deadlock and fleet present, and overdue from 1561 (one urgent
parcel on a blocked robot), absent while the only late parcel is bagged at
dispatch (1621 to 1741), then present from 1921 to the horizon as the intake
fills: 3 overdue at 2221, 6 at 2461, 17 at 2981 (15 in intake, 2 in sorting,
9 of them the hospital's, 26 parcels in intake, no robot available, R1 and R2
trapped), 25 at the horizon (4381: 17 in intake, 7 in sorting, 1 on a robot);
unintentional blockage at 98 of 220 readings, R5 at 70 of them that no streak
classifies, from 3805 to the horizon behind R2 with T-0329 in hand, so the
last reading has fleet 2 of 5 available; DK-RMM at the same readings: RCT
at 1341, UNSTABLE and RCT through the first OFF phase, STABLE or DEVIATING
for most readings after 2601. Seed 12057, rules only: UNSTABLE during the ON
phases, PERSISTENT 2141 to 2221 (blocks of 300 ticks with errands in the
second ON phase) and 2981 to 3021 (R5's 330-tick block in temporary storage),
STABLE in between and after; the run's blocks clear and the row says so.
Normal seeds 1 and 11, 2,000 ticks: STABLE at every reading.

## 6. Checks

`tests/test_operation_watch.py` (6 tests): the rule on synthetic sequences,
Normal STABLE throughout on seeds 1 and 11, seed 11977's readings and the
frozen event stream unchanged with the watch attached (ticks 1 to 1700,
`d5c2edc1…`), the `/summary` digest, the page's row and chip. The eleven
presets' event streams, floor frames and summaries are identical before and
after the change (fingerprints of `default` seeds 1 and 11, `c2near-n`,
`c2near-c0` seeds 11 and 12, the five collapse scenarios, `p7-onoff` seed
11977); the only new thing in the frame and in `/summary` is the `operation`
key.
