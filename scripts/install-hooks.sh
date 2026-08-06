#!/usr/bin/env bash
# Install the repo's git hooks. Run once after cloning.
#   bash scripts/install-hooks.sh
#
# Hooks live in .git/hooks/, which git does not track, so a clone starts with
# none. That is the whole reason the real script sits in scripts/ and this
# copies it into place.

set -euo pipefail

root=$(git rev-parse --show-toplevel)
install -m 755 "$root/scripts/pre-commit" "$root/.git/hooks/pre-commit"
echo "Installed pre-commit hook. Test it with: bash scripts/test-pre-commit.sh"
