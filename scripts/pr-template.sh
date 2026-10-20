#!/usr/bin/env bash
# Print the paths of the current repo's pull request templates, one per line (none if absent).
# Matches pull_request_template.{md,txt} in the root, docs/, or .github/ in any letter case,
# and any file under a PULL_REQUEST_TEMPLATE/ directory in those places.
# usage: pr-template.sh
set -euo pipefail

git ls-files | grep -iE '^(docs/|\.github/)?pull_request_template(\.(md|txt)|/[^/]+)$' || true
