#!/usr/bin/env bash
# Rediska Task Listing Script
# Usage: ./list_tasks.sh [phase|epic|status]
#
# Examples:
#   ./list_tasks.sh                    # Show all incomplete tasks
#   ./list_tasks.sh phase 0            # Show Phase 0 tasks
#   ./list_tasks.sh epic 1.2           # Show Epic 1.2 tasks
#   ./list_tasks.sh completed          # Show completed tasks
#   ./list_tasks.sh stats              # Show statistics

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TASK_FILE="$PROJECT_ROOT/prd/Rediska_Task_Breakdown_v0.1.md"

if [[ ! -f "$TASK_FILE" ]]; then
    echo "Error: Task breakdown file not found at $TASK_FILE"
    exit 1
fi

FILTER_TYPE="${1:-incomplete}"
FILTER_VALUE="${2:-}"

case "$FILTER_TYPE" in
    "phase")
        if [[ -z "$FILTER_VALUE" ]]; then
            echo "Usage: $0 phase <phase_number>"
            exit 1
        fi
        echo "=== Phase $FILTER_VALUE Tasks ==="
        awk "/^## Phase $FILTER_VALUE/,/^## Phase [0-9]/" "$TASK_FILE" | grep "^\- \[" || echo "No tasks found"
        ;;
    "epic")
        if [[ -z "$FILTER_VALUE" ]]; then
            echo "Usage: $0 epic <epic_number>"
            exit 1
        fi
        echo "=== Epic $FILTER_VALUE Tasks ==="
        awk "/^### Epic $FILTER_VALUE/,/^### Epic [0-9]/" "$TASK_FILE" | grep "^\- \[" || echo "No tasks found"
        ;;
    "completed")
        echo "=== Completed Tasks ==="
        grep "^\- \[x\]" "$TASK_FILE" || echo "No completed tasks"
        ;;
    "incomplete")
        echo "=== Incomplete Tasks ==="
        grep "^\- \[ \]" "$TASK_FILE" || echo "All tasks completed!"
        ;;
    "stats")
        echo "=== Task Statistics ==="
        TOTAL=$(grep -c "^\- \[" "$TASK_FILE" || echo "0")
        COMPLETED=$(grep -c "^\- \[x\]" "$TASK_FILE" || echo "0")
        INCOMPLETE=$(grep -c "^\- \[ \]" "$TASK_FILE" || echo "0")

        echo "Total tasks:     $TOTAL"
        echo "Completed:       $COMPLETED"
        echo "Remaining:       $INCOMPLETE"

        if [[ "$TOTAL" -gt 0 ]]; then
            PERCENT=$((COMPLETED * 100 / TOTAL))
            echo "Progress:        $PERCENT%"
        fi

        echo ""
        echo "=== By Phase ==="
        for i in {0..11}; do
            PHASE_TOTAL=$(awk "/^## Phase $i/,/^## Phase $((i+1))/" "$TASK_FILE" | grep -c "^\- \[" 2>/dev/null || echo "0")
            PHASE_DONE=$(awk "/^## Phase $i/,/^## Phase $((i+1))/" "$TASK_FILE" | grep -c "^\- \[x\]" 2>/dev/null || echo "0")
            if [[ "$PHASE_TOTAL" -gt 0 ]]; then
                echo "Phase $i: $PHASE_DONE/$PHASE_TOTAL completed"
            fi
        done
        ;;
    *)
        echo "Usage: $0 [phase|epic|completed|incomplete|stats] [value]"
        exit 1
        ;;
esac
