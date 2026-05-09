# 11 — Rollback a bad deploy

Goal: revert the running service to a previously-shipped image tag,
fast. ECS keeps the previous task definition revision around; the
"rollback" is just pointing the service at it.

## Symptoms that warrant rollback

- Healthchecks failing on every new task → ALB cycling tasks.
- 5xx rate alarm fires.
- Migration was applied but the new code can't read the old (or
  vice versa).

If the service is fully down (no healthy tasks), rolling back is
the single most important next move — investigate AFTER the bleed
stops.

## Backend rollback

### Option A — workflow_dispatch with a known-good SHA

The deploy workflow accepts an `image_tag` input. Find the last
known-good commit SHA (12-char prefix):

```bash
git log --oneline main | head -10
```

GitHub UI: Actions → "Backend deploy" → Run workflow → branch:
`main`, image_tag: `<known-good-sha>`. Re-runs the deploy with that
tag. Skips the build step if the image already exists in ECR.

### Option B — ECS revision pointer

Even faster, no GitHub round-trip:

```bash
# List the last 5 task definition revisions
aws ecs list-task-definitions \
  --family-prefix lume-prod-backend \
  --status ACTIVE \
  --sort DESC \
  --max-items 5

# Pick one (they're sortable by revision number)
PREVIOUS_TASK_DEF=arn:aws:ecs:us-east-1:123:task-definition/lume-prod-backend:42

aws ecs update-service \
  --cluster lume-prod-cluster \
  --service lume-prod-backend \
  --task-definition "$PREVIOUS_TASK_DEF" \
  --force-new-deployment

aws ecs wait services-stable \
  --cluster lume-prod-cluster \
  --services lume-prod-backend
```

## Frontend rollback

Same shape. The frontend deploy workflow has the same `image_tag`
input; `Option B` works on `lume-prod-frontend` family.

## Post-rollback checklist

- [ ] `/healthz` returns 200
- [ ] Smoke-test the most-trafficked routes (login, calendar list,
      one client detail page)
- [ ] CloudWatch alarms cleared
- [ ] Open a postmortem doc — what went wrong, how it slipped past
      the test workflow, what guard would catch it next time

## What if a migration broke the rollback

The deploy workflow runs migrations BEFORE swapping the service, so
a "deploy that broke things" usually means migrations succeeded but
the new code has a bug. Old code can probably read the new schema
(the migration was forward-compatible).

If the migration was destructive (dropped a column the old code
reads), rollback alone isn't enough — you also need to restore the
schema. PITR via runbook 12.
