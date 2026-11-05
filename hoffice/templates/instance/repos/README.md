# Repositories

Keep one card per git repository at `<org>--<name>.md`, using the hoffice engine's `templates/repo-card.md`. Record origin URLs, not local checkout paths; those belong in `AGENTS.local.md`.

Lookup reads these rows (projects may be comma separated):

```markdown
| Origin | `https://code.example.org/example/service.git` |
| Projects | `projects/service/`, `projects/platform/` |
```

The engine's `scripts/hoffice-project-for-repo.sh [checkout]` matches the origin's org/repo across clone protocols and hosts. It prints each instance root and project name, separated by a tab.

| Repository | Projects | Card |
|---|---|---|
