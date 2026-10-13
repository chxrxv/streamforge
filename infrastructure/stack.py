"""StreamForge Phase 1 stack: API Gateway -> Lambda -> S3 (data) + DynamoDB (idempotency, metrics)."""
from __future__ import annotations

from pathlib import Path

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
    Tags,
)
from aws_cdk import (
    aws_apigateway as apigw,
)
from aws_cdk import (
    aws_dynamodb as dynamodb,
)
from aws_cdk import (
    aws_iam as iam,
)
from aws_cdk import (
    aws_lambda as _lambda,
)
from aws_cdk import (
    aws_logs as logs,
)
from aws_cdk import (
    aws_s3 as s3,
)
from constructs import Construct

SRC_DIR = str(Path(__file__).resolve().parent.parent / "src")


class StreamForgeStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, env_name: str = "dev", **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        ephemeral = env_name != "prod"  # non-prod stacks tear down cleanly with `cdk destroy`
        removal = RemovalPolicy.DESTROY if ephemeral else RemovalPolicy.RETAIN

        bucket = s3.Bucket(
            self, "DataBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=removal,
            auto_delete_objects=ephemeral,
            lifecycle_rules=[
                s3.LifecycleRule(id="expire-rejected", prefix="rejected/", expiration=Duration.days(90)),
                s3.LifecycleRule(id="abort-mpu", abort_incomplete_multipart_upload_after=Duration.days(7)),
            ],
        )

        table = dynamodb.Table(
            self, "StateTable",
            partition_key=dynamodb.Attribute(name="pk", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="expires_at",
            removal_policy=removal,
        )

        fn = _lambda.Function(
            self, "ApiFunction",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="streamforge.api.handler",
            code=_lambda.Code.from_asset(SRC_DIR, exclude=["**/__pycache__", "**/*.pyc"]),
            memory_size=256,
            timeout=Duration.seconds(15),
            environment={"DATA_BUCKET": bucket.bucket_name, "STATE_TABLE": table.table_name,
                         "STREAMFORGE_ENV": env_name},
            log_group=logs.LogGroup(
                self, "ApiLogs", retention=logs.RetentionDays.ONE_WEEK, removal_policy=RemovalPolicy.DESTROY
            ),
        )
        # Least privilege: write-only to the three data prefixes; no list/delete on the bucket.
        fn.add_to_role_policy(iam.PolicyStatement(
            actions=["s3:PutObject"],
            resources=[bucket.arn_for_objects(f"{p}/*") for p in ("raw", "processed", "rejected")],
        ))
        fn.add_to_role_policy(iam.PolicyStatement(
            actions=["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:UpdateItem", "dynamodb:Scan"],
            resources=[table.table_arn],
        ))

        api = apigw.RestApi(
            self, "Api",
            rest_api_name=f"streamforge-{env_name}",
            description="StreamForge ingestion API (API-key protected)",
            cloud_watch_role=False,  # do not touch the account-wide API Gateway logging role
            deploy_options=apigw.StageOptions(
                stage_name=env_name, throttling_rate_limit=10, throttling_burst_limit=20,
            ),
            binary_media_types=[],
        )
        integration = apigw.LambdaIntegration(fn, proxy=True)
        events = api.root.add_resource("events")
        events.add_method("POST", integration, api_key_required=True)
        events.add_resource("batch").add_method("POST", integration, api_key_required=True)
        api.root.add_resource("metrics").add_method("GET", integration, api_key_required=True)
        api.root.add_resource("health").add_method("GET", integration)  # unauthenticated liveness only

        key = api.add_api_key("ApiKey", api_key_name=f"streamforge-{env_name}-key")
        plan = api.add_usage_plan(
            "UsagePlan", name=f"streamforge-{env_name}",
            throttle=apigw.ThrottleSettings(rate_limit=10, burst_limit=20),
            quota=apigw.QuotaSettings(limit=10_000, period=apigw.Period.DAY),
        )
        plan.add_api_key(key)
        plan.add_api_stage(stage=api.deployment_stage)

        Tags.of(self).add("Project", "StreamForge")
        Tags.of(self).add("Environment", env_name)
        Tags.of(self).add("ManagedBy", "cdk")

        CfnOutput(self, "ApiUrl", value=api.url)
        CfnOutput(self, "ApiKeyId", value=key.key_id,
                  description="Fetch the secret value with: aws apigateway get-api-key --include-value")
        CfnOutput(self, "DataBucketName", value=bucket.bucket_name)
        CfnOutput(self, "StateTableName", value=table.table_name)
        CfnOutput(self, "RawPrefix", value=f"s3://{bucket.bucket_name}/raw/")
        CfnOutput(self, "ProcessedPrefix", value=f"s3://{bucket.bucket_name}/processed/")
        CfnOutput(self, "RejectedPrefix", value=f"s3://{bucket.bucket_name}/rejected/")
