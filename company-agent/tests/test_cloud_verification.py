"""Accept missing valuation only; never turn arbitrary provider failures green."""

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('cloud_verification',
        Path(__file__).resolve().parents[2] / 'cloud/test_end_to_end.py')
verification = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verification)


@pytest.fixture
def partial_snapshot():
    metrics = {name: {'value': 1} for name in ('price', 'revenue', 'net_income', 'revenue_growth_pct',
               'net_margin_pct', 'free_cash_flow', 'free_cash_flow_growth_pct', 'current_ratio')}
    metrics.update({name: {'value': None} for name in ('trailing_pe', 'forward_pe', 'price_to_eps')})
    return {'mode': 'live', 'status': 'partial',
            'datasets': {name: {} for name in ('GLOBAL_QUOTE', 'INCOME_STATEMENT', 'BALANCE_SHEET', 'CASH_FLOW')},
            'metrics': metrics, 'errors': {'OVERVIEW': 'This is a premium endpoint'}}


def test_explicit_missing_overview_mode(partial_snapshot):
    verification.validate_snapshot(partial_snapshot, 'live', True)
    with pytest.raises(AssertionError):
        verification.validate_snapshot(partial_snapshot, 'live')


@pytest.mark.parametrize('missing', ['GLOBAL_QUOTE', 'INCOME_STATEMENT', 'BALANCE_SHEET', 'CASH_FLOW'])
def test_missing_overview_mode_does_not_hide_other_failures(partial_snapshot, missing):
    del partial_snapshot['datasets'][missing]
    partial_snapshot['errors'][missing] = 'Rate limit reached'
    with pytest.raises(AssertionError):
        verification.validate_snapshot(partial_snapshot, 'live', True)


def test_missing_overview_must_not_have_fabricated_pe(partial_snapshot):
    partial_snapshot['metrics']['trailing_pe']['value'] = 20
    with pytest.raises(AssertionError, match='trailing_pe must be unavailable'):
        verification.validate_snapshot(partial_snapshot, 'live', True)


def test_missing_performance_metric_still_fails(partial_snapshot):
    partial_snapshot['metrics']['free_cash_flow']['value'] = None
    with pytest.raises(AssertionError, match='free_cash_flow'):
        verification.validate_snapshot(partial_snapshot, 'live', True)


def test_agent_must_disclose_missing_pe_and_use_snapshot():
    response = {'result': 'P/E unavailable: overview requires premium access.',
                'tools_used': ['get_company_snapshot']}
    verification.validate_agent_response(response, True)
    with pytest.raises(AssertionError):
        verification.validate_agent_response(dict(response, result='P/E is 20.'), True)
    with pytest.raises(AssertionError):
        verification.validate_agent_response(dict(response, tools_used=[]), True)
