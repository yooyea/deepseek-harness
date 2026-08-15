"""Provision the private OSS bucket used by the tenant control plane."""

from __future__ import annotations

import hashlib
import os

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

region = os.environ.get("OSS_REGION", "cn-shanghai").strip() or "cn-shanghai"
endpoint = os.environ.get("OSS_ENDPOINT", "").strip() or f"https://s3.oss-{region}.aliyuncs.com"
bucket = os.environ.get("OSS_BUCKET", "").strip()
if not bucket:
    seed = f"{os.environ['GITHUB_REPOSITORY']}:{os.environ['SERVER_IP']}"
    bucket = f"linehalo-deepharness-{hashlib.sha256(seed.encode()).hexdigest()[:12]}"

client = boto3.client(
    "s3",
    endpoint_url=endpoint,
    region_name=region,
    aws_access_key_id=os.environ["ALIYUN_ID"],
    aws_secret_access_key=os.environ["ALIYUN_SECRET"],
    config=Config(signature_version="s3", s3={"addressing_style": "virtual"}),
)

try:
    client.head_bucket(Bucket=bucket)
except ClientError as error:
    if error.response.get("ResponseMetadata", {}).get("HTTPStatusCode") != 404:
        raise
    # OSS selects the region from the endpoint and rejects AWS's
    # CreateBucketConfiguration.LocationConstraint payload.
    client.create_bucket(Bucket=bucket)

client.put_bucket_versioning(
    Bucket=bucket,
    VersioningConfiguration={"Status": "Enabled"},
)
client.put_bucket_lifecycle_configuration(
    Bucket=bucket,
    LifecycleConfiguration={
        "Rules": [
            {
                "ID": "expire-incomplete-uploads",
                "Status": "Enabled",
                "Filter": {"Prefix": ""},
                "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 7},
            }
        ]
    },
)

github_env = os.environ.get("GITHUB_ENV")
if github_env:
    with open(github_env, "a", encoding="utf-8") as output:
        output.write(f"OSS_BUCKET={bucket}\nOSS_ENDPOINT={endpoint}\nOSS_REGION={region}\n")
print(bucket)
