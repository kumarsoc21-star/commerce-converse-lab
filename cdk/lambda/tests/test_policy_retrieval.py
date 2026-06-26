"""Tests for policy retrieval guardrail (Bedrock mocked)."""

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import policy_retrieval as pr


def test_lookup_policies_kb_pending_when_no_id(monkeypatch):
    monkeypatch.setenv('KNOWLEDGE_BASE_ID', '')
    out = pr.lookup_policies('returns policy')
    assert out['outcome'] == 'kb_pending'


@patch('policy_retrieval._agent_runtime')
def test_lookup_policies_guardrail_rejects_low_scores(mock_runtime, monkeypatch):
    monkeypatch.setenv('KNOWLEDGE_BASE_ID', 'KB123')
    mock_runtime.retrieve.return_value = {
        'retrievalResults': [
            {
                'score': 0.1,
                'content': {'text': 'low relevance chunk'},
                'metadata': {},
                'location': {'s3Location': {'uri': 's3://b/policies/returns.md'}},
            }
        ]
    }
    out = pr.lookup_policies('store in Madrid?')
    assert out['outcome'] == 'no_relevant_docs'


@patch('policy_retrieval._agent_runtime')
def test_lookup_policies_returns_excerpts(mock_runtime, monkeypatch):
    monkeypatch.setenv('KNOWLEDGE_BASE_ID', 'KB123')
    mock_runtime.retrieve.return_value = {
        'retrievalResults': [
            {
                'score': 0.82,
                'content': {'text': 'Returns accepted within 30 days.'},
                'metadata': {'section': 'Window'},
                'location': {'s3Location': {'uri': 's3://b/policies/returns.md'}},
            }
        ]
    }
    out = pr.lookup_policies('return policy')
    assert out['outcome'] == 'ok'
    assert out['excerpts'][0]['docRef'] == 'returns'
    assert out['excerpts'][0]['relevance'] == 0.82
