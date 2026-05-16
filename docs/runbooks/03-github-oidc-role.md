# 03 — GitHub Actions OIDC role

Goal: GitHub Actions workflows can deploy to AWS without long-lived
access keys. Done via OIDC: GitHub presents a signed JWT to AWS STS,
AWS validates it against the trust policy on a role, the role's
permissions become the workflow's permissions for the run.

## Why OIDC (not access keys)

Access keys live in `secrets.AWS_ACCESS_KEY_ID` etc. They:

- Don't auto-rotate (you have to remember).
- Are bearer tokens — anyone who reads the secret can use them.
- Show up in CloudTrail as the IAM user, not "GitHub Actions" — bad
  forensics.

OIDC eliminates all three: each workflow run gets a fresh
short-lived credential, the role's trust policy restricts
**which** workflow can use it, and CloudTrail records the assume-
role event with the GitHub repo + commit + branch.

## Steps

### 1. Add GitHub as an OIDC identity provider

```bash
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1
```

(The thumbprint is GitHub's published value. AWS rotates this
automatically as long as the URL matches; you don't need to update
it again.)

### 2. Create the deploy role

`trust-policy.json`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::ACCOUNT_ID:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
        },
        "StringLike": {
          "token.actions.githubusercontent.com:sub": [
            "repo:YOUR_GH_ORG/lume-crm:ref:refs/heads/main",
            "repo:YOUR_GH_ORG/lume-crm:pull_request"
          ]
        }
      }
    }
  ]
}
```

Replace `ACCOUNT_ID` and `YOUR_GH_ORG`. The two `sub` patterns:

- `refs/heads/main` — only `push` events on `main` can assume the
  role for the apply step.
- `pull_request` — PR runs (plan) get the role too. If you want to
  block plan-on-PR for forks, add a stricter condition (the OIDC
  token includes `actor`, `head_ref`, etc.).

```bash
aws iam create-role \
  --role-name lume-crm-github-deploy \
  --assume-role-policy-document file://trust-policy.json
```

### 3. Attach policies

For the first cut, attach `AdministratorAccess`. The Terraform plan
and apply touch enough services that scoping deeper is its own
project:

```bash
aws iam attach-role-policy \
  --role-name lume-crm-github-deploy \
  --policy-arn arn:aws:iam::aws:policy/AdministratorAccess
```

When you have time (Phase 0c.6 polish), tighten this to a custom
policy that allows only what `terraform plan/apply` + the deploy
workflows actually need. AWS publishes
`PowerUserAccess` + a custom IAM policy as a starting point.

### 4. Capture the role ARN

```bash
aws iam get-role --role-name lume-crm-github-deploy \
  --query 'Role.Arn' --output text
```

### 5. Set the GitHub repo secrets

In the repo: Settings → Secrets and variables → Actions → New
repository secret.

| Secret name             | Value                                                      |
| ----------------------- | ---------------------------------------------------------- |
| `AWS_DEPLOY_ROLE_ARN`   | The ARN from step 4                                        |
| `NEXT_PUBLIC_API_BASE`  | `https://api.xn--lumcrm-5ua.com`                                  |
| `TF_VAR_domain_name`    | `xn--lumcrm-5ua.com`                                              |
| `TF_VAR_ses_from_address` | `noreply@mail.xn--lumcrm-5ua.com`                               |
| `TF_VAR_alarm_email`    | Email that gets paged on CloudWatch alarms                 |
| `PRIVATE_SUBNETS_JSON`  | JSON list of private subnet IDs (filled in after first apply) |
| `BACKEND_SG_JSON`       | JSON list with the backend SG ID (filled in after first apply) |

The last two are filled in AFTER the first Terraform apply — they
come from the apply's outputs. Until then, the backend deploy
workflow's migration step will fail; that's fine, the first deploy
runs migrations manually anyway.

### 6. Configure the `production` GitHub environment

Settings → Environments → New environment → name `production`.

- Required reviewers: yourself (or whoever signs off on prod
  changes).
- Deployment branches: `main` only.

The infra workflow's `apply` job specifies
`environment: production` — that gates the apply behind the
manual approval.

## Done when

- [ ] OIDC provider exists in IAM
- [ ] Role `lume-crm-github-deploy` exists with the right trust
      policy
- [ ] All repo secrets above are set
- [ ] `production` environment is configured with required
      reviewers

Next: [04-ses-domain-verification.md](04-ses-domain-verification.md)
