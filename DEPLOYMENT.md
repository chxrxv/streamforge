# Deployment

## Current status

**Phase 1 is NOT deployed to AWS.** The environment this was built in has no AWS CLI and no AWS credentials (`~/.aws` absent, no `AWS_*` variables), so deployment was not attempted. Everything else (tests, CDK synthesis, local run) has been executed. No endpoint URL exists yet.

## Prerequisites
- AWS account and an IAM principal that can create the resources in `infrastructure/stack.py` (CloudFormation, S3, DynamoDB, Lambda, IAM roles, API Gateway, Logs). Use an admin/PowerUser sandbox account for a portfolio project.
- Node.js 18+ and Python 3.11+.
- AWS CLI v2 (<https://aws.amazon.com/cli/>) and CDK CLI: `npm install -g aws-cdk`.

## Shortest path to unblock
```powershell
aws configure sso            # or: aws configure   (keys stay in ~/.aws, never in the repo)
aws sts get-caller-identity  # confirm account
$env:AWS_REGION = "ap-south-1"   # Mumbai; any region with API Gateway/Lambda/DynamoDB works
```

## Deploy
```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m pytest                    # must pass first
cdk bootstrap                                       # once per account/region (creates a staging bucket + roles)
cdk diff                                            # review changes
cdk deploy --outputs-file cdk-outputs.json          # stack: StreamForge-dev
```
Use `-c env_name=prod` for a stack that **retains** the bucket and table on destroy.

## Get the API key and smoke test
```powershell
$out = (Get-Content cdk-outputs.json | ConvertFrom-Json)."StreamForge-dev"
$env:STREAMFORGE_API_URL = $out.ApiUrl
$env:STREAMFORGE_API_KEY = aws apigateway get-api-key --api-key $out.ApiKeyId --include-value --query value --output text
.\.venv\Scripts\python scripts\smoke_test.py
aws s3 ls "s3://$($out.DataBucketName)/processed/" --recursive
```
Never commit `cdk-outputs.json` values containing the key, or the key itself (`cdk-outputs.json` contains only the key *id*, but is git-ignored anyway).

## API quick reference
```
POST /events          one event            201 accepted | 200 duplicate | 422 rejected | 400 | 413 | 503
POST /events/batch    {"events":[...]}     200 with results (max 100)
GET  /metrics         quality metrics
GET  /health          liveness (no key)
Header: x-api-key: <key>
```

## Local (non-AWS) workflow
```powershell
.\.venv\Scripts\python scripts\local_server.py 8000          # in-memory dedup/metrics, files in ./local_data
$env:STREAMFORGE_API_URL="http://127.0.0.1:8000"; $env:STREAMFORGE_API_KEY="local"
.\.venv\Scripts\python scripts\smoke_test.py
```
This is a local run, not a cloud deployment.

## Teardown
`cdk destroy` removes this stack's resources only. For `dev`, the S3 bucket is emptied automatically (`auto_delete_objects`) and deleted; for `prod` the bucket and table are retained and must be removed manually after you confirm the data is not needed. `cdk bootstrap` resources (CDKToolkit stack) are shared and left alone. Nothing here runs `destroy` automatically.
