# Seestar ALP Code Linting/Formatting Processes

The seestar_alp codebase conforms to the default linting, and formatting rules set forth by [Ruff](https://docs.astral.sh/ruff/)

This is checked on every PR by the process set forth in the [Validate python correctness](../.github/workflows/lint.yaml) action

## How to check your code

Checking the code conforms to linting rules prior to making a PR saves time, and review cycles.

### Check linting correctness

```
ruff check
```
If this exits with a `0` error code, and prints `All checks passed!` - congrats, all checks pass.

#### Auto fixups
Ruff can auto-fix *some* linting errors:
```
ruff check --fix
```

*NOTE* - Always review the changes it makes for correctness. Trust, but verify.


### Check formatting correctness
```
ruff format --check
```
If this exits with a `0` error code, and prints `XX files already formatted` (where XX is a number that may change over time) - congrats, all formatting is correct.

#### Auto formatting
Ruff can auto-format your code to pass its rules:
```
ruff format
```

