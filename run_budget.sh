#!/usr/bin/env bash
# Usage:
#   ./run_budget.sh setup              one-time: create the venv, install deps
#   ./run_budget.sh import <Person>    import latest SoFi export, then rebuild dashboard
#   ./run_budget.sh build              just rebuild the dashboard (no new import)
#   ./run_budget.sh apply-edits        apply category changes downloaded from the dashboard, then rebuild
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
    echo "Rebuilding dashboard..."
    python build_dashboard.py
    ;;

  build)
    activate_venv
    echo "Rebuilding dashboard..."
    python build_dashboard.py
    ;;

  apply-edits)
    activate_venv
    echo "Applying category changes from the dashboard..."
    python apply_category_edits.py
    echo ""
    echo "Rebuilding dashboard..."
    python build_dashboard.py
    ;;

  *)
    echo "Usage:"
    echo "  ./run_budget.sh setup              one-time: create venv + install deps"
    echo "  ./run_budget.sh import <Person>     import latest SoFi export + rebuild dashboard"
    echo "  ./run_budget.sh build               just rebuild the dashboard"
    echo "  ./run_budget.sh apply-edits         apply dashboard category changes + rebuild"
    exit 1
    ;;
esac