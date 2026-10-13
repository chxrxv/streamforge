import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("aws_cdk")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "infrastructure"))

import aws_cdk as cdk  # noqa: E402
from aws_cdk.assertions import Match, Template  # noqa: E402
from stack import StreamForgeStack  # noqa: E402


@pytest.fixture(scope="module")
def template() -> Template:
    app = cdk.App()
    stack = StreamForgeStack(app, "T", env_name="dev",
                             env=cdk.Environment(account="123456789012", region="ap-south-1"))
    return Template.from_stack(stack)


def test_bucket_is_private_and_encrypted(template):
    template.has_resource_properties("AWS::S3::Bucket", {
        "PublicAccessBlockConfiguration": {
            "BlockPublicAcls": True, "BlockPublicPolicy": True,
            "IgnorePublicAcls": True, "RestrictPublicBuckets": True},
        "BucketEncryption": Match.object_like({}),
    })


def test_bucket_policy_enforces_tls(template):
    policies = json.dumps(template.find_resources("AWS::S3::BucketPolicy"))
    assert "aws:SecureTransport" in policies


def test_dynamodb_on_demand_with_ttl(template):
    template.has_resource_properties("AWS::DynamoDB::Table", {
        "BillingMode": "PAY_PER_REQUEST",
        "TimeToLiveSpecification": {"AttributeName": "expires_at", "Enabled": True},
    })


def test_lambda_config(template):
    template.has_resource_properties("AWS::Lambda::Function", {
        "Handler": "streamforge.api.handler", "Runtime": "python3.12",
        "Environment": {"Variables": Match.object_like({"DATA_BUCKET": Match.any_value(),
                                                         "STATE_TABLE": Match.any_value()})},
    })


def test_every_method_but_health_requires_api_key(template):
    methods = template.find_resources("AWS::ApiGateway::Method")
    keyed = [m["Properties"].get("ApiKeyRequired", False) for m in methods.values()
             if m["Properties"]["HttpMethod"] != "OPTIONS"]
    assert keyed.count(True) == 3 and keyed.count(False) == 1  # health is the only open route


def test_usage_plan_has_throttle_and_quota(template):
    template.has_resource_properties("AWS::ApiGateway::UsagePlan", {
        "Throttle": {"BurstLimit": 20, "RateLimit": 10},
        "Quota": {"Limit": 10000, "Period": "DAY"},
    })


def test_iam_has_no_wildcard_actions_or_resources_for_data(template):
    for pol in template.find_resources("AWS::IAM::Policy").values():
        for st in pol["Properties"]["PolicyDocument"]["Statement"]:
            actions = st["Action"] if isinstance(st["Action"], list) else [st["Action"]]
            assert not any(a == "*" or a.endswith(":*") for a in actions), actions
            assert st["Resource"] != "*"


def test_lambda_cannot_delete_or_read_s3(template):
    blob = json.dumps(template.find_resources("AWS::IAM::Policy"))
    assert "s3:DeleteObject" not in blob and "s3:GetObject" not in blob


def test_outputs_present(template):
    outputs = template.to_json()["Outputs"]
    assert {"ApiUrl", "ApiKeyId", "DataBucketName", "StateTableName"} <= set(outputs)


def test_prod_retains_data():
    app = cdk.App()
    stack = StreamForgeStack(app, "P", env_name="prod",
                             env=cdk.Environment(account="123456789012", region="ap-south-1"))
    t = Template.from_stack(stack)
    t.has_resource("AWS::S3::Bucket", {"DeletionPolicy": "Retain"})
    t.has_resource("AWS::DynamoDB::Table", {"DeletionPolicy": "Retain"})
