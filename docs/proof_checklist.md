# Proof Checklist

This checklist defines what counts as evidence before saying **done**, **fixed**, or **checked**.

## Rules

1. **Code claims require evidence.**
   Any answer about what the code does must include either command output or an exact file line number.

2. **A test proves a fix only with a negative control.**
   The test must be **red on the broken code** and **green on the fixed code**. A green test alone is not proof that the
   fix matters.

## Before saying "done"

Run the complete proof pack:

```bash
git status -sb
git log -3 --oneline
git rev-parse HEAD
git rev-parse origin/main
pytest -q
```

Verify:

* `git rev-parse HEAD` and `git rev-parse origin/main` match.
* `pytest -q` finishes successfully.
* The number of `passed` tests equals the number of `def test_` definitions.
* Test names are unique.
* No unintended uncommitted changes remain.

## CI claims

CI is proven by the **GitHub Actions run**, not by the badge.

Verify:

* Actions → the relevant workflow run → **Summary**.
* The run's commit SHA matches `git rev-parse HEAD`.
* The **Run tests** step is successful.
* The **Run tests** output shows the expected number of passed tests.

A badge alone is not evidence of a specific commit or test run.
