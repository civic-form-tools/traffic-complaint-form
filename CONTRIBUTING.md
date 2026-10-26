# Contributing

- One issue per change; every PR references its issue.
- Work on a branch, open a PR, squash-merge when CI is green.
- Commits and squash-merge bodies carry a full description: what changed,
  why, which tests cover it, known limitations.
- CI must be green: ruff, pytest on Python 3.10-3.13, coverage floor 80%.
- Every bug fix ships with a regression test.
- Never commit personal data or secret values. Use the invented examples in
  docs/SECRETS.md for any fixture.
