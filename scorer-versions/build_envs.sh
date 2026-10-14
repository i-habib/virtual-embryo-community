#!/usr/bin/env bash
# Build one uv virtualenv per veckit variant, outside the repository.
#
#   bash build_envs.sh                 # all variants
#   bash build_envs.sh pypi-0.1.2 pr6  # only the named ones
#
# Wheels come from scorer-variants/pypi/*.whl; git variants are installed from the detached worktrees under
# scorer-variants/worktrees/ (created with `git worktree add --detach`). Each env records its resolved
# package versions in envs/<name>/freeze.txt. Written for the macOS default bash (3.2): no associative arrays.
set -euo pipefail

S="${SCORER_VARIANTS:?set SCORER_VARIANTS to a scratch directory}"
ENVS="$S/envs"
UV="${UV:-/opt/homebrew/bin/uv}"
PY_VERSION=3.11
ORDER="pypi-0.1.0 pypi-0.1.1 pypi-0.1.2 git-46d41e6 git-main-cc3859a pr2 pr4 pr5 pr6 pr8 pr11"

source_for() {
  case "$1" in
    pypi-0.1.0) echo "$S/pypi/veckit-0.1.0-py3-none-any.whl" ;;
    pypi-0.1.1) echo "$S/pypi/veckit-0.1.1-py3-none-any.whl" ;;
    pypi-0.1.2) echo "$S/pypi/veckit-0.1.2-py3-none-any.whl" ;;
    git-46d41e6|git-main-cc3859a|pr2|pr4|pr5|pr6|pr8|pr11)
      case "$1" in
        git-46d41e6) echo "$S/worktrees/git-46d41e6" ;;
        git-main-cc3859a) echo "$S/worktrees/git-main-cc3859a" ;;
        *) echo "$S/worktrees/$1" ;;
      esac ;;
    *) return 1 ;;
  esac
}

if [ "$#" -gt 0 ]; then WANT="$*"; else WANT="$ORDER"; fi

mkdir -p "$ENVS"
for name in $WANT; do
  src="$(source_for "$name")" || { echo "unknown variant: $name" >&2; exit 1; }
  env_dir="$ENVS/$name"
  echo "== $name  <- $src"
  "$UV" venv --clear --quiet --python "$PY_VERSION" "$env_dir"
  "$UV" pip install --quiet --python "$env_dir/bin/python" "$src"
  "$UV" pip freeze --python "$env_dir/bin/python" > "$env_dir/freeze.txt"
  "$env_dir/bin/python" -c "import importlib.util as u; print('  veckit at', u.find_spec('veckit').origin)"
done
