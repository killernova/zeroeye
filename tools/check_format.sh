#!/usr/bin/env bash
#
# check_format.sh  -  EditorConfig Compliance Validator
#
# Verifies that tracked files in the repo comply with .editorconfig settings.
# Uses editorconfig-checker (ec) if available, otherwise falls back to basic
# heuristic checks for indent style, trailing whitespace, and final newlines.
#
# Usage:
#   ./tools/check_format.sh            # check all tracked files
#   ./tools/check_format.sh --staged   # check only staged files
#   ./tools/check_format.sh --verbose  # verbose output
#
# Exit codes:
#   0  -  all files comply
#   1  -  violations found
#   2  -  script error (missing repo root, etc.)

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EDITORCONFIG="$REPO_ROOT/.editorconfig"
VERBOSE=0
STAGED_ONLY=0
VIOLATIONS=0
CHECKED=0

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

for arg in "$@"; do
    case "$arg" in
        --verbose|-v)  VERBOSE=1 ;;
        --staged)      STAGED_ONLY=1 ;;
        --help|-h)
            echo "Usage: $0 [--verbose] [--staged]"
            echo ""
            echo "Options:"
            echo "  --verbose, -v   Show detailed per-file results"
            echo "  --staged        Check only git-staged files"
            echo "  --help, -h      Show this help"
            exit 0
            ;;
        *)
            echo "Unknown argument: $arg"
            exit 2
            ;;
    esac
done

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

log_info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_fail()  { echo -e "${RED}[FAIL]${NC}  $*"; }

report_violation() {
    local file="$1"
    local line="$2"
    local message="$3"
    VIOLATIONS=$((VIOLATIONS + 1))
    if [ "$VERBOSE" -eq 1 ] || [ "$VIOLATIONS" -le 20 ]; then
        log_fail "$file:$line: $message"
    fi
}

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------

if [ ! -f "$EDITORCONFIG" ]; then
    log_fail ".editorconfig not found at $EDITORCONFIG"
    exit 2
fi

cd "$REPO_ROOT"

# ---------------------------------------------------------------------------
# Try editorconfig-checker first
# ---------------------------------------------------------------------------

EC_BIN=""
if command -v editorconfig-checker &>/dev/null; then
    EC_BIN="editorconfig-checker"
elif command -v ec &>/dev/null; then
    EC_BIN="ec"
fi

if [ -n "$EC_BIN" ]; then
    log_info "Using editorconfig-checker ($EC_BIN)"
    if [ "$STAGED_ONLY" -eq 1 ]; then
        STAGED_LIST="$(git diff --cached --name-only --diff-filter=ACM)"
        if [ -z "$STAGED_LIST" ]; then
            log_info "No staged files to check."
            exit 0
        fi
        echo "$STAGED_LIST" | xargs "$EC_BIN" && {
            log_ok "All staged files comply with .editorconfig"
            exit 0
        } || {
            log_fail "editorconfig-checker found violations"
            exit 1
        }
    else
        if "$EC_BIN"; then
            log_ok "All files comply with .editorconfig"
            exit 0
        else
            log_fail "editorconfig-checker found violations"
            exit 1
        fi
    fi
fi

# ---------------------------------------------------------------------------
# Fallback: basic heuristic checks
# ---------------------------------------------------------------------------

log_info "editorconfig-checker not found; using built-in heuristic checks"
log_info "Install editorconfig-checker for full validation: https://github.com/editorconfig-checker/editorconfig-checker"

# ---------------------------------------------------------------------------
# Define expected indent per file extension
# ---------------------------------------------------------------------------

get_indent_style() {
    local file="$1"
    local basename
    basename="$(basename "$file")"
    local ext="${basename##*.}"

    case "$basename" in
        Makefile|*.mk)      echo "tab" ; return ;;
        Dockerfile*)        echo "space:4" ; return ;;
        .gitignore)         echo "space:4" ; return ;;
    esac

    case "$ext" in
        rs)             echo "space:4" ;;
        go)             echo "tab" ;;
        ts|tsx|js|jsx|mjs|cjs) echo "space:2" ;;
        py)             echo "space:4" ;;
        c|h|cpp|hpp|cc) echo "space:4" ;;
        java)           echo "space:4" ;;
        rb)             echo "space:2" ;;
        pl)             echo "space:4" ;;
        sh)             echo "space:4" ;;
        css)            echo "space:4" ;;
        sql)            echo "space:4" ;;
        html)           echo "space:2" ;;
        yml|yaml)       echo "space:2" ;;
        json)           echo "space:2" ;;
        toml)           echo "space:2" ;;
        lua)            echo "space:2" ;;
        md)             echo "space:2" ;;
        *)              echo "unknown" ;;
    esac
}

# ---------------------------------------------------------------------------
# Check each file
# ---------------------------------------------------------------------------

SKIP_EXTS="png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|eot|pdf|zip|tar|gz|bz2|xz|lock|sum|bin|exe|so|dylib|a|o|pyc|class|jar|war"

check_file() {
    local file="$1"

    # Skip if file doesn't exist (deleted)
    [ -f "$file" ] || return 0

    # Skip binary/non-text files by extension
    local local_ext="${file##*.}"
    if echo "$local_ext" | grep -qiE "^($SKIP_EXTS)$" 2>/dev/null; then
        return 0
    fi

    # Skip lockfiles
    case "$file" in
        *package-lock.json|*Cargo.lock|*go.sum|*Gemfile.lock|*poetry.lock)
            return 0
            ;;
    esac

    # Skip encrypted/binary diagnostic artifacts
    case "$file" in
        diagnostic/*.logd|diagnostic/*.logd-part*)
            return 0
            ;;
    esac

    # Skip tools/encryptly binaries
    case "$file" in
        tools/encryptly/*)
            return 0
            ;;
    esac

    local style
    style="$(get_indent_style "$file")"
    [ "$style" = "unknown" ] && return 0

    CHECKED=$((CHECKED + 1))

    # --- Check 1: trailing whitespace ---
    # Skip Markdown (trailing spaces can be intentional line breaks)
    local file_ext="${file##*.}"
    if [ "$file_ext" != "md" ]; then
        local ws_line
        ws_line="$(grep -nP '[ \t]+$' "$file" 2>/dev/null | head -1 || true)"
        if [ -n "$ws_line" ]; then
            local ws_lineno="${ws_line%%:*}"
            report_violation "$file" "$ws_lineno" "trailing whitespace"
        fi
    fi

    # --- Check 2: final newline ---
    if [ -s "$file" ]; then
        # Check if file ends without a newline
        if [ "$(tail -c 1 "$file" | wc -l)" -eq 0 ]; then
            local last_line
            last_line="$(wc -l < "$file" | tr -d ' ')"
            last_line=$((last_line + 1))
            report_violation "$file" "$last_line" "missing final newline"
        fi
    fi

    # --- Check 3: indent style ---
    if [ "$style" = "tab" ]; then
        # Check for lines that start with 4+ spaces (should be tabs)
        local bad_line
        bad_line="$(grep -nP '^ {4,}' "$file" 2>/dev/null | head -1 || true)"
        if [ -n "$bad_line" ]; then
            local bad_lineno="${bad_line%%:*}"
            report_violation "$file" "$bad_lineno" "expected tabs, found spaces"
        fi
    elif echo "$style" | grep -q "^space:"; then
        local expected="${style#space:}"
        # Check for lines that start with tabs (should be spaces)
        local bad_line
        bad_line="$(grep -nP '^\t' "$file" 2>/dev/null | head -1 || true)"
        if [ -n "$bad_line" ]; then
            local bad_lineno="${bad_line%%:*}"
            report_violation "$file" "$bad_lineno" "expected $expected spaces, found tab"
        fi
    fi
}

# Build file list into a temp file to avoid subshell variable scoping issues
FILE_LIST="$(mktemp)"
trap 'rm -f "$FILE_LIST"' EXIT

if [ "$STAGED_ONLY" -eq 1 ]; then
    git diff --cached --name-only --diff-filter=ACM > "$FILE_LIST"
else
    git ls-files > "$FILE_LIST"
fi

# Check each file
while IFS= read -r file; do
    [ -n "$file" ] && check_file "$file"
done < "$FILE_LIST"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
if [ "$VIOLATIONS" -eq 0 ]; then
    log_ok "All $CHECKED checked files comply with .editorconfig"
    exit 0
else
    if [ "$VIOLATIONS" -gt 20 ]; then
        log_fail "Showing first 20 of $VIOLATIONS violations (use --verbose for all)"
    fi
    log_fail "$VIOLATIONS violation(s) found in $CHECKED files"
    log_info "Run 'editorconfig-checker' for full validation: https://github.com/editorconfig-checker/editorconfig-checker"
    exit 1
fi
