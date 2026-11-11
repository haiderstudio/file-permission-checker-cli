#!/bin/sh
# Run the checker on the bundled examples and show the report.
# The checker exits 1 because the examples contain scripts
# without their executable bit; that is the point of the
# examples, so this script exits 0.
cd "$(dirname "$0")/.." || exit 2
python3 src/file_permission_checker.py examples || true
