"""Invoked on deploy (CDK Trigger) to seed converse-catalog."""

from __future__ import annotations

import json
from pathlib import Path

from dynamo_store import seed_catalog_rows

DATA_FILE = Path(__file__).parent / 'data' / 'catalog.json'


def lambda_handler(event, context):
    rows = json.loads(DATA_FILE.read_text())
    count = seed_catalog_rows(rows)
    return {'seededLines': count, 'status': 'ok'}
