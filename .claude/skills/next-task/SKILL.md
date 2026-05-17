---
description: Pick the next backlog item for the current lane, move it to In flight, return the descriptor. Used by the autonomous loop at the start of every tick.
---

# next-task

Read `.claude/state/backlog.md`, find the topmost Active item whose
dependencies are all in Done and whose `lane:` tag matches the running
loop's lane, move it from Active to In flight, update
`.claude/state/in-flight.json`, and return the task descriptor.

## Invocation

Optional arg: `lane=backend` or `lane=ios`. If omitted, infer from the
`AURION_LANE` environment variable. If neither is set, refuse with a
clear error — the loop must always know its lane.

## Procedure

1. **Determine lane.**
   - Use the `lane=` arg if provided.
   - Otherwise read `AURION_LANE` env var.
   - Otherwise: stop and return an error. Do not guess.

2. **Read the backlog.**
   - Open `.claude/state/backlog.md`.
   - Parse the `## Active` section into ordered items.
   - For each item, extract: ID, description, effort, lane, dependencies.

3. **Filter by lane + dependencies.**
   - Drop items whose `lane:` tag doesn't match the running lane.
   - Drop items whose `depends on X` refers to an ID not in the `## Done`
     section.
   - The first remaining item (topmost in file order) is the chosen task.

4. **Handle empty result.**
   - If no eligible item exists for this lane:
     - Append to `.claude/state/alerts.md`:
       ```
       ## YYYY-MM-DD HH:MM INFO next-task
       Lane {lane} has no eligible Active items. Loop paused.
       ```
     - Return null. The loop will sleep via `ScheduleWakeup` and retry on
       the next tick.

5. **Move the item.**
   - Acquire `flock` on `.claude/state/backlog.md` to prevent the other
     lane from racing.
   - Remove the item from `## Active`.
   - Add it to `## In flight` with the format:
     ```
     - [~] {ID} {description} — lane: {lane} — started: YYYY-MM-DD HH:MM
     ```
   - Release the lock.

6. **Update in-flight.json.**
   - Read `.claude/state/in-flight.json`.
   - Set `{lane}.task_id` to the chosen ID.
   - Set `{lane}.branch` to `lane-{lane}/{slug}` where slug is the ID
     lowercased + first 3 words of the description, kebab-cased.
   - Set `{lane}.started_at` to the current ISO-8601 UTC timestamp.
   - Leave `{lane}.pr` as null (set by `/open-pr` later).
   - Write back atomically.

7. **Return descriptor.**
   - Return a structured object the caller can pass to `/plan-task`:
     ```yaml
     id: P0-04
     description: Alembic migrations
     effort_days: 8
     lane: backend
     depends_on: []
     branch: lane-backend/p0-04-alembic-migrations
     started_at: 2026-05-15T09:14:00Z
     ```

## Refusals

- Do not pick a task whose dependencies are unresolved — that's the loop
  trying to skip ahead. If the topmost lane-matching item is dep-blocked
  AND no lower item is unblocked, return null with a clear alert.
- Do not modify the `## Done` or `## Blocked` sections — those are
  written only by `/auto-merge` and `/diagnose-ci` respectively.
- Do not create new sections in `backlog.md` — the schema is fixed.

## Failure modes

| Failure | Response |
|---|---|
| Lane unknown | Refuse, return error. Do not default to one lane. |
| `backlog.md` malformed | Refuse, append ALERT to `alerts.md`, return null. |
| `in-flight.json` already has this lane's `task_id` set | Refuse — previous task didn't finish. Append ALERT, return null. The human resolves. |
| `flock` times out (60 s) | Refuse, append WARN, return null. Other lane is mid-write. |
