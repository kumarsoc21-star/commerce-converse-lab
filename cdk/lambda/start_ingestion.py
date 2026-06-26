"""Starts a Bedrock Knowledge Base ingestion job (invoked by CDK Trigger after policy upload)."""

from __future__ import annotations

import os
import uuid

import boto3

_client = boto3.client('bedrock-agent')


def lambda_handler(event, context):
    kb_id = os.environ['KNOWLEDGE_BASE_ID']
    ds_id = os.environ['DATA_SOURCE_ID']
    resp = _client.start_ingestion_job(
        knowledgeBaseId=kb_id,
        dataSourceId=ds_id,
        clientToken=str(uuid.uuid4()),
        description='commerce-converse-lab policy sync',
    )
    job = resp.get('ingestionJob', {})
    return {
        'ingestionJobId': job.get('ingestionJobId'),
        'status': job.get('status'),
    }
