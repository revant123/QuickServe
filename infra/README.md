# QuickServe on AWS (Phase 6)

This folder holds the Terraform code that builds QuickServe on AWS. (The Kubernetes manifests in `k8s/` are separate: see "Kubernetes (Phase 7)" in the main README.) **Nothing here runs by itself, and nothing has been created in AWS yet.** CI only checks the code, using fake ("mock") AWS, so it costs nothing.

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
    └── app_server/   one t4g.small running the ghcr.io image with Docker
```

| Piece | What it is | Rough cost in Mumbai (ap-south-1), on-demand |
|---|---|---|
| App server | `t4g.small`, 2 ARM vCPUs, 2 GiB RAM | about USD 0.011 per hour (~USD 8 per month if left on) |
| Database | RDS `db.t4g.micro`, single-AZ, 20 GB | about USD 0.021 per hour (~USD 15 per month) |
| Public IPv4 address | needed to reach the server | USD 0.005 per hour (~USD 3.65 per month) |
| Disks | 16 GB (server) + 20 GB (database), gp3 | a few dollars per month; check the AWS Pricing Calculator |
| Parameter Store (secrets), Session Manager, Budgets alerts | | no charge |
| **Total if left running all month** | | **roughly USD 30** |
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
sudo docker exec quickserve-api python -m scripts.seed
sudo docker logs --tail 20 quickserve-worker
sudo tail -50 /var/log/quickserve-bootstrap.log  # if something went wrong at boot
exit
```

## Deploying a new version

Merge to main → CI publishes `ghcr.io/revant123/quickserve:sha-<commit>`. Then, without Terraform:

```bash
aws ssm send-command --instance-ids "$(terraform output -raw instance_id)" \
  --document-name AWS-RunShellScript \
  --parameters 'commands=["/opt/quickserve/deploy.sh sha-<commit>"]'
```

`deploy.sh` re-reads the secrets, pulls the image, runs `alembic upgrade head`, then swaps the API and the worker. The API is down for a few seconds during the swap; zero-downtime deploys come with a load balancer or Kubernetes (Phase 7). Rolling back is the same command with the previous tag.

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
terraform test          # 5 checks on the environment
cd ../../modules/app_server && terraform init && terraform test   # and so on for each module
```
