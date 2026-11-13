"""Pipeline orchestration, extraction run identity, and bounded retries.

Scaffold only; no processing stages are implemented yet.
Future extraction calls must use runs.start_run before the request and
runs.finish_run for its outcome. Each retry is a separate run.
"""
