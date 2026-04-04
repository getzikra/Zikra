# Contributing to Zikra

Thank you for your interest in contributing.

## Local Development

1. Clone the repo
2. Install dependencies: see README for stack-specific instructions
3. Copy `.env.example` to `.env` and fill in your values
4. Start the stack: follow the Quick Start in the README

## Running Tests

Run the test suite before submitting a PR:
```bash
pytest tests/
```

## Pull Request Process

1. Fork the repo and create a branch from `main`
2. Make your changes — keep PRs focused on a single issue
3. Ensure tests pass
4. Submit your PR with a clear description of what changed and why
5. A maintainer will review within a few days

## Reporting Bugs

Open an issue using the Bug Report template. Include logs and your environment details.

## Good First Issues

Look for issues labelled `good first issue` to get started. These are well-scoped and have enough context to work on without deep project knowledge.

## Code Style

- Python: follow PEP 8, use type hints where practical
- Commit messages: imperative present tense (`fix: resolve timeout on reconnect`)
