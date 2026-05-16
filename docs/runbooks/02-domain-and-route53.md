# 02 — Domain + Route 53 hosted zone

Goal: the apex domain (e.g. `xn--lumcrm-5ua.com`) is registered, the
Route 53 hosted zone exists, and the registrar's NS records point at
it. Terraform's `dns.tf` reads this zone via data source — without
this step, `terraform apply` fails.

## Prerequisites

- AWS account hardened (runbook 01).
- IAM admin signed in via the AWS CLI:
  ```
  aws sts get-caller-identity
  ```
  Should print your IAM admin ARN.

## Steps

### 1. Register the domain (any registrar)

If you don't already have a domain:

**Option A — Route 53 Domains** (one less moving part).
- Route 53 → Registered domains → Register domain. ~$12-50/yr
  depending on TLD.

**Option B — External registrar** (Namecheap, Squarespace,
GoDaddy). Same end state; one extra step to update NS records.

### 2. Create the hosted zone

```bash
aws route53 create-hosted-zone \
  --name xn--lumcrm-5ua.com \
  --caller-reference "$(date +%s)" \
  --hosted-zone-config Comment="Lume CRM production"
```

Save the zone ID from the output (e.g. `Z0123456789ABCDEFGHIJ`).

### 3. Get the NS records

```bash
ZONE_ID=Z0123456789ABCDEFGHIJ
aws route53 get-hosted-zone --id "$ZONE_ID" \
  --query 'DelegationSet.NameServers' --output text
```

Four nameservers, e.g.:

```
ns-123.awsdns-12.com
ns-456.awsdns-45.net
ns-789.awsdns-78.org
ns-012.awsdns-01.co.uk
```

### 4. Update the registrar

* **Route 53 Domains**: it's already wired — the zone you just
  created is the authoritative one for the domain. Skip to step 5.
* **External registrar**: log into the registrar, find the "DNS" or
  "Nameservers" section, switch from the registrar's default to
  "Custom DNS", paste in the four AWS nameservers. Save.

### 5. Wait for propagation

```bash
dig NS xn--lumcrm-5ua.com +short
```

Should return the four AWS nameservers (in any order). Propagation
is usually <1 hr; can be up to 48 hr in the worst case. Don't move
on until this is right.

### 6. Confirm zone is reachable

```bash
aws route53 list-resource-record-sets \
  --hosted-zone-id "$ZONE_ID" \
  --max-items 5
```

You should see the SOA + NS records. Anything else means a stale
state Terraform can't reason about.

## Done when

- [ ] Domain is registered
- [ ] Route 53 hosted zone exists
- [ ] `dig NS xn--lumcrm-5ua.com` returns the AWS nameservers
- [ ] Zone ID is saved (you'll need it nowhere else explicitly —
      Terraform's data source resolves by name — but it's the kind
      of thing worth filing)

Next: [03-github-oidc-role.md](03-github-oidc-role.md)
