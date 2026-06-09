"""backend.jobs — scheduled background entrypoints.

Distinct from ``backend.scripts`` (one-off + manual operator tooling) and
``backend.workers`` (long-running daemon processes). Each file here is a
``python -m backend.jobs.<name>`` cron entrypoint, intended to be wired
to GH Actions ``schedule:`` triggers and run-to-completion in a single
invocation.
"""
