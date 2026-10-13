#!/usr/bin/env python3
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import aws_cdk as cdk  # noqa: E402
from stack import StreamForgeStack  # noqa: E402

app = cdk.App()
env_name = app.node.try_get_context("env_name") or os.environ.get("STREAMFORGE_ENV", "dev")
StreamForgeStack(
    app,
    f"StreamForge-{env_name}",
    env_name=env_name,
    env=cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=os.environ.get("CDK_DEFAULT_REGION") or os.environ.get("AWS_REGION") or "ap-south-1",
    ),
)
app.synth()
