"""Bedrock Converse tool specs and dispatch for commerce-converse-lab."""

from dynamo_store import (
    clear_cart,
    find_products,
    open_support_case,
    place_in_cart,
    read_cart,
    remove_from_cart,
)
from policy_retrieval import lookup_policies

TOOL_CONFIG = {
    'tools': [
        {
            'toolSpec': {
                'name': 'find_products',
                'description': (
                    'Search the gift catalog. For category requests (Apple, Samsung, ebooks, '
                    'gift cards, accessories, smart home), set dept_label to that category. '
                    'For brand accessories (e.g. Samsung accessories), use dept_label Accessories '
                    'with the brand in keywords — not dept_label Samsung. '
                    'Also supports price range, stock filter, and keywords.'
                ),
                'inputSchema': {
                    'json': {
                        'type': 'object',
                        'properties': {
                            'dept_label': {
                                'type': 'string',
                                'description': (
                                    "Department filter: 'Apple', 'Samsung', 'Ebooks', 'Gift Cards', "
                                    "'Accessories', 'Smart Home'. Prefer for category gifts."
                                ),
                            },
                            'min_price': {'type': 'number', 'description': 'Minimum unit price USD.'},
                            'max_price': {'type': 'number', 'description': 'Maximum unit price USD.'},
                            'in_stock_only': {
                                'type': 'boolean',
                                'description': 'Only lines with qtyAvailable > 0. Default true.',
                            },
                            'keywords': {
                                'type': 'string',
                                'description': (
                                    'Optional extra terms matched against title, blurb, and department.'
                                ),
                            },
                        },
                    }
                },
            }
        },
        {
            'toolSpec': {
                'name': 'place_in_cart',
                'description': (
                    'Place a catalog line in the shopper cart. Mutates state — only after explicit confirmation.'
                ),
                'inputSchema': {
                    'json': {
                        'type': 'object',
                        'properties': {
                            'item_sku': {'type': 'string', 'description': "Catalog key, e.g. 'APPL-001'."},
                            'qty_held': {'type': 'integer', 'description': 'Quantity to hold. Default 1.'},
                        },
                        'required': ['item_sku'],
                    }
                },
            }
        },
        {
            'toolSpec': {
                'name': 'read_cart',
                'description': (
                    'Read the shopper current cart lines (itemSku, displayName, cartQty, lineTotal). '
                    'Call before remove_from_cart when resolving which item to remove.'
                ),
                'inputSchema': {
                    'json': {
                        'type': 'object',
                        'properties': {},
                    }
                },
            }
        },
        {
            'toolSpec': {
                'name': 'remove_from_cart',
                'description': (
                    'Remove one line from the shopper cart by itemSku. Mutates state — confirm first.'
                ),
                'inputSchema': {
                    'json': {
                        'type': 'object',
                        'properties': {
                            'item_sku': {'type': 'string', 'description': "Catalog key, e.g. 'SAMS-004'."},
                        },
                        'required': ['item_sku'],
                    }
                },
            }
        },
        {
            'toolSpec': {
                'name': 'clear_cart',
                'description': (
                    'Remove all lines from the shopper cart. Mutates state — confirm first.'
                ),
                'inputSchema': {
                    'json': {
                        'type': 'object',
                        'properties': {},
                    }
                },
            }
        },
        {
            'toolSpec': {
                'name': 'open_support_case',
                'description': (
                    'Open a human support case when policy lookup cannot help. Confirm with shopper first.'
                ),
                'inputSchema': {
                    'json': {
                        'type': 'object',
                        'properties': {
                            'case_title': {'type': 'string', 'description': 'Short case title.'},
                            'case_body': {'type': 'string', 'description': 'Full case description.'},
                            'linked_order_ref': {
                                'type': 'string',
                                'description': 'Optional order reference if relevant.',
                            },
                        },
                        'required': ['case_title', 'case_body'],
                    }
                },
            }
        },
        {
            'toolSpec': {
                'name': 'lookup_policies',
                'description': (
                    'Look up store policies and FAQs (shipping, returns, warranty). '
                    'Answer only from returned excerpts and cite docRef + sectionLabel.'
                ),
                'inputSchema': {
                    'json': {
                        'type': 'object',
                        'properties': {
                            'question': {'type': 'string', 'description': 'Policy question to look up.'},
                        },
                        'required': ['question'],
                    }
                },
            }
        },
    ]
}

READ_TOOLS = {'find_products', 'lookup_policies', 'read_cart'}
WRITE_TOOLS = {'place_in_cart', 'remove_from_cart', 'clear_cart', 'open_support_case'}

_IMPLEMENTATIONS = {
    'find_products': find_products,
    'read_cart': read_cart,
    'place_in_cart': place_in_cart,
    'remove_from_cart': remove_from_cart,
    'clear_cart': clear_cart,
    'open_support_case': open_support_case,
    'lookup_policies': lookup_policies,
}


def dispatch(tool_name: str, tool_input: dict) -> dict | list:
    impl = _IMPLEMENTATIONS.get(tool_name)
    if impl is None:
        raise ValueError(f'unknown tool: {tool_name}')
    return impl(**tool_input)
