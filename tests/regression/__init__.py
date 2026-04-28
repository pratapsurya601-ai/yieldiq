# Regression-test suite. Each module here corresponds to a single
# production bug fixed in the 2026-04-28 launch-window sweep. Tests
# are self-contained — no DB, no API, no network. They exist to make
# the *exact* class of bug we shipped impossible to reintroduce
# silently. Add a new module here every time we land a one-off fix
# without a guarding test.
