---
name: commit-discipline
description: Conventional commit rules, phase branching, PR review standards, and authorship constraints.
---

# Commit Discipline & PR Workflow

## 1. Authorship Rule
- Sole Author: `Bhargava Sri Sai <bhargavasrisai7@gmail.com>`.
- **NEVER** add `Co-Authored-By` trailers or mention AI tools in commit messages, PRs, or headers.

## 2. Conventional Commit Standards
All commits must follow the Conventional Commits specification:
- `feat:` New capability or feature slice
- `fix:` Bug fix or correction
- `test:` Adding or updating test suites
- `refactor:` Code reorganization without functional changes
- `docs:` Documentation, README, or skill file updates
- `chore:` Scaffold, tooling, dependencies, and configuration

## 3. Slice Granularity
- Target **8+ commits per phase**.
- Commit after each logically complete slice that passes test validation.
- Never batch an entire phase into one monolithic commit.
- Never squash commits upon PR merge.

## 4. Branching & PR Discipline
1. Create a dedicated branch for each phase off `develop` (`feat/00-foundations`, `feat/01-domain-ledger`, etc.).
2. At the end of each phase:
   - Run full test suite (`pytest`).
   - Create PR using `gh pr create` with comprehensive description (Summary, Test Coverage, Edge Cases, Known Limitations).
   - Perform Red-Team self-review.
   - Merge PR into `develop`.
3. Merge `develop` into `main` only at the two integration checkpoints (Phase 4 and Phase 8).
