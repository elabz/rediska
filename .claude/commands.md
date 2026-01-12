# Rediska Claude Code Commands

## Task Management

### Mark a Task Complete
After completing a task from the Task Breakdown, mark it complete:
```bash
./scripts/tasks/complete_task.sh "task description"
```

Example:
```bash
./scripts/tasks/complete_task.sh "Create monorepo folder structure"
```

### List Tasks
View tasks with various filters:
```bash
# Show all incomplete tasks
./scripts/tasks/list_tasks.sh

# Show completed tasks
./scripts/tasks/list_tasks.sh completed

# Show task statistics
./scripts/tasks/list_tasks.sh stats

# Show tasks for a specific phase
./scripts/tasks/list_tasks.sh phase 0

# Show tasks for a specific epic
./scripts/tasks/list_tasks.sh epic 1.2
```

## Workflow

When working on Rediska, follow this workflow:

1. **Check current tasks**: `./scripts/tasks/list_tasks.sh stats`
2. **Pick a task from the current sprint/phase**
3. **Implement the task** - ensure acceptance criteria (AC) are met
4. **Run tests** to verify functionality
5. **Mark task complete**: `./scripts/tasks/complete_task.sh "task name"`
6. **Commit changes** with meaningful message

## Sprint Reference

Current sprints are defined in `prd/Rediska_Sprint_Plan_v0.1.md`:

- **Sprint 0**: Bootstrap (repo scaffolding, docker compose, TLS)
- **Sprint 1**: Auth + DB + Inbox (mock data)
- **Sprint 2**: Provider OAuth + backfill + delta sync
- **Sprint 3**: Search + Leads + ES + embeddings
- **Sprint 4**: Agents + Attachments + Manual Send + Backups
