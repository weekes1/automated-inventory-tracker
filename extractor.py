"""Vision provider adapter and structured response parsing.

Scaffold only; retain raw observations separately from resolved values.
When implemented, send the snapshotted prompt/inputs from runs.start_run and
record the full response plus returned model/request/usage via runs.finish_run.
"""
