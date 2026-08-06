#!/usr/bin/env bash
# Prove the pre-commit hook blocks secrets and does not cry wolf on ordinary
# code. A secret filter nobody tested is worse than none, because it is
# believed. Every case below runs a real `git commit` in a throwaway repo and
# checks the exit status.
#
#   bash scripts/test-pre-commit.sh

set -uo pipefail

HOOK="$(git rev-parse --show-toplevel)/scripts/pre-commit"
pass=0
fail=0

sandbox=$(mktemp -d)
trap 'rm -rf "$sandbox"' EXIT
git -C "$sandbox" init -q
git -C "$sandbox" config user.email t@t.t
git -C "$sandbox" config user.name t
install -m 755 "$HOOK" "$sandbox/.git/hooks/pre-commit"
printf '.env\n' > "$sandbox/.gitignore"
git -C "$sandbox" add .gitignore
git -C "$sandbox" -c core.hooksPath=/dev/null commit -qm base 2>/dev/null

# check <expectation> <name> <filename> <contents...>
check() {
    local expect="$1" name="$2" file="$3"; shift 3
    printf '%s\n' "$@" > "$sandbox/$file"
    git -C "$sandbox" add -f "$file" 2>/dev/null

    if git -C "$sandbox" commit -qm "test" >/dev/null 2>&1; then
        result="allowed"
    else
        result="blocked"
    fi

    if [ "$result" = "$expect" ]; then
        echo "  ok       $name ($result)"
        pass=$((pass + 1))
    else
        echo "  FAILED   $name: expected $expect, got $result"
        fail=$((fail + 1))
    fi

    git -C "$sandbox" reset -q --hard HEAD >/dev/null 2>&1
    rm -f "$sandbox/$file"
    git -C "$sandbox" reset -q HEAD >/dev/null 2>&1
}

echo "Secrets that must be blocked:"
check blocked ".env by force-add"        .env         "GROQ_API_KEY=gsk_abcdefghij0123456789abcdefghij"
check blocked "Groq key in source"       leak.py      "KEY = 'gsk_EXAMPLEONLYnotarealkey0123456789abcd'"
check blocked "OpenAI-style key"         leak2.py     "key='sk-proj-abcdefghijklmnopqrstuvwxyz012345'"
check blocked "Google AIza key"          leak3.js     "const k = 'AIzaSyD-abcdefghijklmnopqrstuvwxyz0123';"
check blocked "Google AQ. key"           leak4.py     "GOOGLE='AQ.ExampleOnlyNotARealKey000000000000000000'"
check blocked "GitHub PAT"               leak5.md     "token ghp_abcdefghijklmnopqrstuvwxyz0123456789"
check blocked "assignment with a value"  conf.py      "DEEPGRAM_API_KEY = \"0000000000EXAMPLEONLY0000000000000000000\""
check blocked "secret in a notebook"     nb.ipynb     "  \"source\": \"api_key='gsk_abcdefghij0123456789abcdefghijkl'\""
check blocked "private key file"         server.pem   "-----BEGIN PRIVATE KEY-----"

echo
echo "Ordinary content that must NOT be blocked:"
check allowed "plain source"             ok.py        "def add(a, b):" "    return a + b"
check allowed "empty key template"       tmpl.example "GROQ_API_KEY=" "DEEPGRAM_API_KEY="
check allowed "a git SHA"                notes.md     "Fixed in 9451e5f0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
check allowed "the word api_key in prose" doc.md      "Set your api_key in the .env file before running."
check allowed "env var read, not a value" src.py      "key = os.getenv('GROQ_API_KEY')"

echo
echo "$pass passed, $fail failed."
[ "$fail" -eq 0 ] || exit 1
