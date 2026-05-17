# ADR 0028 — ECS deploy contract: Terraform owns structure, CI owns image

## Status

Accepted (2026-05-17). Fixes a class of bug that bit us in production
on 2026-05-16 (commits `f7a260d` → `7557ea1`); the cleanup commit is
the one that lands this ADR.

## Context

We have two writers that both want to register revisions of the same
ECS task-definition family (`lume-prod-backend`,
`lume-prod-frontend`):

1. **CI** (`.github/workflows/backend-deploy.yml`,
   `frontend-deploy.yml`) — on every push to `main`, builds a
   commit-SHA-tagged image, registers a new task-definition revision
   via `describe-task-definition → swap image →
   register-task-definition`, and updates the ECS service to use the
   new revision. Standard rolling-deploy pattern.

2. **Terraform** (`infra/compute.tf`) — when env vars, secrets, or
   IAM bindings change in the `container_definitions` block,
   Terraform computes a new task-def revision and registers it.

The two writers compete. Without coordination, they produce
overlapping task-def revisions and the wrong one can end up running.

### The 2026-05-16 incident

While shipping the Meta Instagram integration (ADR 0027) we
discovered three separate deploy regressions, all rooted in the
same underlying problem:

- Terraform stamps `"${repo}:${var.backend_image_tag}"` (default
  `"latest"`) into every new revision it creates.
- The `:latest` tag is **immutable** on this ECR repo (security
  posture — we don't want anyone overwriting an audit-anchored tag).
- During incident response I tagged `:latest` to the very first
  Docker image manually so the Terraform-generated revisions
  wouldn't fail to pull. That tag is now permanently pinned to
  commit `f7a260d` and can never be moved.
- Whenever Terraform regenerates the task def (e.g. because we
  added Meta secrets), it creates a new revision with `:latest`,
  which still points at the very old image. If anyone manually
  promotes that revision (e.g. for testing a fresh env-var change
  before CI runs) the service rolls back to pre-Meta code.

The service has `lifecycle.ignore_changes = [task_definition,
desired_count]` so Terraform doesn't promote its own revisions
automatically — that's why the bug only triggered when operators
manually pointed the service at a Terraform-generated revision.
The operator workflow ("apply Terraform, manually promote the new
revision to verify the secret change is wired through") is
reasonable and shouldn't blow up.

## Decision

### 1. Terraform reads the live image off the running service

`infra/compute.tf` now declares two pairs of data sources:

```hcl
data "aws_ecs_service" "backend_live" {
  cluster_arn  = aws_ecs_cluster.main.arn
  service_name = "${local.name_prefix}-backend"
}

data "aws_ecs_task_definition" "backend_live" {
  task_definition = data.aws_ecs_service.backend_live.task_definition
}
```

The `service_name` is a literal string, not a reference to the
`aws_ecs_service.backend` resource — that path would create a
dependency cycle (task_def → image → live_service → task_def).
The literal name is deterministic (`{name_prefix}-backend`) and
matches what the service resource sets one block down.

The current image gets extracted in a `local`:

```hcl
locals {
  backend_live_image = try(
    jsondecode(data.aws_ecs_task_definition.backend_live.container_definitions)[0].image,
    "${aws_ecr_repository.backend.repository_url}:${var.backend_image_tag}",
  )
}
```

And used in the task-def `container_definitions` block:

```hcl
container_definitions = jsonencode([{
  name  = "backend"
  image = local.backend_live_image
  ...
}])
```

Result: whenever Terraform creates a new revision, the image field
matches whatever CI most recently deployed. If an operator
manually promotes a Terraform-generated revision, ECS pulls the
right code.

The `try()` fallback to `var.backend_image_tag` handles the cold
bootstrap (very first apply, no service exists yet). After the
first CI deploy, every subsequent Terraform apply uses the data
source path.

### 2. Sole ownership remains as before

This change preserves the existing ownership split:

| Writer | Owns | Mechanism |
|---|---|---|
| **CI** | Image tag + service promotion | `register-task-definition` + `update-service` |
| **Terraform** | Container env, secrets, IAM, networking, ALB wiring | Standard resource lifecycle |

The service still has `lifecycle.ignore_changes = [task_definition,
desired_count]`, so Terraform's revisions never auto-promote.

### 3. ECR tag immutability stays IMMUTABLE

We considered loosening `image_tag_mutability` to `MUTABLE` so
`:latest` could be moved. Rejected: SHA-tagged immutable images are
a SOC 2 / audit anchor. The data-source pattern above removes the
need for a moving `:latest` entirely.

### 4. CI workflow unchanged

The existing `backend-deploy.yml` already does the right thing:
`describe-task-definition --task-definition $FAMILY` returns the
latest revision (which is either a CI- or Terraform-generated
revision; either way the env / secrets are current), swaps the
image, registers a new revision, updates the service.

No CI workflow changes needed; this is purely a Terraform-side fix.

## Consequences

### Good

- Symptom (operator promotes Terraform revision → stale code)
  cannot recur.
- Terraform's plans for env / secret changes are now drift-free —
  the diff doesn't include image churn.
- No CI workflow changes, no new variables to manage, no commits-
  back-to-main from CI. Single-source-of-truth for image stays in
  ECR; single-source-of-truth for env/secrets stays in Terraform.
- The pattern is documented in `compute.tf` next to the locals
  block so a future engineer doesn't have to reverse-engineer it.

### Bad / Deferred

- The `var.backend_image_tag` variable is now functionally vestigial
  (only used during cold-bootstrap). Keeping it for clarity + the
  rare disaster-recovery scenario where the data source can't
  resolve and an operator needs to force a specific image.
- Plan time slightly slower because we now read 4 data sources on
  every plan (negligible — ~100ms).

### Acknowledged

- Cold bootstrap of a NEW environment still uses
  `var.{backend,frontend}_image_tag` (default `"latest"`). The
  first CI deploy after bootstrap immediately overwrites with a SHA.
  If `:latest` doesn't exist in ECR at bootstrap time, the initial
  ECS task placement fails with `CannotPullContainerError`; this is
  expected + harmless (the next CI deploy fixes it).
- Anyone manually rolling back to an old revision should still pin
  to a specific revision number rather than relying on `:latest`.
  This is operator hygiene, not enforceable in Terraform.

## Alternatives considered

### Use `lifecycle.ignore_changes = [container_definitions]` on the task def

Terraform would stop tracking ANY changes to container_definitions
(not just image), which means env / secret changes in code would
silently NOT propagate to new revisions. Loses the Terraform-as-
source-of-truth posture for env/secrets, which is a deliberate
design choice (auditability of configuration in source control).

### Have CI commit a `.auto.tfvars` file back to main after each push

Mechanically works (CI writes new SHA to a tfvars file, commits,
pushes, gets picked up by next Terraform run). But the commit
loop is awkward (need `[skip ci]` or branch isolation) and adds a
write-back path from production CI to source — an extra failure
mode + audit-trail confusion.

### Move env / secrets management out of Terraform into CI

Have CI's render-task-definition step inject env + secrets at
deploy time instead of Terraform. Then Terraform only manages
the service shell, not the task def at all. Major architectural
shift; loses code-review of config changes via Terraform PR; not
worth it for a problem the data source approach solves cleanly.

### Stop using a placeholder image entirely (Terraform doesn't manage task def)

Move `aws_ecs_task_definition.backend` out of Terraform; have CI
register the only revisions that exist. Same downside as the
previous alternative — env/secrets stop being declarative.

## References

- `infra/compute.tf` — the locals block + data sources + comments
  explaining the pattern
- `.github/workflows/backend-deploy.yml` — the CI render-and-deploy
  step (unchanged by this ADR)
- Incident timeline: commits `f7a260d` (2026-05-16 14:00 UTC, first
  encountered) through `7557ea1` (2026-05-16 18:30 UTC, last manual
  rev-promotion workaround)
- HashiCorp Terraform community pattern: "ECS task definitions with
  external image management" (multiple StackOverflow + GitHub
  discussions converge on this exact data-source approach)
