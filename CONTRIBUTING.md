# Contributing

- One issue per change; every PR references its issue.
- Work on a branch, open a PR, squash-merge when CI is green.
- Commits and squash-merge bodies carry a full description: what changed,
  why, which tests cover it, known limitations.
- CI must be green: ruff, pytest on Python 3.10-3.13, coverage floor 80%.
- Every bug fix ships with a regression test.
- Never commit personal data or secret values. Use the invented examples in
  docs/SECRETS.md for any fixture.

## Issues: labels, milestones and order

The same scheme is used in every public repo, defined in
[collaboration-docs CONTRIBUTING](https://github.com/reihlinstinct/collaboration-docs/blob/main/CONTRIBUTING.md).
Do not add parallel label schemes.

**Labels** (every open issue has one type, one area and one priority)
- `type: feature | fix | task | docs | security` - the kind of work.
- `area: ...` - the part of the project. In this repo: `area: form`, `area: delivery`, `area: ci`, `area: docs`, `area: security`.
- `priority: high | medium | low` - high is done first.
- `status: blocked | held | in-progress | needs-review` - only when it applies. `status: in-progress` means someone claimed it.
- `needs-triage` - not sorted yet. Remove it when the three labels above are set.
- `good first issue` - small and clear, a good place to start.

The older GitHub default labels (`bug`, `enhancement`, `documentation`, ...) stay for history; new issues use the scheme above.

**Milestones:** `Now` (in progress or due this week), `Next` (planned after Now), `Later` (backlog). High priority goes to Now, medium to Next, low to Later, unless the maintainer decides otherwise.

**Picking an issue:** filter by milestone `Now`, then `Next`. Take high priority first. Skip blocked, held and in-progress items. Comment "taking this" on the issue, then open a PR that references it (`fixes #N` / `refs #N`).
