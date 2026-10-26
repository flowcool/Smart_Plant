# GitHub operations

## Pull requests

Deliver source changes through a PR targeting `V2R1`, including rollback
commits. Wait for the required `yaml-syntax` check before merging. This check
validates syntax only; firmware builds and deployment need their own approval
and operational evidence.

Apply the global PR lifecycle and `.github/pull_request_template.md`.
Pullfrog is the PR reviewer; docs-only PRs require CI only. After an authorized
push and PR creation, run `~/.agents/bin/pr-ship <n> --repo flowcool/Smart_Plant`.

Always pass `--repo flowcool/Smart_Plant` to `gh pr create`.
Without it, `gh` defaults to the upstream fork parent (JGAguado/Smart_Plant)
and opens the PR there instead.

```bash
gh pr create --repo flowcool/Smart_Plant --base V2R1 --title "..." --body "..."
```
