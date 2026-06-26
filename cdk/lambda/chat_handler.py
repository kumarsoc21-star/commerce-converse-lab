"""HTTP API handler — routes /health, /chat, /cart, /cart/place, /cart/remove, /cart/clear."""

from __future__ import annotations

import json
import os

from agent_loop import run_converse_loop
from dynamo_store import clear_cart, place_in_cart, read_cart, remove_from_cart


def _json(body, status=200):
    return {
        'statusCode': status,
        'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
        'body': json.dumps(body, default=str),
    }


def _path_parts(event):
    raw = event.get('rawPath') or event.get('path') or ''
    return [p for p in raw.split('/') if p]


def _body(event):
    body = event.get('body') or '{}'
    if event.get('isBase64Encoded'):
        import base64
        body = base64.b64decode(body).decode()
    return json.loads(body) if body else {}


def _collect_listings(tool_trace):
    listings = []
    for step in tool_trace:
        if step['name'] == 'find_products' and step.get('phase') == 'executed':
            result = step.get('result')
            if isinstance(result, list):
                listings = result
    return listings


def _collect_sources(tool_trace):
    sources, seen = [], set()
    for step in tool_trace:
        if step['name'] != 'lookup_policies' or step.get('phase') != 'executed':
            continue
        payload = step.get('result') or {}
        for chunk in payload.get('excerpts', []):
            key = (chunk.get('docRef'), chunk.get('sectionLabel'))
            if key not in seen:
                seen.add(key)
                sources.append(chunk)
    return sources


def lambda_handler(event, context):
    parts = _path_parts(event)
    method = event.get('requestContext', {}).get('http', {}).get('method') or event.get('httpMethod', 'GET')

    if method == 'GET' and parts == ['health']:
        kb_id = os.environ.get('KNOWLEDGE_BASE_ID', '').strip()
        return _json({
            'status': 'ok',
            'engine': 'bedrock-converse-lambda',
            'policyKb': 'ready' if kb_id else 'pending',
            'knowledgeBaseId': kb_id or None,
        })

    if method == 'GET' and parts == ['cart']:
        query = event.get('queryStringParameters') or {}
        shopper_ref = query.get('shopperRef') or 'demo-shopper'
        return _json(read_cart(shopper_ref))

    if method == 'POST' and parts == ['cart', 'place']:
        payload = _body(event)
        item_sku = payload.get('itemSku')
        if not item_sku:
            return _json({'error': 'itemSku is required'}, 400)
        shopper_ref = payload.get('shopperRef') or 'demo-shopper'
        cart_qty = int(payload.get('cartQty', payload.get('qtyHeld', 1)))
        result = place_in_cart(shopper_ref, item_sku, cart_qty)
        if result.get('outcome') == 'error':
            return _json({'error': result['detail']}, 404)
        return _json(read_cart(shopper_ref))

    if method == 'POST' and parts == ['cart', 'remove']:
        payload = _body(event)
        item_sku = payload.get('itemSku')
        if not item_sku:
            return _json({'error': 'itemSku is required'}, 400)
        shopper_ref = payload.get('shopperRef') or 'demo-shopper'
        result = remove_from_cart(shopper_ref, item_sku)
        if result.get('outcome') == 'error':
            return _json({'error': result['detail']}, 404)
        return _json(read_cart(shopper_ref))

    if method == 'POST' and parts == ['cart', 'clear']:
        payload = _body(event)
        shopper_ref = payload.get('shopperRef') or 'demo-shopper'
        clear_cart(shopper_ref)
        return _json(read_cart(shopper_ref))

    if method == 'POST' and parts == ['chat']:
        payload = _body(event)
        utterance = payload.get('utterance')
        if not utterance:
            return _json({'error': 'utterance is required'}, 400)

        shopper_ref = payload.get('shopperRef') or 'demo-shopper'
        confirm_writes = bool(payload.get('confirmWrites', False))
        transcript = payload.get('transcript')

        result = run_converse_loop(
            utterance,
            transcript=transcript,
            shopper_ref=shopper_ref,
            confirm_writes=confirm_writes,
        )
        cart = read_cart(shopper_ref)

        return _json(
            {
                'reply': result['reply'],
                'sources': _collect_sources(result['toolTrace']),
                'listings': _collect_listings(result['toolTrace']),
                'cart': cart,
                'toolTrace': [{'name': t['name'], 'phase': t['phase']} for t in result['toolTrace']],
                'transcript': result['transcript'],
            }
        )

    return _json({'error': 'Not found', 'path': parts}, 404)
