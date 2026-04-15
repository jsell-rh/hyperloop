#!/usr/bin/env bash
# check_result_file.sh — verify .worker-result.json exists and is valid before submission
# Exit 0 = pass, Exit 1 = fail

set -euo pipefail

RESULT_FILE="$(git rev-parse --show-toplevel)/.worker-result.json"

if [[ ! -f "$RESULT_FILE" ]]; then
  echo "FAIL: .worker-result.json not found at repo root ($RESULT_FILE)" >&2
  exit 1
fi

# Validate JSON structure
if ! python3 -c "
import json, sys

with open('$RESULT_FILE') as f:
    data = json.load(f)

required = {'verdict', 'findings', 'detail'}
missing = required - set(data.keys())
if missing:
    print(f'FAIL: missing fields in .worker-result.json: {missing}', file=sys.stderr)
    sys.exit(1)

if data['verdict'] not in ('pass', 'fail'):
    print(f'FAIL: verdict must be \"pass\" or \"fail\", got: {data[\"verdict\"]}', file=sys.stderr)
    sys.exit(1)

if not isinstance(data['findings'], int):
    print(f'FAIL: findings must be an integer, got: {type(data[\"findings\"]).__name__}', file=sys.stderr)
    sys.exit(1)

if not isinstance(data['detail'], str) or not data['detail'].strip():
    print('FAIL: detail must be a non-empty string', file=sys.stderr)
    sys.exit(1)

print(f'PASS: .worker-result.json is valid (verdict={data[\"verdict\"]}, findings={data[\"findings\"]})')
"; then
  exit 1
fi
