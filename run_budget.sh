#!/usr/bin/env bash
# Usage:
#   ./run_budget.sh setup              one-time: create the venv, install deps
#   ./run_budget.sh import <Person>    import latest SoFi export, then start the live dashboard server
#   ./run_budget.sh build              start the live dashboard server (alias for "serve")
#   ./run_budget.sh apply-edits        apply category changes downloaded from the dashboard, then start the live server
#   ./run_budget.sh serve              start the local dashboard server (auto-opens browser, live refresh + save)
#   ./run_budget.sh serve --reload     same, but auto-restarts when a .py/.html file changes
#                                      (handy during active development; off by default)
#
# Every command above hands off to the live server — a static dashboard.html
# goes stale the moment new data lands, so live refresh + in-page save is
# the default view everywhere now. Run "python build_dashboard.py" directly
# if you specifically want a static, shareable snapshot instead.
#
# Auto-detects the SoFi export from ~/Downloads (matching the filename SoFi
# generates) — no need to rename or move the file first. Pass --file to
# import_sofi.py directly (see below) if you want to point at a specific file.

set -e
cd "$(dirname "$0")"

activate_venv() {
  if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
  elif [ -f ".venv/Scripts/activate" ]; then
    source .venv/Scripts/activate
  else
    echo "No .venv found. Run './run_budget.sh setup' first."
    exit 1
  fi
}

ACTION="$1"
PERSON="$2"

case "$ACTION" in
  setup)
    echo "Creating virtual environment..."
    python3 -m venv .venv
    activate_venv
    pip install -r requirements.txt
    echo "Setup complete. Next: fill in config.py and service_account.json, then run:"
    echo "  ./run_budget.sh import Elise    (or Matt)"
    ;;

  import)
    if [ -z "$PERSON" ]; then
      echo "Usage: ./run_budget.sh import <Elise|Matt>"
      exit 1
    fi
    activate_venv
    echo "Importing latest SoFi export for $PERSON..."
    python import_sofi.py --person "$PERSON"
    echo ""
    echo "Starting local dashboard server..."
    python server.py
    ;;

  apply-edits)
    activate_venv
    echo "Applying category changes from the dashboard..."
    python apply_category_edits.py
    echo ""
    echo "Starting local dashboard server..."
    python server.py
    ;;

  build|serve)
    activate_venv
    echo "Starting local dashboard server..."
    python server.py "${@:2}"
    ;;

  *)
    echo "Usage:"
    echo "  ./run_budget.sh setup              one-time: create venv + install deps"
    echo "  ./run_budget.sh import <Person>     import latest SoFi export + start the live server"
    echo "  ./run_budget.sh build               start the local dashboard server (alias for serve)"
    echo "  ./run_budget.sh apply-edits         apply dashboard category changes + start the live server"
    echo "  ./run_budget.sh serve               start the local dashboard server (auto-opens browser)"
    echo "  ./run_budget.sh serve --reload      same, but auto-restarts when source files change"
    exit 1
    ;;
esac