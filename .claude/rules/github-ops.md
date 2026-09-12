# GitHub operations

## Pull requests

Always pass `--repo flowcool/Smart_Plant` to `gh pr create`.
Without it, `gh` defaults to the upstream fork parent (JGAguado/Smart_Plant)
and opens the PR there instead.

```bash
gh pr create --repo flowcool/Smart_Plant --base V2R1 --title "..." --body "..."
```
