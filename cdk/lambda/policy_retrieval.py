"""Bedrock Knowledge Base retrieval for lookup_policies with relevance guardrail."""

from __future__ import annotations

import os
import re

import boto3

RELEVANCE_THRESHOLD = float(os.environ.get('POLICY_RELEVANCE_THRESHOLD', '0.25'))

_agent_runtime = boto3.client('bedrock-agent-runtime')


def _kb_id() -> str:
    return os.environ.get('KNOWLEDGE_BASE_ID', '').strip()


def _doc_ref_from_uri(uri: str) -> str:
    if not uri:
        return 'unknown-doc'
    name = uri.rstrip('/').split('/')[-1]
    return re.sub(r'\.md$', '', name, flags=re.IGNORECASE) or name


def _section_label(metadata: dict) -> str:
    for key in ('section', 'doc_title', 'x-amz-bedrock-kb-source-uri'):
        val = metadata.get(key)
        if val:
            return str(val).split('/')[-1]
    return 'general'


def lookup_policies(question: str) -> dict:
    if not _kb_id():
        return {
            'outcome': 'kb_pending',
            'detail': 'Policy knowledge base is not configured on this deployment.',
        }

    resp = _agent_runtime.retrieve(
        knowledgeBaseId=_kb_id(),
        retrievalQuery={'text': question},
        retrievalConfiguration={
            'vectorSearchConfiguration': {'numberOfResults': 5},
        },
    )

    excerpts = []
    for hit in resp.get('retrievalResults', []):
        score = float(hit.get('score') or 0)
        content = (hit.get('content') or {}).get('text', '')
        metadata = hit.get('metadata') or {}
        location = hit.get('location') or {}
        s3_uri = ((location.get('s3Location') or {}).get('uri')) or metadata.get(
            'x-amz-bedrock-kb-source-uri', ''
        )
        excerpts.append(
            {
                'bodyText': content,
                'docRef': _doc_ref_from_uri(s3_uri),
                'sectionLabel': _section_label(metadata),
                'relevance': round(score, 3),
            }
        )

    excerpts.sort(key=lambda e: e['relevance'], reverse=True)

    if not excerpts or excerpts[0]['relevance'] < RELEVANCE_THRESHOLD:
        return {'outcome': 'no_relevant_docs'}

    return {'outcome': 'ok', 'excerpts': excerpts[:3]}
