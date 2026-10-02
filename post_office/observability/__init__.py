"""
Decision-scope context for tracing, and the RCT explainer, log and recorder.

Four modules are carried into this prototype: `context` (decision scope for
tracing), `rct_explain` (what drove a DK-RMM reading, read from the event log,
with expert consultations in place of the source's discussions), `rct_log`
(every saved RCT, read back from disk) and `run_record` (a run's DK-RMM record
and its RCT files, written as the run goes).
"""
