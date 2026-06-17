# CI Pages Doc Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish XCC's agent-control claims as reproducible GitHub automation and align the entry documentation with the current project positioning.

**Architecture:** Add GitHub Actions workflows as public automation gates, keep the static GitHub Pages site in `github-pages/`, and update only the documentation entry points that currently contradict the README/GitHub Pages positioning. Runtime code remains unchanged.

**Tech Stack:** GitHub Actions, Python 3.11, uv, tox, clang/LLVM system packages, static HTML/CSS/JS, Markdown.

---

### Task 1: Add Public Automation Gates

**Files:**
- Create: `.github/workflows/ci.yml`
- Create: `.github/workflows/pages.yml`
- Modify: `README.md`
- Modify: `github-pages/README.md`

- [x] **Step 1: Create CI workflow**

Create `.github/workflows/ci.yml` with a Python 3.11 job that installs clang/LLVM, installs uv, syncs dev dependencies, then runs validation, unittest, lint, and type gates.

- [x] **Step 2: Create Pages deployment workflow**

Create `.github/workflows/pages.yml` with GitHub Pages permissions and deploy the static `github-pages/` directory on pushes to `main` and manual dispatch.

- [x] **Step 3: Surface workflow evidence in docs**

Add CI/Pages badges and GitHub Pages deployment notes so visitors can discover the public gates from README and `github-pages/README.md`.

### Task 2: Align Entry Documentation

**Files:**
- Modify: `pyproject.toml`
- Modify: `docs/index.en.md`
- Modify: `docs/index.zh.md`
- Modify: `docs/compiler-comparison.en.md`
- Modify: `docs/compiler-comparison.zh.md`
- Modify: `docs/roadmap.en.md`
- Modify: `docs/roadmap.zh.md`
- Modify: `docs/xcc-architecture.en.md`
- Modify: `docs/xcc-architecture.zh.md`
- Modify: `CHANGELOG.md`

- [x] **Step 1: Update package metadata**

Change the package description from a narrow LLVM-backend description to the agent-controlled C compiler positioning.

- [x] **Step 2: Update docs entry pages**

Replace outdated "educational + LLVM-C only" positioning with the current Python 3.11+ stdlib C11 compiler and agent-control engineering specimen summary.

- [x] **Step 3: Update comparison and roadmap pages**

Correct XCC comparison rows and roadmap items that still say the default target is always LLVM or that Linux support is only future work.

- [x] **Step 4: Record status**

Add a concise changelog entry for CI/Pages automation and documentation synchronization.

### Task 3: Verify Handoff Gates

**Files:**
- No source edits expected.

- [x] **Step 1: Run validation harness**

Run: `uv run python scripts/validate_compiler.py`

- [x] **Step 2: Run focused validation tests**

Run: `uv run python -m unittest tests.test_validation -v`

- [x] **Step 3: Run lint gate**

Run: `uv run tox -e lint`

- [x] **Step 4: Run type gate**

Run: `uv run tox -e type`
