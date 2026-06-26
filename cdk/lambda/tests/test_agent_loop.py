"""Tests for confirm-write replay in agent_loop."""

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


def _pending_transcript():
    return [
        {'role': 'user', 'content': [{'text': 'Add the AirPods to my cart'}]},
        {
            'role': 'assistant',
            'content': [
                {
                    'toolUse': {
                        'toolUseId': 'tool-1',
                        'name': 'place_in_cart',
                        'input': {'item_sku': 'APPL-001', 'qty_held': 1},
                    }
                }
            ],
        },
        {
            'role': 'user',
            'content': [
                {
                    'toolResult': {
                        'toolUseId': 'tool-1',
                        'content': [
                            {
                                'json': {
                                    'result': {
                                        'outcome': 'confirmation_required',
                                        'action': 'place_in_cart',
                                        'details': {'item_sku': 'APPL-001', 'qty_held': 1},
                                    }
                                }
                            }
                        ],
                    }
                }
            ],
        },
        {'role': 'assistant', 'content': [{'text': 'Please confirm to add the headlamp.'}]},
    ]


@patch('agent_loop.runtime')
@patch('agent_loop.dispatch')
def test_confirm_replays_pending_place_in_cart(mock_dispatch, mock_runtime):
    import agent_loop as al

    mock_dispatch.return_value = {
        'outcome': 'placed',
        'itemSku': 'APPL-001',
        'displayName': 'AirPods Pro',
        'cartQty': 1,
        'lineCount': 1,
        'grandTotal': 32.0,
    }
    mock_runtime.converse.return_value = {
        'stopReason': 'end_turn',
        'output': {'message': {'role': 'assistant', 'content': [{'text': 'Added the headlamp to your cart.'}]}},
    }

    transcript = _pending_transcript()
    result = al.run_converse_loop(
        'Yes, please proceed',
        transcript=transcript,
        shopper_ref='demo-shopper',
        confirm_writes=True,
    )

    mock_dispatch.assert_called_once_with(
        'place_in_cart',
        {'item_sku': 'APPL-001', 'qty_held': 1, 'shopper_ref': 'demo-shopper'},
    )
    assert any(step['phase'] == 'executed' and step['name'] == 'place_in_cart' for step in result['toolTrace'])
    patched = _tool_result(transcript, 'tool-1')
    assert patched['outcome'] == 'placed'


def _tool_result(transcript, tool_use_id):
    for msg in transcript:
        if msg.get('role') != 'user':
            continue
        for block in msg.get('content', []):
            tool_result = block.get('toolResult')
            if tool_result and tool_result.get('toolUseId') == tool_use_id:
                return tool_result['content'][0]['json']['result']
    raise AssertionError('tool result not found')


@patch('agent_loop.dispatch')
def test_find_pending_writes(mock_dispatch):
    import agent_loop as al

    pending = al._find_pending_writes(_pending_transcript())
    assert len(pending) == 1
    assert pending[0]['name'] == 'place_in_cart'
    assert pending[0]['input']['item_sku'] == 'APPL-001'
