# 12 — Restore from backup

Two scenarios:

1. **Database**: a destructive migration or an accidental DELETE.
   Restore via RDS point-in-time recovery (PITR).
2. **Object storage**: someone deleted a PHI document in the media
   bucket. Restore via S3 versioning.

## RDS — point-in-time recovery

PITR creates a NEW RDS instance from the backup at a specific
timestamp. The original instance is untouched. After restore, you
either repoint the application at the new instance OR rename them
to swap.

### 1. Pick the timestamp

The latest restorable time is shown in the AWS console under
RDS → instance → Maintenance & backups. CLI:

```bash
aws rds describe-db-instances \
  --db-instance-identifier lume-prod-postgres \
  --query 'DBInstances[0].LatestRestorableTime'
```

Pick a time JUST BEFORE the bad change. RDS retains backups for 30
days (per `rds_backup_retention_days`).

### 2. Restore to a new instance

```bash
aws rds restore-db-instance-to-point-in-time \
  --source-db-instance-identifier lume-prod-postgres \
  --target-db-instance-identifier lume-prod-postgres-restore \
  --restore-time 2026-05-07T18:30:00Z \
  --db-subnet-group-name lume-prod-db-subnet-group \
  --vpc-security-group-ids <backend-rds-sg-id> \
  --db-parameter-group-name lume-prod-postgres16 \
  --no-publicly-accessible
```

Wait for the new instance to be available (~10-20 min for our size):

```bash
aws rds wait db-instance-available \
  --db-instance-identifier lume-prod-postgres-restore
```

### 3. Verify the data

Connect from a temp Fargate task or an EC2 instance with the right
SG. Run sanity SELECTs against the data you expected to be there.

### 4. Swap

Two options:

**Option A — repoint the app.** Update `DB_HOST` in the ECS task
def to the restored instance's endpoint, force-new-deployment. The
original (broken) instance keeps running, useful for forensic
inspection. Delete it manually when satisfied.

**Option B — rename and swap.** Rename the broken instance to
`lume-prod-postgres-broken`, rename the restored instance to
`lume-prod-postgres`. Endpoints update; ECS tasks reconnect with no
config change because they look up by DNS name.

```bash
aws rds modify-db-instance \
  --db-instance-identifier lume-prod-postgres \
  --new-db-instance-identifier lume-prod-postgres-broken \
  --apply-immediately

aws rds modify-db-instance \
  --db-instance-identifier lume-prod-postgres-restore \
  --new-db-instance-identifier lume-prod-postgres \
  --apply-immediately
```

Force a backend redeploy so connection pools start fresh:

```bash
aws ecs update-service \
  --cluster lume-prod-cluster \
  --service lume-prod-backend \
  --force-new-deployment
```

### 5. Document + close out

- [ ] Postmortem doc — what happened, what timestamp was restored
      to, how much data lag the user-visible state has
- [ ] Delete `lume-prod-postgres-broken` after a week of forensic
      retention — it costs ~$13/mo otherwise
- [ ] Update Terraform state if the swap changed an ARN — usually
      the endpoint stays stable so no diff

## S3 — restore a deleted object

The media bucket has versioning enabled. Deleting an object adds a
"delete marker" rather than removing the data. To restore:

```bash
BUCKET=lume-prod-media-XXXX  # from terraform output

# Find the version IDs of the deleted object
aws s3api list-object-versions \
  --bucket "$BUCKET" \
  --prefix path/to/deleted/file.pdf

# Look for the most recent version with IsLatest=false (the one
# before the delete marker). Note its VersionId.

# Either copy the old version on top of itself (becomes new latest):
aws s3api copy-object \
  --bucket "$BUCKET" \
  --key path/to/deleted/file.pdf \
  --copy-source "$BUCKET/path/to/deleted/file.pdf?versionId=ABCDEF"

# Or delete the delete marker:
aws s3api delete-object \
  --bucket "$BUCKET" \
  --key path/to/deleted/file.pdf \
  --version-id <delete-marker-version-id>
```

Versioning retention is 365 days (lifecycle rule in `storage.tf`).
After that, deleted versions are permanently expired.
