# 04 — SES domain verification

Goal: SES can send email from `noreply@mail.xn--lumcrm-5ua.com` (or whatever
sending subdomain you choose). Domain is DKIM-signed, SPF-passing,
DMARC-monitored. Without these three, mail lands in spam — which for
a HIPAA app means signed-form links never reach the patient.

## Why a subdomain (not the apex)

Sending from `noreply@xn--lumcrm-5ua.com` works, but a poor-reputation
sending event (a customer marks one of your emails as spam) burns
the apex domain's reputation including its non-SES uses (Google
Workspace, marketing site contact form). Putting send traffic on a
subdomain (`mail.xn--lumcrm-5ua.com`) isolates the blast radius.

## Steps

### 1. Verify the sending domain in SES

```bash
aws ses verify-domain-identity \
  --domain mail.xn--lumcrm-5ua.com \
  --region us-east-1
```

(Use whatever region you're standing the rest of prod up in. Must
be HIPAA-eligible for SES — confirm at
https://aws.amazon.com/compliance/services-in-scope/.)

The output gives you a `VerificationToken`. Add it as a TXT record:

```bash
ZONE_ID=$(aws route53 list-hosted-zones-by-name \
  --dns-name xn--lumcrm-5ua.com \
  --query 'HostedZones[0].Id' --output text)

cat > ses-verify.json <<EOF
{
  "Changes": [{
    "Action": "UPSERT",
    "ResourceRecordSet": {
      "Name": "_amazonses.mail.xn--lumcrm-5ua.com",
      "Type": "TXT",
      "TTL": 600,
      "ResourceRecords": [{"Value": "\"VERIFICATION_TOKEN_FROM_ABOVE\""}]
    }
  }]
}
EOF

aws route53 change-resource-record-sets \
  --hosted-zone-id "$ZONE_ID" \
  --change-batch file://ses-verify.json
```

Wait ~5 minutes. Confirm:

```bash
aws ses get-identity-verification-attributes \
  --identities mail.xn--lumcrm-5ua.com
```

Status should be `Success`.

### 2. Enable DKIM

```bash
aws ses verify-domain-dkim \
  --domain mail.xn--lumcrm-5ua.com \
  --region us-east-1
```

Three CNAME tokens. Add each as a Route 53 CNAME record:

```
TOKEN1._domainkey.mail.xn--lumcrm-5ua.com → TOKEN1.dkim.amazonses.com
TOKEN2._domainkey.mail.xn--lumcrm-5ua.com → TOKEN2.dkim.amazonses.com
TOKEN3._domainkey.mail.xn--lumcrm-5ua.com → TOKEN3.dkim.amazonses.com
```

Then:

```bash
aws ses set-identity-dkim-enabled \
  --identity mail.xn--lumcrm-5ua.com \
  --dkim-enabled
```

Confirm via:

```bash
aws ses get-identity-dkim-attributes \
  --identities mail.xn--lumcrm-5ua.com
```

`DkimVerificationStatus` should be `Success`.

### 3. SPF — TXT record on the sending subdomain

Allow Amazon SES servers to send on behalf of this domain. Without
this, recipient mail servers can mark messages as "from someone who
doesn't authorize Amazon".

Route 53 → mail.xn--lumcrm-5ua.com → TXT record:

```
v=spf1 include:amazonses.com -all
```

The `-all` (hard fail) is correct because we ONLY send through SES
on this subdomain.

### 4. DMARC — TXT record at `_dmarc.mail.xn--lumcrm-5ua.com`

Start in `quarantine` mode with rua/ruf reporting. After ~30 days
of clean reports, move to `reject`.

```
v=DMARC1; p=quarantine; rua=mailto:dmarc-reports@mail.xn--lumcrm-5ua.com; ruf=mailto:dmarc-reports@mail.xn--lumcrm-5ua.com; pct=100; aspf=s; adkim=s
```

(You can use a 3rd-party DMARC reporter like Postmark or
DMARCdigests if `dmarc-reports@` isn't a mailbox you want to read
manually.)

### 5. Move out of the SES sandbox

By default SES accounts are sandboxed: can only send to verified
addresses, hard cap of 200 messages/day. Required for production.

In SES console → Account dashboard → "Request production access".
AWS asks:
- Use case: transactional only (appointment reminders, signed-form
  links, password resets)
- Expected volume: realistic — start with 1k/day cap, you can raise it
- Compliance with AWS AUP: yes
- Bounce/complaint handling: SES auto-suspends; we read SNS alerts

Approval is usually 24-48 hr. While waiting, you can dev-test with
verified-email-only mode.

### 6. Verify the FROM address

If `ses_from_address` in `terraform.tfvars` is the literal email
(`noreply@mail.xn--lumcrm-5ua.com`), it's automatically allowed once the
domain is verified. Different specific addresses on the same domain
also work — the IAM policy on the backend task role matches the
`ses:FromAddress` condition.

### 7. SNS notifications for bounces + complaints (Phase 0c.6)

SES supports forwarding bounce / complaint events to an SNS topic.
We don't wire this up automatically — it's a small but real
follow-up. Until then, watch the SES Account dashboard's
"Sending statistics" tab once a week.

## Done when

- [ ] `_amazonses.mail.xn--lumcrm-5ua.com` TXT record exists, SES status `Success`
- [ ] Three DKIM CNAMEs published, DKIM status `Success`
- [ ] SPF TXT record published
- [ ] DMARC TXT record published
- [ ] Production access approved (or sandbox is fine while
      iterating)
- [ ] Test email to a real inbox: SPF=pass, DKIM=pass, DMARC=pass
      (check the headers in Gmail's "Show original")

Next: [05-first-deploy.md](05-first-deploy.md)
