"""Tests for DynamoDB store helpers (mocked boto3)."""

import os
import sys
from decimal import Decimal
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


@patch('dynamo_store.get_catalog_line')
@patch('dynamo_store._cart')
def test_place_in_cart_puts_line(mock_cart_fn, mock_get_line):
    import dynamo_store as ds

    mock_get_line.return_value = {
        'itemSku': 'APPL-001',
        'displayName': 'AirPods Pro',
        'unitPrice': 32.0,
        'qtyAvailable': 10,
        'blurb': '',
        'thumbUrl': '',
    }
    table = MagicMock()
    with patch.object(ds, '_cart', return_value=table), patch.object(
        ds, 'read_cart', return_value={'lines': [], 'lineCount': 1, 'grandTotal': 32.0}
    ):
        out = ds.place_in_cart('shopper-1', 'APPL-001', 1)
    assert out['outcome'] == 'placed'
    table.put_item.assert_called_once()


@patch('dynamo_store.read_cart')
@patch('dynamo_store.get_catalog_line')
@patch('dynamo_store._cart')
def test_remove_from_cart_deletes_line(mock_cart_fn, mock_get_line, mock_read_cart):
    import dynamo_store as ds

    mock_get_line.return_value = {'displayName': 'AirPods Pro'}
    mock_read_cart.return_value = {'lines': [], 'lineCount': 0, 'grandTotal': 0.0}
    table = MagicMock()
    table.get_item.return_value = {'Item': {'emberShopperId': 'shopper-1', 'trailSku': 'APPL-001'}}
    mock_cart_fn.return_value = table
    out = ds.remove_from_cart('shopper-1', 'APPL-001')
    assert out['outcome'] == 'removed'
    assert out['displayName'] == 'AirPods Pro'
    table.delete_item.assert_called_once_with(
        Key={'emberShopperId': 'shopper-1', 'trailSku': 'APPL-001'}
    )


@patch('dynamo_store.read_cart')
@patch('dynamo_store._cart')
def test_clear_cart_deletes_all_lines(mock_cart_fn, mock_read_cart):
    import dynamo_store as ds

    mock_read_cart.return_value = {'lines': [], 'lineCount': 0, 'grandTotal': 0.0}
    table = MagicMock()
    table.query.return_value = {
        'Items': [
            {'emberShopperId': 'shopper-1', 'trailSku': 'A'},
            {'emberShopperId': 'shopper-1', 'trailSku': 'B'},
        ]
    }
    batch = MagicMock()
    batch.__enter__ = MagicMock(return_value=batch)
    batch.__exit__ = MagicMock(return_value=False)
    table.batch_writer.return_value = batch
    mock_cart_fn.return_value = table
    out = ds.clear_cart('shopper-1')
    assert out['outcome'] == 'cleared'
    assert out['removedCount'] == 2
    assert batch.delete_item.call_count == 2


@patch('dynamo_store._catalog')
def test_find_products_tech_keyword_matches_department(mock_catalog_fn):
    import dynamo_store as ds

    table = MagicMock()
    table.scan.return_value = {
        'Items': [
            {
                'trailSku': 'ACCS-001',
                'giftTitle': 'Anker 735 GaN USB-C Charger (65W)',
                'trailDept': 'Accessories',
                'trailDeptKey': 'accessories',
                'emberPrice': Decimal('39.99'),
                'stockQty': 120,
                'giftBlurb': 'Charges laptop, phone, and tablet.',
                'thumbUrl': '',
            },
            {
                'trailSku': 'SAMS-004',
                'giftTitle': 'Galaxy SmartTag2 (4-Pack)',
                'trailDept': 'Samsung',
                'trailDeptKey': 'samsung',
                'emberPrice': Decimal('39.99'),
                'stockQty': 88,
                'giftBlurb': 'Bluetooth trackers for keys and bags.',
                'thumbUrl': '',
            },
        ]
    }
    mock_catalog_fn.return_value = table
    rows = ds.find_products(keywords='tech', max_price=50)
    assert len(rows) == 2
    assert {r['itemSku'] for r in rows} == {'ACCS-001', 'SAMS-004'}


def test_dept_hint_from_keywords():
    import dynamo_store as ds

    assert ds._dept_hint_from_keywords('tech gift for Marcus') == 'Accessories'
    assert ds._dept_hint_from_keywords('apple gift card') == 'Apple'
    assert ds._dept_hint_from_keywords('samsung galaxy buds') == 'Samsung'
    assert ds._dept_hint_from_keywords('samsung accessories for Marcus') == 'Accessories'
    assert ds._dept_hint_from_keywords('ebook gift ideas') == 'Ebooks'
    assert ds._dept_hint_from_keywords('digital gift card') == 'Gift Cards'


@patch('dynamo_store._scan_catalog')
def test_find_products_samsung_accessories_merges_brand_and_accessory_rows(mock_scan):
    import dynamo_store as ds
    from decimal import Decimal

    mock_scan.side_effect = [
        [
            {
                'trailSku': 'ACCS-003',
                'giftTitle': 'Spigen Ultra Hybrid Case — Galaxy S24',
                'trailDept': 'Accessories',
                'trailDeptKey': 'accessories',
                'emberPrice': Decimal('24.99'),
                'stockQty': 95,
                'giftBlurb': 'Clear back shows Samsung color while protecting corners.',
            },
            {
                'trailSku': 'ACCS-002',
                'giftTitle': 'Belkin 3-in-1 MagSafe Charging Stand',
                'trailDept': 'Accessories',
                'trailDeptKey': 'accessories',
                'emberPrice': Decimal('149.99'),
                'stockQty': 25,
                'giftBlurb': 'Samsung phones use Qi pad on the base.',
            },
        ],
        [
            {
                'trailSku': 'SAMS-004',
                'giftTitle': 'Galaxy SmartTag2 (4-Pack)',
                'trailDept': 'Samsung',
                'trailDeptKey': 'samsung',
                'emberPrice': Decimal('39.99'),
                'stockQty': 88,
                'giftBlurb': 'Bluetooth trackers with SmartThings Find.',
            },
            {
                'trailSku': 'SAMS-005',
                'giftTitle': 'Samsung Gift Card — $25 Digital',
                'trailDept': 'Samsung',
                'trailDeptKey': 'samsung',
                'emberPrice': Decimal('25.0'),
                'stockQty': 999,
                'giftBlurb': 'Instant email code for samsung.com accessories.',
            },
            {
                'trailSku': 'SAMS-002',
                'giftTitle': 'Galaxy Tab A9+ (Wi-Fi, 64GB)',
                'trailDept': 'Samsung',
                'trailDeptKey': 'samsung',
                'emberPrice': Decimal('219.99'),
                'stockQty': 22,
                'giftBlurb': '11-inch display tablet.',
            },
        ],
    ]

    rows = ds.find_products(dept_label='Samsung', keywords='accessories for Marcus')
    assert mock_scan.call_count == 2
    assert {r['itemSku'] for r in rows} == {'ACCS-003', 'ACCS-002', 'SAMS-004'}
    assert rows[0]['itemSku'] == 'ACCS-003'


@patch('dynamo_store._scan_catalog')
def test_find_products_accessories_dept_with_samsung_keywords(mock_scan):
    import dynamo_store as ds
    from decimal import Decimal

    mock_scan.side_effect = [
        [
            {
                'trailSku': 'ACCS-001',
                'giftTitle': 'Anker 735 GaN USB-C Charger (65W)',
                'trailDept': 'Accessories',
                'trailDeptKey': 'accessories',
                'emberPrice': Decimal('39.99'),
                'stockQty': 120,
                'giftBlurb': 'Works with Apple and Samsung USB-C devices.',
            },
        ],
        [
            {
                'trailSku': 'SAMS-001',
                'giftTitle': 'Galaxy Buds FE',
                'trailDept': 'Samsung',
                'trailDeptKey': 'samsung',
                'emberPrice': Decimal('99.99'),
                'stockQty': 55,
                'giftBlurb': 'Active noise reduction and rich sound.',
            },
        ],
    ]

    rows = ds.find_products(dept_label='Accessories', keywords='Samsung')
    assert mock_scan.call_count == 2
    assert {r['itemSku'] for r in rows} == {'ACCS-001', 'SAMS-001'}


@patch('dynamo_store._catalog')
def test_find_products_keyword_match_is_case_insensitive(mock_catalog_fn):
    import dynamo_store as ds
    from decimal import Decimal

    table = MagicMock()
    table.scan.return_value = {
        'Items': [
            {
                'trailSku': 'ACCS-003',
                'giftTitle': 'Spigen Ultra Hybrid Case — Galaxy S24',
                'trailDept': 'Accessories',
                'trailDeptKey': 'accessories',
                'emberPrice': Decimal('24.99'),
                'stockQty': 95,
                'giftBlurb': 'Clear back shows Samsung color while protecting corners.',
            },
        ]
    }
    mock_catalog_fn.return_value = table
    rows = ds.find_products(dept_label='Accessories', keywords='samsung')
    assert len(rows) == 1
    assert rows[0]['itemSku'] == 'ACCS-003'


@patch('dynamo_store._catalog')
def test_find_products_returns_catalog_view(mock_catalog_fn):
    import dynamo_store as ds

    table = MagicMock()
    table.scan.return_value = {
        'Items': [
            {
                'trailSku': 'B-2',
                'giftTitle': 'Lamp',
                'trailDept': 'Apple',
                'emberPrice': Decimal('30'),
                'stockQty': 5,
                'giftBlurb': 'lamp',
                'thumbUrl': '',
            },
        ]
    }
    mock_catalog_fn.return_value = table
    rows = ds.find_products(limit=5)
    assert len(rows) == 1
    assert rows[0]['itemSku'] == 'B-2'
    assert rows[0]['unitPrice'] == 30.0
