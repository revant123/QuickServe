# QuickServe on AWS (Phases 6 and 16)

This folder holds the Terraform code that builds QuickServe on AWS. (The Kubernetes manifests in `k8s/` are separate: see "Kubernetes (Phase 7)" in the main README.) **Nothing here runs by itself.** CI checks the code with fake ("mock") AWS, so it costs nothing. Only `terraform apply`, run by you, creates anything. Phase 16 adds HTTPS on a free DuckDNS name and GitHub Actions deploying every merge: see [Phase 16](#phase-16-live-with-https-and-automatic-deploys) below.

The main README explains *why* it's built this way (section "AWS and Terraform (Phase 6)"). This file covers what gets built, what it costs, and the exact steps to deploy it and tear it down.

## What gets built

```
infra/
├── bootstrap/        run once per AWS account: budget alert + S3 bucket for Terraform state
├── envs/dev/         the dev environment: network, database, secrets, app server
│   └── tests/        `terraform test` checks (no AWS needed)
└── modules/          reusable pieces, each with its own tests
    ├── budget/       monthly budget with email alerts
    ├── network/      VPC, 2 public + 2 private subnets, no NAT gateway
    ├── database/     RDS PostgreSQL 16, private, encrypted
    ├── app_server/   one t4g.small: Caddy (HTTPS), the API (blue/green), the app, worker, notifier, Redis, Jaeger
    └── github_deploy/  Phase 16: the role GitHub Actions deploys with (OIDC, no keys)
```

| Piece | What it is | Rough cost in Mumbai (ap-south-1), on-demand |
|---|---|---|
| App server | `t4g.small`, 2 ARM vCPUs, 2 GiB RAM | about USD 0.011 per hour (~USD 8 per month if left on) |
| Database | RDS `db.t4g.micro`, single-AZ, 20 GB | about USD 0.021 per hour (~USD 15 per month) |
| Public IPv4 address | needed to reach the server | USD 0.005 per hour (~USD 3.65 per month) |
| Disks | 16 GB (server) + 20 GB (database), gp3 | a few dollars per month; check the AWS Pricing Calculator |
| Parameter Store (secrets), Session Manager, Budgets alerts | | no charge |
| **Total if left running all month** | | **roughly USD 30** |
| **Phase 16 demo, 2 weeks** | | **roughly USD 14** |
| **One 3-hour study session, then `destroy`** | | **roughly USD 0.15** |

Prices change and differ by region: check https://calculator.aws before you apply. The FinOps habit this phase teaches is in that last row: **create, use, destroy**.

## Before you start (one time)

1. **An AWS account.** If you sign in as the root user, turn on MFA (multi-factor authentication) first.
2. **Install the tools** (Mac, in the Terminal app):
   ```bash
   brew install awscli terraform
   aws --version         # needs 2.32 or newer for `aws login`
   terraform version     # 1.11 or newer; CI uses 1.17.2
   ```
3. **Log the AWS CLI in** with your console sign-in. This creates short-lived credentials, with no access keys saved on your Mac:
   ```bash
   aws login --profile quickserve
   # Terraform needs the credentials refreshed during long runs (the database
   # takes ~10 minutes), so point a second profile at the first one:
   aws configure set credential_process "aws configure export-credentials --profile quickserve --format process" --profile quickserve-tf
   aws configure set region ap-south-1 --profile quickserve-tf
   export AWS_PROFILE=quickserve-tf
   aws sts get-caller-identity   # shows your account ID: you're in
   ```
4. **Make the image public** on GitHub: Profile → Packages → quickserve → Package settings → Change visibility → Public. The server downloads it without logging in.

## Step 1: Bootstrap (budget alert + state bucket)

```bash
cd ~/quickserve/infra/bootstrap
cp terraform.tfvars.example terraform.tfvars    # then put your email in it
terraform init
terraform plan          # read it: a budget and an S3 bucket, nothing else
terraform apply         # type "yes"
terraform output state_bucket
```

AWS sends a confirmation email for the budget alerts. Open it and confirm, or the alerts go nowhere. Keep this stack forever; it costs almost nothing.

## Step 2: The dev environment

```bash
cd ~/quickserve/infra/envs/dev
cp backend.hcl.example backend.hcl              # put the bucket name from step 1 in it
cp terraform.tfvars.example terraform.tfvars    # pick an image tag, e.g. sha-3073e30
terraform init -backend-config=backend.hcl
terraform plan          # about 30 resources; read what it will create
terraform apply         # type "yes". The database takes about 10 minutes.
```

When it finishes, Terraform prints `api_url`. The server needs about 3 more minutes to install Docker, pull the image and run the migrations. Then open `ready_url`: it should say `"database":"ok","redis":"ok"`.

**Load the demo data** (a shell on the server through Session Manager, so no SSH key and no open port 22):

```bash
brew install --cask session-manager-plugin      # one time
aws ssm start-session --target "$(terraform output -raw instance_id)"
sudo /opt/quickserve/seed.sh                      # demo data, with the live passwords (Phase 16)
sudo docker logs --tail 20 quickserve-worker
sudo tail -50 /var/log/quickserve-bootstrap.log  # if something went wrong at boot
exit
```

## Phase 16: live with HTTPS and automatic deploys

Do these once, after "Before you start". Each step is one thing to do; run the commands in the Terminal app on your Mac (or ask Claude Code to run them).

**1. Get a free name on DuckDNS.**
Go to https://www.duckdns.org and sign in (GitHub or Google). Type a name in the box, for example `quickserve-arushi`, and click **add domain**. Don't worry about the IP shown: the server will set it. Copy the **token** shown at the top of the page.

**2. Make both images public** (if you haven't): on GitHub, Profile → Packages → `quickserve` → Package settings → Change visibility → Public. Do the same for `quickserve-app`.

**3. Fill in `terraform.tfvars`** (in `infra/envs/dev`):
```hcl
image_tag     = "sha-0519a88"                       # the newest commit on main, with "sha-" in front
domain        = "quickserve-arushi.duckdns.org"     # your DuckDNS name
duckdns_token = "the-token-you-copied"
```
Git ignores this file, so the token never reaches GitHub.

**4. Create everything** (about 10 minutes, mostly the database):
```bash
cd ~/quickserve/infra/envs/dev
terraform init -backend-config=backend.hcl
terraform plan          # read it: about 40 resources
terraform apply         # type "yes"
```

**5. Wait 3–5 minutes, then open the site:**
```bash
terraform output -raw site_url      # e.g. https://quickserve-arushi.duckdns.org
```
The server installs Docker, points DuckDNS at itself, runs the migrations, starts everything and gets the certificate. If the page doesn't load yet, wait a minute and refresh.

**6. Turn on automatic deploys.** In the QuickServe folder:
```bash
cd ~/quickserve
terraform -chdir=infra/envs/dev output -raw github_setup_commands
```
It prints four `gh variable set ...` lines. Copy and run them. From now on, every merge to main that passes CI is deployed, smoke-tested and, if broken, rolled back. Watch it in GitHub → Actions → the `deploy` job, and in GitHub → the repository's **Environments** → `production`.

Optional, but a good habit: allow deploys from `main` only.
```bash
gh api -X PUT repos/revant123/QuickServe/environments/production \
  -F 'deployment_branch_policy[protected_branches]=false' -F 'deployment_branch_policy[custom_branch_policies]=true'
gh api -X POST repos/revant123/QuickServe/environments/production/deployment-branch-policies -f name=main
```

**7. Load the demo restaurants** (with passwords only you know). Session Manager needs a small plugin once: `brew install --cask session-manager-plugin`.
```bash
cd ~/quickserve/infra/envs/dev
aws ssm start-session --target "$(terraform output -raw instance_id)"
sudo /opt/quickserve/seed.sh
exit
terraform output -raw demo_customer_password; echo    # customer@quickserve.dev: OK to share
terraform output -raw demo_staff_password; echo       # owner@, rider@, admin@: keep to yourself
```

**8. See live traces** (Jaeger isn't on the internet). This opens a tunnel and stays running; press Ctrl+C to close it:
```bash
$(terraform output -raw jaeger_tunnel_command)
```
Then open http://localhost:16686.

**If something goes wrong**
- *The site doesn't load after 10 minutes:* `aws ssm start-session --target "$(terraform output -raw instance_id)"`, then `sudo tail -50 /var/log/quickserve-bootstrap.log` and `sudo docker logs quickserve-caddy`.
- *Certificate errors in Caddy's log:* check that `nslookup quickserve-arushi.duckdns.org` shows the server's IP (`terraform output public_ip`), and that `allowed_http_cidrs` isn't limited to your IP (Let's Encrypt must reach port 80).
- *The deploy job says "Not authorized to perform sts:AssumeRoleWithWebIdentity":* the token's subject doesn't match the trust policy. For a fork, set `github_owner_id` and `github_repository_id` to yours (`gh api repos/OWNER/NAME --jq '{owner_id: .owner.id, id}'`).
- *Deploy by hand, or roll back:* `scripts/live_deploy.sh sha-<commit>` or `scripts/live_deploy.sh rollback` (with `AWS_PROFILE=quickserve-tf` set).

**When you're done (1–2 weeks later):**
```bash
cd ~/quickserve
gh variable delete AWS_DEPLOY_ROLE_ARN      # stops the deploy job first (it's skipped, not failed)
cd infra/envs/dev && terraform destroy       # type "yes"; about 10 minutes
```
Then check Billing → Bills the next day.

## Deploying a new version

Since Phase 16 this happens by itself after every merge (step 6 above). By hand, it's the same command GitHub Actions runs:

```bash
scripts/live_deploy.sh sha-<commit>     # or: scripts/live_deploy.sh rollback
```

It runs the server's `deploy.sh` through the `quickserve-dev-deploy` SSM document, which accepts only `sha-<hex>` or `rollback`. `deploy.sh` re-reads the secrets, pulls both images, runs `alembic upgrade head`, starts the new API **next to** the old one, waits until it's ready, and only then stops the old one. Caddy moves traffic over by itself, so there's no downtime. If the new API never gets ready, it's removed and the old one keeps serving. A rollback goes back to the previous tag without running migrations (see "expand, then contract" in the main README).

## Step 3: Destroy (at the end of every session)

```bash
cd ~/quickserve/infra/envs/dev
terraform destroy       # type "yes"; about 10 minutes
```

This deletes the server, the database (including its data: the seed script recreates the demo data next time), the network and the secrets. The bootstrap stack (budget + state bucket) stays.

Afterwards, check the console's **Billing → Bills** page the next day: the dev resources should show no new charges.

## Checking the code without AWS

```bash
cd ~/quickserve/infra/envs/dev
terraform init -backend=false
terraform validate
terraform test          # 7 checks on the environment
cd ../../modules/app_server && terraform init && terraform test   # and so on for each module
```
