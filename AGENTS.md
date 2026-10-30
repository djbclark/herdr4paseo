# Notes for AI sessions in herdr4paseo

A Textual TUI (log view plus prompt box) for one Paseo agent, built only on the `paseo` CLI.
Public repo: github.com/djbclark/herdr4paseo.

1. `src/herdr4paseo/core.py` is pure (argv builders, `paseo ls --json` parsing, log-line styling); `app.py` is the Textual UI.
2. Tests use `tests/fake_paseo.py` through `PASEO_BIN`; never point tests at a real daemon or send to a live agent.
3. Run tests with `uv run --group dev pytest -q` (through `~/ops/site-private/bin/bg`; the CI-first decision is recorded as local).
4. Do not run `paseo --help` or other probing on the live daemon; read https://paseo.sh/docs/cli instead.
5. Output formats of `paseo logs` and `paseo ls --json` were read from a live daemon on 2026-10-28; recheck if Paseo changes them.
