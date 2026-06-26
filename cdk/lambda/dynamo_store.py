"""DynamoDB persistence for Trail & Ember catalog, cart, and support tickets."""

from __future__ import annotations

import os
import time
import uuid
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Attr, Key

_dynamo = boto3.resource('dynamodb')
_table_cache: dict[str, object] = {}


def _table(env_var: str):
    if env_var not in _table_cache:
        _table_cache[env_var] = _dynamo.Table(os.environ[env_var])
    return _table_cache[env_var]


def _catalog():
    return _table('CATALOG_TABLE')


def _cart():
    return _table('CART_TABLE')


def _cases():
    return _table('CASES_TABLE')


def _now_iso() -> str:
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def _dec(val) -> float:
    if isinstance(val, Decimal):
        return float(val)
    return float(val)


def _catalog_row_from_seed(row: dict) -> dict:
    """Map seed JSON keys to Trail & Ember DynamoDB attribute names."""
    if 'trailSku' in row:
        sku = row['trailSku']
        title = row['giftTitle']
        dept = row['trailDept']
        dept_key = row['trailDeptKey']
        price = row['emberPrice']
        stock = row['stockQty']
        blurb = row.get('giftBlurb', '')
        thumb = row.get('thumbUrl', '')
    else:
        sku = row['itemSku']
        title = row['displayName']
        dept = row['deptLabel']
        dept_key = row['deptKey']
        price = row['unitPrice']
        stock = row['qtyAvailable']
        blurb = row.get('blurb', '')
        thumb = row.get('thumbUrl', '')

    return {
        'trailSku': sku,
        'giftTitle': title,
        'trailDept': dept,
        'trailDeptKey': dept_key,
        'emberPrice': Decimal(str(price)),
        'stockQty': int(stock),
        'giftBlurb': blurb,
        'thumbUrl': thumb,
    }


def _catalog_view(row: dict) -> dict:
    return {
        'itemSku': row['trailSku'],
        'displayName': row['giftTitle'],
        'deptLabel': row['trailDept'],
        'unitPrice': _dec(row['emberPrice']),
        'qtyAvailable': int(row['stockQty']),
        'blurb': row.get('giftBlurb', ''),
        'thumbUrl': row.get('thumbUrl', ''),
    }


def seed_catalog_rows(rows: list[dict]) -> int:
    written = 0
    with _catalog().batch_writer() as batch:
        for row in rows:
            batch.put_item(Item=_catalog_row_from_seed(row))
            written += 1
    return written


def _row_search_text(row: dict) -> str:
    return (
        f"{row['giftTitle']} {row.get('giftBlurb', '')} "
        f"{row['trailDept']} {row.get('trailDeptKey', '')}"
    ).lower()


def _row_matches_keywords(row: dict, keywords: str) -> bool:
    """Case-insensitive token match against title, blurb, and department fields."""
    tokens = [t for t in keywords.lower().split() if len(t) >= 2]
    if not tokens:
        tokens = [keywords.lower()]
    text = _row_search_text(row)
    return any(token in text for token in tokens)


def _brand_dept_from_keywords(keywords: str) -> str | None:
    kw = keywords.lower()
    if any(term in kw for term in ('samsung', 'galaxy', 'android')):
        return 'Samsung'
    if any(term in kw for term in ('apple', 'iphone', 'ipad', 'airpods', 'macbook')):
        return 'Apple'
    return None


def _row_matches_brand(row: dict, brand_dept: str) -> bool:
    text = _row_search_text(row)
    if brand_dept == 'Samsung':
        return any(term in text for term in ('samsung', 'galaxy', 'android', 'smarttag'))
    if brand_dept == 'Apple':
        return any(
            term in text
            for term in ('apple', 'iphone', 'ipad', 'airpods', 'macbook', 'magsafe')
        )
    return True


_ACCESSORY_TERMS = ('accessory', 'accessories', 'charger', 'case', 'cable')
_BRAND_DEPTS = frozenset({'Samsung', 'Apple'})


def _brand_dept_from_context(dept_label: str | None, keywords: str | None) -> str | None:
    if dept_label in _BRAND_DEPTS:
        return dept_label
    if keywords:
        return _brand_dept_from_keywords(keywords)
    return None


def _is_brand_accessory_query(dept_label: str | None, keywords: str | None) -> bool:
    if not keywords:
        return False
    brand_dept = _brand_dept_from_context(dept_label, keywords)
    if not brand_dept:
        return False
    kw = keywords.lower()
    has_accessory = any(term in kw for term in _ACCESSORY_TERMS)
    if has_accessory:
        return True
    return dept_label == 'Accessories'


def _find_brand_accessory_products(
    brand_dept: str,
    min_price=None,
    max_price=None,
    in_stock_only=True,
    limit=5,
) -> list[dict]:
    accessory_rows = _scan_catalog(
        dept_label='Accessories',
        min_price=min_price,
        max_price=max_price,
        in_stock_only=in_stock_only,
    )
    accessory_rows = [row for row in accessory_rows if _row_matches_brand(row, brand_dept)]

    brand_rows = _scan_catalog(
        dept_label=brand_dept,
        min_price=min_price,
        max_price=max_price,
        in_stock_only=in_stock_only,
    )
    brand_rows = [
        row
        for row in brand_rows
        if 'gift card' not in row['giftTitle'].lower() and _is_accessory_like_row(row)
    ]
    return _merge_catalog_rows(accessory_rows, brand_rows, limit=limit)


def _is_accessory_like_row(row: dict) -> bool:
    text = f"{row['giftTitle']} {row.get('giftBlurb', '')}".lower()
    markers = ('buds', 'tag', 'charger', 'case', 'cable', 'tracker', 'earbuds', 'smarttag')
    return any(marker in text for marker in markers)


_DEPT_HINTS = (
    ('Apple', ('apple', 'iphone', 'ipad', 'airpods', 'macbook', 'watch')),
    ('Samsung', ('samsung', 'galaxy', 'android')),
    ('Ebooks', ('ebook', 'ebooks', 'kindle', 'audiobook', 'audible', 'book')),
    ('Gift Cards', ('gift card', 'giftcard', 'prepaid', 'store credit')),
    ('Accessories', ('accessory', 'accessories', 'charger', 'case', 'cable', 'tech')),
    ('Smart Home', ('smart home', 'alexa', 'echo', 'hue', 'doorbell', 'smartthings')),
)


def _dept_hint_from_keywords(keywords: str) -> str | None:
    kw = keywords.lower()
    has_accessory = any(term in kw for term in _ACCESSORY_TERMS)
    has_samsung = any(term in kw for term in ('samsung', 'galaxy', 'android'))
    has_apple = any(term in kw for term in ('apple', 'iphone', 'ipad', 'airpods', 'macbook'))
    if has_accessory and (has_samsung or has_apple):
        return 'Accessories'

    for dept, terms in _DEPT_HINTS:
        if any(term in kw for term in terms):
            return dept
    return None


def _hint_terms_for_dept(dept_label: str) -> tuple[str, ...]:
    for dept, terms in _DEPT_HINTS:
        if dept == dept_label:
            return terms
    return ()


def _text_filter_keywords(keywords: str, dept_label: str | None, dept_from_hint: str | None) -> str | None:
    """Drop department-routing terms when they already selected dept_label."""
    if not keywords or not dept_label or dept_from_hint != dept_label:
        return keywords

    kw = keywords.lower()
    for term in sorted(_hint_terms_for_dept(dept_label), key=len, reverse=True):
        kw = kw.replace(term, ' ')
    tokens = [t for t in kw.split() if len(t) >= 2]
    if not tokens:
        return None
    return ' '.join(tokens)


def _scan_catalog(
    dept_label=None,
    min_price=None,
    max_price=None,
    in_stock_only=True,
    keywords=None,
    dept_from_hint=None,
):
    filt = None
    if dept_label:
        clause = Attr('trailDept').contains(dept_label)
        filt = clause if filt is None else filt & clause
    if min_price is not None:
        clause = Attr('emberPrice').gte(Decimal(str(min_price)))
        filt = clause if filt is None else filt & clause
    if max_price is not None:
        clause = Attr('emberPrice').lte(Decimal(str(max_price)))
        filt = clause if filt is None else filt & clause
    if in_stock_only:
        clause = Attr('stockQty').gt(0)
        filt = clause if filt is None else filt & clause

    scan_kwargs = {}
    if filt is not None:
        scan_kwargs['FilterExpression'] = filt

    items = []
    resp = _catalog().scan(**scan_kwargs)
    items.extend(resp.get('Items', []))
    while 'LastEvaluatedKey' in resp:
        resp = _catalog().scan(ExclusiveStartKey=resp['LastEvaluatedKey'], **scan_kwargs)
        items.extend(resp.get('Items', []))

    if keywords:
        text_keywords = _text_filter_keywords(keywords, dept_label, dept_from_hint)
        if text_keywords:
            items = [row for row in items if _row_matches_keywords(row, text_keywords)]
    return items


def _merge_catalog_rows(*groups: list[dict], limit: int) -> list[dict]:
    seen: set[str] = set()
    merged: list[dict] = []
    for group in groups:
        for row in group:
            sku = row['trailSku']
            if sku in seen:
                continue
            seen.add(sku)
            merged.append(row)
    merged.sort(key=lambda r: _dec(r['emberPrice']))
    return merged[: int(limit)]


def find_products(
    dept_label=None,
    min_price=None,
    max_price=None,
    in_stock_only=True,
    keywords=None,
    limit=5,
):
    dept_from_hint = None
    if not dept_label and keywords:
        dept_label = _dept_hint_from_keywords(keywords)
        dept_from_hint = dept_label

    if _is_brand_accessory_query(dept_label, keywords):
        brand_dept = _brand_dept_from_context(dept_label, keywords)
        items = _find_brand_accessory_products(
            brand_dept,
            min_price=min_price,
            max_price=max_price,
            in_stock_only=in_stock_only,
            limit=limit,
        )
        return [_catalog_view(r) for r in items]

    items = _scan_catalog(
        dept_label=dept_label,
        min_price=min_price,
        max_price=max_price,
        in_stock_only=in_stock_only,
        keywords=keywords,
        dept_from_hint=dept_from_hint,
    )
    items.sort(key=lambda r: _dec(r['emberPrice']))
    return [_catalog_view(r) for r in items[: int(limit)]]


def get_catalog_line(item_sku: str) -> dict | None:
    resp = _catalog().get_item(Key={'trailSku': item_sku})
    row = resp.get('Item')
    return _catalog_view(row) if row else None


def place_in_cart(shopper_ref: str, item_sku: str, qty_held: int = 1) -> dict:
    line = get_catalog_line(item_sku)
    if line is None:
        return {'outcome': 'error', 'detail': f'No catalog line for itemSku {item_sku}'}

    _cart().put_item(
        Item={
            'emberShopperId': shopper_ref,
            'trailSku': item_sku,
            'cartQty': int(qty_held),
            'emberAddedAt': _now_iso(),
        }
    )
    snapshot = read_cart(shopper_ref)
    return {
        'outcome': 'placed',
        'itemSku': item_sku,
        'displayName': line['displayName'],
        'cartQty': int(qty_held),
        'lineCount': snapshot['lineCount'],
        'grandTotal': snapshot['grandTotal'],
    }


def remove_from_cart(shopper_ref: str, item_sku: str) -> dict:
    resp = _cart().get_item(Key={'emberShopperId': shopper_ref, 'trailSku': item_sku})
    if 'Item' not in resp:
        return {'outcome': 'error', 'detail': f'No cart line for itemSku {item_sku}'}

    meta = get_catalog_line(item_sku)
    display_name = meta['displayName'] if meta else item_sku
    _cart().delete_item(Key={'emberShopperId': shopper_ref, 'trailSku': item_sku})
    snapshot = read_cart(shopper_ref)
    return {
        'outcome': 'removed',
        'itemSku': item_sku,
        'displayName': display_name,
        'lineCount': snapshot['lineCount'],
        'grandTotal': snapshot['grandTotal'],
    }


def clear_cart(shopper_ref: str) -> dict:
    resp = _cart().query(KeyConditionExpression=Key('emberShopperId').eq(shopper_ref))
    removed = 0
    with _cart().batch_writer() as batch:
        for row in resp.get('Items', []):
            batch.delete_item(Key={'emberShopperId': shopper_ref, 'trailSku': row['trailSku']})
            removed += 1
    snapshot = read_cart(shopper_ref)
    return {
        'outcome': 'cleared',
        'removedCount': removed,
        'lineCount': snapshot['lineCount'],
        'grandTotal': snapshot['grandTotal'],
    }


def read_cart(shopper_ref: str) -> dict:
    resp = _cart().query(KeyConditionExpression=Key('emberShopperId').eq(shopper_ref))
    lines = []
    for row in resp.get('Items', []):
        meta = get_catalog_line(row['trailSku'])
        if not meta:
            continue
        qty = int(row['cartQty'])
        unit = meta['unitPrice']
        lines.append(
            {
                'itemSku': row['trailSku'],
                'displayName': meta['displayName'],
                'unitPrice': unit,
                'thumbUrl': meta.get('thumbUrl', ''),
                'cartQty': qty,
                'lineTotal': round(unit * qty, 2),
            }
        )

    line_count = sum(l['cartQty'] for l in lines)
    grand_total = round(sum(l['lineTotal'] for l in lines), 2)
    return {'lines': lines, 'lineCount': line_count, 'grandTotal': grand_total}


def open_support_case(shopper_ref: str, case_title: str, case_body: str, linked_order_ref=None) -> dict:
    resp = _cases().query(KeyConditionExpression=Key('emberShopperId').eq(shopper_ref))
    for row in resp.get('Items', []):
        if (
            row.get('ticketTitle') == case_title
            and row.get('ticketBody') == case_body
            and row.get('ticketState') == 'open'
        ):
            return {'outcome': 'exists', 'caseRef': row['supportTicketRef']}

    case_ref = 'CS-' + uuid.uuid4().hex[:8].upper()
    _cases().put_item(
        Item={
            'emberShopperId': shopper_ref,
            'supportTicketRef': case_ref,
            'ticketTitle': case_title,
            'ticketBody': case_body,
            'ticketState': 'open',
            'linkedOrderRef': linked_order_ref or '',
            'emberOpenedAt': _now_iso(),
        }
    )
    return {'outcome': 'opened', 'caseRef': case_ref}
