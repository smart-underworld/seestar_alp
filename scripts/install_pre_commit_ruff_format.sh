#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "${repo_root}" ]]; then
  echo "Error: not inside a git repository."
  exit 1
fi

hook_path="${repo_root}/.git/hooks/pre-commit"

cat >"${hook_path}" <<'HOOK'
#!/usr/bin/env bash
set -euo pipefail

if ! command -v ruff >/dev/null 2>&1; then
  echo "pre-commit: ruff not found; skipping format."
  exit 0
fi

mapfile -t files < <(git diff --cached --name-only --diff-filter=ACM | grep -E '\.py$' || true)
if [[ ${#files[@]} -eq 0 ]]; then
  exit 0
fi

echo "pre-commit: running ruff format on staged Python files..."
ruff format "${files[@]}"

echo "pre-commit: running ruff check --fix on staged Python files..."
ruff check --fix "${files[@]}" || {
  echo "pre-commit: ruff check found unfixable issues; please fix them before committing."
  exit 1
}

git add -- "${files[@]}"
HOOK

chmod +x "${hook_path}"
echo "Installed pre-commit hook at ${hook_path}"
