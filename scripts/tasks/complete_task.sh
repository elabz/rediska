#!/usr/bin/env bash
# Rediska Task Completion Script
# Usage: ./complete_task.sh "task description" [phase] [epic]
#
# Examples:
#   ./complete_task.sh "Create monorepo folder structure"
#   ./complete_task.sh "Create monorepo folder structure" 0 0.1
#
# This script marks a task as completed in prd/Rediska_Task_Breakdown_v0.1.md

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TASK_FILE="$PROJECT_ROOT/prd/Rediska_Task_Breakdown_v0.1.md"

if [[ ! -f "$TASK_FILE" ]]; then
    echo "Error: Task breakdown file not found at $TASK_FILE"
    exit 1
fi

TASK_DESCRIPTION="${1:-}"
PHASE="${2:-}"
EPIC="${3:-}"

if [[ -z "$TASK_DESCRIPTION" ]]; then
    echo "Usage: $0 \"task description\" [phase] [epic]"
    echo ""
    echo "Available incomplete tasks:"
    grep -n "^\- \[ \]" "$TASK_FILE" | head -20
    exit 1
fi

# Escape special regex characters in the task description
ESCAPED_TASK=$(echo "$TASK_DESCRIPTION" | sed 's/[[\.*^$()+?{|]/\\&/g')

# Find and replace the task
if grep -q "^\- \[ \] $ESCAPED_TASK" "$TASK_FILE"; then
    # Use sed to mark the task as complete
    if [[ "$(uname)" == "Darwin" ]]; then
        sed -i '' "s/^- \[ \] $ESCAPED_TASK/- [x] $ESCAPED_TASK/" "$TASK_FILE"
    else
        sed -i "s/^- \[ \] $ESCAPED_TASK/- [x] $ESCAPED_TASK/" "$TASK_FILE"
    fi
    echo "Task completed: $TASK_DESCRIPTION"

    # Show remaining tasks in the same section
    echo ""
    echo "Remaining incomplete tasks:"
    grep -c "^\- \[ \]" "$TASK_FILE" | xargs -I {} echo "  {} tasks remaining"
else
    echo "Task not found or already completed: $TASK_DESCRIPTION"
    echo ""
    echo "Searching for similar tasks..."
    grep -i "^\- \[ \].*$(echo "$TASK_DESCRIPTION" | cut -c1-20)" "$TASK_FILE" || echo "No similar tasks found."
    exit 1
fi
