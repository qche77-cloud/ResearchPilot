"""Thread-local research traces with no prompts, responses, credentials or error bodies."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from functools import wraps
import json
import os
import re
import time
import uuid

_STATE = ContextVar('research_trace_state', default=None)
_PARENT = ContextVar('research_trace_parent', default=None)


@contextmanager
def trace_scope(state):
    token = _STATE.set(state)
    parent = _PARENT.set(None) if token.old_value is not state else None
    try:
        yield
    finally:
        if parent is not None:
            _PARENT.reset(parent)
        _STATE.reset(token)


@contextmanager
def span(kind, operation, **metadata):
    state = _STATE.get()
    if state is None:
        yield {}
        return
    record = {'call_id': uuid.uuid4().hex, 'parent_id': _PARENT.get(), 'run_id': state.run_id,
              'stage': state.current_stage, 'kind': kind, 'operation': operation,
              'mode': 'offline_fixture' if os.getenv('RESEARCHPILOT_OFFLINE_TEST') == '1' else 'live',
              'started_at': datetime.now(timezone.utc).isoformat(), 'status': 'running', **metadata}
    state.diagnostics.setdefault('trace', []).append(record)
    parent = _PARENT.set(record['call_id'])
    start = time.perf_counter()
    try:
        yield record
        record['status'] = 'success'
    except BaseException as exc:
        record['status'] = 'error'
        record['error_type'] = type(exc).__name__
        raise
    finally:
        record['elapsed_ms'] = round((time.perf_counter() - start) * 1000, 3)
        record['ended_at'] = datetime.now(timezone.utc).isoformat()
        _PARENT.reset(parent)
        state.diagnostics['trace_summary'] = trace_summary(state.diagnostics['trace'])


def traced_tool(operation):
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            with span('tool', operation):
                return function(*args, **kwargs)
        return wrapped
    return decorate


def traced_state(operation):
    def decorate(function):
        @wraps(function)
        def wrapped(state, *args, **kwargs):
            with trace_scope(state), span('step', operation):
                return function(state, *args, **kwargs)
        return wrapped
    return decorate


def _usage(data):
    raw = data.get('usage') if isinstance(data, dict) else None
    if not isinstance(raw, dict):
        return None
    usage = {}
    for name in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
        value = raw.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        usage[name] = value
    details = raw.get('prompt_tokens_details')
    cached = details.get('cached_tokens') if isinstance(details, dict) else None
    if cached is not None and (not isinstance(cached, int) or isinstance(cached, bool) or not 0 <= cached <= usage['prompt_tokens']):
        return None
    if usage['total_tokens'] != usage['prompt_tokens'] + usage['completion_tokens']:
        return None
    usage['cached_tokens'] = cached
    return usage


def estimate_cost(model, usage, pricing=None):
    """Rates are explicit USD/million-token configuration, never guessed defaults."""
    if not usage:
        return None
    try:
        table = pricing if pricing is not None else json.loads(os.getenv('RESEARCHPILOT_MODEL_PRICING_JSON', '{}'))
        rate = table[model]
        if not isinstance(rate.get('as_of'), str) or not rate['as_of']:
            return None
        date.fromisoformat(rate['as_of'])
        cached = usage['cached_tokens']
        if cached is None:
            return None
        input_rate = Decimal(str(rate['input_per_million']))
        output_rate = Decimal(str(rate['output_per_million']))
        cached_rate = Decimal(str(rate['cached_input_per_million'])) if cached else input_rate
        if any(not r.is_finite() or r < 0 for r in (input_rate, output_rate, cached_rate)):
            return None
        cost = ((usage['prompt_tokens'] - cached) * input_rate + cached * cached_rate
                + usage['completion_tokens'] * output_rate) / Decimal(1_000_000)
        return {'amount': str(cost), 'currency': 'USD', 'rate_as_of': rate['as_of'], 'basis': 'configured_token_rates'}
    except (KeyError, TypeError, ValueError, InvalidOperation, AttributeError):
        return None


def request_json(request, *, timeout, opener, operation, kind='model'):
    """Preserve the caller's urllib transport so existing mocks/config keep working."""
    payload = json.loads(request.data) if request.data else {}
    model = payload.get('model') if kind == 'model' else None
    routing = 'default_model'
    if kind == 'model':
        model, routing = resolve_model(operation, model)
        if model != payload.get('model'):
            payload['model'] = model
            request.data = json.dumps(payload).encode('utf-8')
        if operation == 'agent.decide' and os.getenv('RESEARCHPILOT_STRICT_OUTPUTS') == '1':
            payload['response_format'] = {'type': 'json_schema', 'json_schema': {
                'name': 'research_decision', 'strict': True, 'schema': {
                    'type': 'object', 'additionalProperties': False,
                    'properties': {'action': {'type': 'string', 'enum': ['search', 'finish']},
                                   'task': {'type': ['string', 'null']}, 'query': {'type': ['string', 'null']},
                                   'reason': {'type': 'string'}},
                    'required': ['action', 'task', 'query', 'reason']}}}
            request.data = json.dumps(payload).encode('utf-8')
    with span(kind, operation, **({'model': model, 'routing': routing} if model else {})) as record:
        record['usage'] = None
        record['estimated_cost'] = None
        with opener(request, timeout=timeout) as response:
            data = json.loads(response.read())
        if kind == 'model':
            record['usage'] = _usage(data)
            record['usage_source'] = ('fixture_response' if os.getenv('RESEARCHPILOT_OFFLINE_TEST') == '1'
                                      else 'provider_response') if record['usage'] is not None else 'unknown'
            record['estimated_cost'] = estimate_cost(model, record['usage'])
        return data


def resolve_model(operation, default_model):
    """Opt-in operation/role routes; no automatic model upgrade or extra calls."""
    try:
        routes = json.loads(os.getenv('RESEARCHPILOT_MODEL_ROUTES_JSON', '{}'))
        if not isinstance(routes, dict):
            return default_model, 'invalid_config_fallback'
        target = routes.get(operation, routes.get(operation.split('.')[0]))
        if target is None:
            return default_model, 'default_model'
        if not isinstance(target, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}', target):
            return default_model, 'invalid_route_fallback'
        return target, 'explicit_role_route'
    except (ValueError, TypeError):
        return default_model, 'invalid_config_fallback'


def trace_summary(records):
    models = [r for r in records if r['kind'] == 'model']
    known = [r for r in models if r.get('usage') is not None]
    costs = [r['estimated_cost'] for r in models if r.get('estimated_cost') is not None]
    return {'model_calls': len(models), 'tool_calls': sum(r['kind'] == 'tool' for r in records),
            'errors': sum(r['status'] == 'error' for r in records),
            'known_total_tokens': sum(r['usage']['total_tokens'] for r in known),
            'unknown_usage_calls': len(models) - len(known),
            'known_cost_subtotal_usd': str(sum((Decimal(c['amount']) for c in costs), Decimal(0))),
            'unknown_model_cost_calls': len(models) - len(costs),
            'total_model_cost_usd': str(sum((Decimal(c['amount']) for c in costs), Decimal(0))) if len(costs) == len(models) else None,
            'tool_cost': 'unknown'}
