#!/usr/bin/env bash
#
# A4S+ honesty scan.
#
# Two jobs:
#   1. Fail if unfinished-work markers (TODO / FIXME / XXX / HACK) exist in
#      shipped source.
#   2. Fail if the repository makes a claim it is not entitled to make
#      ("military-grade", "clinically validated", "real sensor data", ...).
#
# The word "mock"/"fake"/"stub" is allowed ONLY inside test files, where it
# describes test doubles, and inside this script. Application code must never
# fabricate data.
#
# Run:  bash scripts/honesty-scan.sh      (or: make honesty-scan)

set -uo pipefail

cd "$(dirname "$0")/.." || exit 2

# Checks 1 and 2 are about shipped code. Checks 3 and 4 also cover prose,
# because a false claim in a document is still a false claim.
CODE=(backend/app backend/ml backend/seeds frontend/src infra scripts)
SOURCES=("${CODE[@]}" docs README.md)
EXCLUDES=(
  --glob '!node_modules/**'
  --glob '!.next/**'
  --glob '!**/__pycache__/**'
  --glob '!**/artifacts/**'
  --glob '!package-lock.json'
)

fail=0

section() { printf '\n\033[1m%s\033[0m\n' "$1"; }
ok() { printf '  \033[32mOK\033[0m  %s\n' "$1"; }
bad() {
  printf '  \033[31mFAIL\033[0m  %s\n' "$1"
  fail=1
}

# --------------------------------------------------------------- 1. markers
section "Unfinished-work markers"
marker_hits=$(rg -n --no-heading -i "${EXCLUDES[@]}" \
  -e '\bTODO\b' -e '\bFIXME\b' -e '\bXXX\b' -e '\bHACK\b' \
  --glob '!scripts/honesty-scan.sh' --glob '!scripts/claim_scan.py' \
  "${CODE[@]}" 2>/dev/null)
if [ -n "$marker_hits" ]; then
  bad "unfinished-work markers found:"
  printf '%s\n' "$marker_hits" | sed 's/^/        /'
else
  ok "no TODO / FIXME / XXX / HACK in shipped source"
fi

# ------------------------------------------------- 2. test doubles in app code
section "Test doubles outside tests"
double_hits=$(rg -n --no-heading -i "${EXCLUDES[@]}" \
  --glob '!**/__tests__/**' --glob '!**/tests/**' --glob '!**/*.test.*' \
  --glob '!**/*.spec.*' --glob '!frontend/vitest.setup.ts' \
  --glob '!scripts/honesty-scan.sh' --glob '!scripts/claim_scan.py' \
  -e '\bmock(ed|s)?\b' -e '\bfake[sd]?\b' -e '\bdummy\b' -e '\blorem\b' \
  "${CODE[@]}" 2>/dev/null |
  grep -viE 'not (a )?(mock|fake)|never (mock|fake)|no (mocks|fakes)|nothing .*(mocked|faked)')
if [ -n "$double_hits" ]; then
  bad "test-double vocabulary in application code:"
  printf '%s\n' "$double_hits" | sed 's/^/        /'
else
  ok "application code contains no mock/fake/dummy data paths"
fi

# ------------------------------------------------------------ 3. false claims
section "Overclaiming language"
#
# The codebase mentions these phrases on purpose, in order to disclaim them
# ("NOT CLINICALLY VALIDATED", 'nothing here should be described as
# "military-grade"'). A mention is therefore only a violation when it is
# *unqualified*, so the checker inspects a small window around each hit for
# negating language, and carries a short allowlist with written reasons.
python3 scripts/claim_scan.py "${SOURCES[@]}" > /tmp/a4s-claims.txt 2>&1
claim_status=$?
if [ "$claim_status" -ne 0 ]; then
  bad "unqualified claims this prototype is not entitled to make:"
  sed 's/^/        /' /tmp/a4s-claims.txt
else
  ok "every mention of military-grade / clinical validation is a disclaimer"
fi

# ------------------------------------------------------- 4. required warnings
section "Required disclaimers"
require() {
  if rg -q -i "${EXCLUDES[@]}" -e "$2" "$1" 2>/dev/null; then
    ok "$1 states: $3"
  else
    bad "$1 is missing: $3"
  fi
}
require README.md 'software (-only )?prototype' '"software prototype"'
require README.md 'simulated' '"simulated data"'
require README.md 'not clinically validated' '"not clinically validated"'
require frontend/src/lib/constants.ts 'SOFTWARE PROTOTYPE' 'prototype banner text'
require frontend/src/lib/constants.ts 'NOT CLINICALLY VALIDATED' 'validation disclaimer'

section "Result"
if [ "$fail" -eq 0 ]; then
  printf '  honesty-scan: \033[32mPASS\033[0m\n'
else
  printf '  honesty-scan: \033[31mFAIL\033[0m\n'
fi
exit "$fail"