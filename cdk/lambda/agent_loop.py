"""Bedrock Converse tool-calling loop — custom orchestration in Lambda."""

from bedrock_client import GEN_MODEL_ID, runtime
from tool_registry import TOOL_CONFIG, WRITE_TOOLS, dispatch

SYSTEM_PROMPT = (
    'You are Converse Commerce, a friendly gift-store assistant. '
    'When a shopper wants products, call find_products with dept_label for the category '
    '(Apple, Samsung, Ebooks, Gift Cards, Accessories, Smart Home) plus any price limit. '
    'For brand accessories (Samsung accessories, Apple chargers), use dept_label Accessories '
    'and put the brand in keywords. '
    'Recommend only returned catalog lines. '
    'The UI renders listings as cards, so keep replies short — highlight one or two picks. '
    'For policy questions, call lookup_policies and answer only from returned excerpts. '
    'Write plain friendly prose — no markdown blockquotes and no docRef in the reply; the UI lists sources below. '
    'If lookup_policies returns kb_pending or no excerpts, say you lack that information and offer open_support_case. '
    'When the shopper asks to remove or empty cart items, call read_cart first to resolve itemSku. '
    'Before place_in_cart, remove_from_cart, clear_cart, or open_support_case, confirm details. '
    'Write tools need confirmWrites=true on the next request. Keep replies concise.'
)


def _text_of(message: dict) -> str:
    return ''.join(block['text'] for block in message['content'] if 'text' in block)


def _tool_result_outcome(messages: list, assistant_idx: int, tool_use_id: str) -> dict | None:
    for msg in messages[assistant_idx + 1 :]:
        if msg.get('role') != 'user':
            break
        for block in msg.get('content', []):
            tool_result = block.get('toolResult')
            if not tool_result or tool_result.get('toolUseId') != tool_use_id:
                continue
            for part in tool_result.get('content', []):
                payload = part.get('json') or {}
                result = payload.get('result')
                if isinstance(result, dict):
                    return result
    return None


def _find_pending_writes(messages: list) -> list[dict]:
    pending = []
    for idx, msg in enumerate(messages):
        if msg.get('role') != 'assistant':
            continue
        for block in msg.get('content', []):
            tool_use = block.get('toolUse')
            if not tool_use:
                continue
            name = tool_use['name']
            if name not in WRITE_TOOLS:
                continue
            outcome = _tool_result_outcome(messages, idx, tool_use['toolUseId'])
            if isinstance(outcome, dict) and outcome.get('outcome') == 'confirmation_required':
                pending.append(
                    {
                        'name': name,
                        'input': dict(tool_use.get('input') or {}),
                        'tool_use_id': tool_use['toolUseId'],
                    }
                )
    return pending


def _patch_tool_result(messages: list, tool_use_id: str, result: dict) -> None:
    for msg in messages:
        if msg.get('role') != 'user':
            continue
        for block in msg.get('content', []):
            tool_result = block.get('toolResult')
            if tool_result and tool_result.get('toolUseId') == tool_use_id:
                tool_result['content'] = [{'json': {'result': result}}]
                return


def _execute_write(name: str, tool_input: dict, shopper_ref: str) -> dict:
    payload = dict(tool_input)
    if name in {'place_in_cart', 'remove_from_cart', 'clear_cart', 'open_support_case', 'read_cart'}:
        payload['shopper_ref'] = shopper_ref
    return dispatch(name, payload)


def _apply_confirmed_writes(messages: list, shopper_ref: str, tool_trace: list) -> list[dict]:
    executed = []
    for pending in _find_pending_writes(messages):
        result = _execute_write(pending['name'], pending['input'], shopper_ref)
        _patch_tool_result(messages, pending['tool_use_id'], result)
        entry = {
            'name': pending['name'],
            'input': pending['input'],
            'phase': 'executed',
            'result': result,
        }
        tool_trace.append(entry)
        executed.append(entry)
    return executed


def run_converse_loop(
    utterance: str,
    transcript=None,
    shopper_ref: str = 'demo-shopper',
    confirm_writes: bool = False,
    max_turns: int = 5,
):
    messages = list(transcript or [])
    tool_trace = []

    if confirm_writes:
        _apply_confirmed_writes(messages, shopper_ref, tool_trace)

    messages.append({'role': 'user', 'content': [{'text': utterance}]})

    for _ in range(max_turns):
        resp = runtime.converse(
            modelId=GEN_MODEL_ID,
            system=[{'text': SYSTEM_PROMPT}],
            messages=messages,
            toolConfig=TOOL_CONFIG,
            inferenceConfig={'maxTokens': 800, 'temperature': 0.3},
        )
        assistant_msg = resp['output']['message']
        messages.append(assistant_msg)

        if resp['stopReason'] != 'tool_use':
            return {
                'reply': _text_of(assistant_msg),
                'toolTrace': tool_trace,
                'transcript': messages,
            }

        tool_result_blocks = []
        for block in assistant_msg['content']:
            if 'toolUse' not in block:
                continue
            tu = block['toolUse']
            name, tool_input = tu['name'], dict(tu.get('input') or {})

            if name in WRITE_TOOLS and not confirm_writes:
                result = {'outcome': 'confirmation_required', 'action': name, 'details': tool_input}
                tool_trace.append({'name': name, 'input': tool_input, 'phase': 'awaiting_confirmation'})
            else:
                result = _execute_write(name, tool_input, shopper_ref)
                tool_trace.append({'name': name, 'input': tu['input'], 'phase': 'executed', 'result': result})

            tool_result_blocks.append(
                {'toolResult': {'toolUseId': tu['toolUseId'], 'content': [{'json': {'result': result}}]}}
            )
        messages.append({'role': 'user', 'content': tool_result_blocks})

    return {
        'reply': '(stopped: too many tool turns)',
        'toolTrace': tool_trace,
        'transcript': messages,
    }
