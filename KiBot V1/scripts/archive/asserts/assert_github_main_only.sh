#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

git fetch origin --prune >/dev/null 2>&1 || true

remote_branches="$(git branch -r | sed 's/^[[:space:]]*//' | grep -v -- '->' || true)"
unexpected="$(printf '%s\n' "$remote_branches" | grep -vE '^origin/main$' | grep -vE '^$' || true)"

if [ -n "$unexpected" ]; then
  echo "FAIL:REMOTE_BRANCHES_NOT_MAIN_ONLY"
  printf '%s\n' "$unexpected"
  exit 1
fi

head_branch="$(git remote show origin | awk -F': ' '/HEAD branch/ {print $2}' | tr -d '\r')"
if [ "$head_branch" != "main" ]; then
  echo "FAIL:ORIGIN_HEAD_NOT_MAIN"
  echo "$head_branch"
  exit 1
fi

echo "OK:GITHUB_MAIN_ONLY"
