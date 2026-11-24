# Librarium

Librarium is a local library catalogue and EPUB review application. You can browse a collection, read a book, and inspect its metadata, contents and validation results. The demo uses fictional books.

[Run Librarium locally](docs/development.md#application-experiment) or read the [product brief](PRODUCT.md). This public source snapshot starts a new Git history. Historical issue and release references document earlier development. Public CI rebuilds an audited historical runtime with synthetic data to test upgrades and recovery. The private release pipeline verifies the original released image by digest.

## Project guides

| Need | Read |
|---|---|
| Product ambition and user journeys | [Product brief](PRODUCT.md) |
| Goals, priorities and delivery work | [Roadmap guide](docs/roadmap.md) |
| Beta, stable releases and production promotion | [Release strategy](docs/releases.md) |
| Visual and interaction direction | [Design brief](DESIGN.md) |
| Where files belong | [Structure and ownership](docs/structure.md) |
| Portable agent environment contract | [Environment contract](docs/agent-environment.md) |
| Local setup and verification | [Development guide](docs/development.md) |
| VS Code, live diffs, and optional coding | [Editor guide](docs/vscode.md) |
| Accepted Docker release requirements | [Packaging contract](docs/packaging.md) |
| Approved decisions | [Decision log](docs/decisions.md) |
| What exists and what comes next | [Current status](docs/status.md) |
| Architecture proposal and evaluation | [Architecture assessment brief](docs/architecture.md) |
| Task-appropriate skills | [Skill map](docs/skills.md) |
| Concise shared memory and graph/log maintenance | [Context hygiene](docs/context-hygiene.md) |
| Existing codebase references and snapshot boundaries | [Upstream sources](upstream/README.md) |
| Earlier code preserved for evaluation | [Experiments](experiments/README.md) |
| Three generated product concepts | [Inspiration images](images/inspiration/README.md) |

Codex onboarding lives in [.codex/README.md](.codex/README.md). Claude onboarding
lives in [.claude/README.md](.claude/README.md). Product facts belong in shared
documents so either assistant can continue from the same evidence.
