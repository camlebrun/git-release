# Contributing to StackRadar

Thanks for your interest. This project follows a **Specification-Driven Development** workflow — read [`docs/sdd.md`](docs/sdd.md) before opening a PR.

---

## Workflow

1. Open an issue describing the problem or feature
2. A spec update (in `docs/specification.md` or `docs/plan.md`) may be needed before any code is written
3. Fork the repo and create a branch from `main` using the naming convention below
4. Write tests first, then implementation
5. Open a PR against `main` — CI must be green

All merges go through pull request. Direct pushes to `main` are not permitted.

---

## Branch naming

| Type | Pattern | Example |
|---|---|---|
| Feature | `feat/<short-description>` | `feat/slack-notifications` |
| Bug fix | `fix/<short-description>` | `fix/cursor-overflow` |
| Chore / infra | `chore/<short-description>` | `chore/upgrade-mistral-sdk` |
| Docs | `docs/<short-description>` | `docs/deployment-guide` |

---

## Code standards

This project enforces formatting and typing on every PR via CI.

```bash
# Format
black src tests

# Lint
ruff check src tests

# Type check
mypy --strict src

# Security scan
bandit -r src functions --severity-level medium

# Tests
pytest --tb=short -q
```

All four must pass before a PR can be merged.

---

## Commit messages

Use the [Conventional Commits](https://www.conventionalcommits.org/) format:

```
<type>(<scope>): <short description>

[optional body]
```

Types: `feat`, `fix`, `chore`, `docs`, `refactor`, `test`, `ci`

Examples:
```
feat(fetcher): add retry on GitHub 429
fix(analyser): handle empty release body
docs(sdd): clarify task lifecycle
```

---

## Adding a tracked repo

To track a new GitHub repository, add `"owner/repo"` to [`repos.json`](repos.json) and open a PR. No code change is needed — the next pipeline run auto-backfills the last 2 major versions.

---

## Project structure

```
src/           Backend Python (Cloud Run Job + Cloud Function)
public/        Static frontend (Cloudflare Pages)
functions/     Cloud Function source (email digest)
tests/         Unit tests
docs/          Architecture and specification documents
scripts/       Local utility scripts (not deployed)
```

---

## Questions

Open an issue with the `question` label.
