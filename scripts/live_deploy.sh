#!/usr/bin/env bash
# Deploy one image tag to the live AWS server, or roll back (Phase 16).
#
#   scripts/live_deploy.sh sha-<commit>
#   scripts/live_deploy.sh rollback
#
# GitHub Actions runs this after every merge to main. It works from a laptop
# too, with AWS credentials (aws login): same command, same result.
#
# It doesn't SSH anywhere. It asks AWS Systems Manager to run the server's own
# deploy.sh, through the one SSM document the deploy role may use, then waits
# for the result and prints the server's output.
set -euo pipefail

TAG="${1:?usage: scripts/live_deploy.sh sha-<commit> | rollback}"
PARAM="${DEPLOY_TARGET_PARAMETER:-/quickserve/dev/deploy_target}"

# Which server and document: written by Terraform, so a replaced server is
# found without changing anything in GitHub.
target="$(aws ssm get-parameter --name "$PARAM" --query Parameter.Value --output text)"
instance="$(python3 -c 'import json, sys; print(json.loads(sys.argv[1])["instance_id"])' "$target")"
document="$(python3 -c 'import json, sys; print(json.loads(sys.argv[1])["document"])' "$target")"

command_id="$(aws ssm send-command \
  --instance-ids "$instance" \
  --document-name "$document" \
  --parameters "tag=$TAG" \
  --comment "QuickServe $TAG (${GITHUB_REPOSITORY:-manual} run ${GITHUB_RUN_ID:-local})" \
  --query Command.CommandId --output text)"
echo "Deploying $TAG to $instance (SSM command $command_id)"

# deploy.sh takes about a minute: pull, migrate, start, wait until ready, swap.
status=Pending
for _ in $(seq 1 120); do
  sleep 5
  status="$(aws ssm get-command-invocation --command-id "$command_id" --instance-id "$instance" \
    --query Status --output text 2>/dev/null || echo Pending)"
  case "$status" in
    Success | Failed | Cancelled | TimedOut) break ;;
  esac
done

echo "----- output from the server -----"
aws ssm get-command-invocation --command-id "$command_id" --instance-id "$instance" \
  --query StandardOutputContent --output text || true
errors="$(aws ssm get-command-invocation --command-id "$command_id" --instance-id "$instance" \
  --query StandardErrorContent --output text || true)"
[ -n "$errors" ] && [ "$errors" != "None" ] && printf -- '----- errors -----\n%s\n' "$errors"
echo "----------------------------------"

if [ "$status" != Success ]; then
  echo "::error::Deploy of $TAG ended with status $status. deploy.sh only swaps to a new version once it's ready, so the previous version is still serving."
  exit 1
fi
echo "Deployed $TAG"
