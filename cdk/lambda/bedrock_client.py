"""Bedrock runtime client for the Converse API."""

import os

import boto3

GEN_MODEL_ID = os.environ.get('GEN_MODEL_ID', 'us.anthropic.claude-haiku-4-5-20251001-v1:0')
REGION = os.environ.get('AWS_REGION', 'us-east-1')

runtime = boto3.client('bedrock-runtime', region_name=REGION)
