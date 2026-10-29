"""Financial edge cases where a plausible number would be misleading."""

from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'mcp_server'))
from financials import calculate_metrics, number


@pytest.fixture
def data():
    return json.loads((Path(__file__).resolve().parents[2] / 'mcp_server/fixtures/ibm.json').read_text())


@pytest.mark.parametrize('value', [None, 'None', 'N/A', '-', '', 'NaN', 'Infinity'])
def test_missing_values_are_not_zero(value):
    assert number(value) is None


def test_zero_and_negative_denominators_are_not_meaningful(data):
    data['OVERVIEW']['EPS'] = '-2'
    data['OVERVIEW']['PERatio'] = '0'
    data['INCOME_STATEMENT']['annualReports'][1]['netIncome'] = '-100'
    data['BALANCE_SHEET']['annualReports'][0]['totalShareholderEquity'] = '0'
    metrics, _ = calculate_metrics(data)
    for key in ('price_to_eps', 'trailing_pe', 'net_income_growth_pct', 'liabilities_to_equity'):
        assert metrics[key]['value'] is None


@pytest.mark.parametrize('field,value', [('fiscalDateEnding', '2023-12-31'), ('reportedCurrency', 'EUR')])
def test_growth_requires_comparable_years_and_currency(data, field, value):
    data['INCOME_STATEMENT']['annualReports'][1][field] = value
    metrics, notes = calculate_metrics(data)
    assert metrics['revenue_growth_pct']['value'] is None
    assert any('comparable' in note for note in notes)


@pytest.mark.parametrize('field,value', [('fiscalDateEnding', '2024-12-31'), ('reportedCurrency', 'EUR')])
def test_cash_flow_requires_matching_fiscal_period_and_currency(data, field, value):
    data['CASH_FLOW']['annualReports'][0][field] = value
    metrics, _ = calculate_metrics(data)
    assert metrics['free_cash_flow']['value'] is None


def test_capex_sign_and_missing_cash_flow(data):
    data['CASH_FLOW']['annualReports'][0]['capitalExpenditures'] = '-5000000000'
    metrics, _ = calculate_metrics(data)
    assert metrics['free_cash_flow']['value'] == 15_000_000_000
    data['CASH_FLOW']['annualReports'][0].pop('capitalExpenditures')
    metrics, _ = calculate_metrics(data)
    assert metrics['free_cash_flow']['value'] is None


def test_report_order_and_inputs_are_preserved(data):
    data['INCOME_STATEMENT']['annualReports'].reverse()
    original = deepcopy(data)
    metrics, _ = calculate_metrics(data)
    assert metrics['revenue']['period'] == '2025-12-31'
    assert metrics['revenue_growth_pct']['value'] == 10
    assert data == original


def test_missing_overview_keeps_pe_unavailable_and_preserves_statements(data):
    del data['OVERVIEW']
    metrics, notes = calculate_metrics(data)
    for name in ('trailing_pe', 'forward_pe', 'price_to_eps'):
        assert metrics[name]['value'] is None
    assert metrics['price']['unit'] == 'unknown'
    assert metrics['revenue_growth_pct']['value'] == 10
    assert any('P/E and trailing EPS are unavailable' in note for note in notes)


def test_cash_flow_trend_uses_comparable_free_cash_flow(data):
    # Regression: 12.102 billion is an increase from 11.760 billion.
    data['CASH_FLOW']['annualReports'] = [
        {'fiscalDateEnding': '2025-12-31', 'reportedCurrency': 'USD',
         'operatingCashflow': '13193000000', 'capitalExpenditures': '1091000000'},
        {'fiscalDateEnding': '2024-12-31', 'reportedCurrency': 'USD',
         'operatingCashflow': '13300000000', 'capitalExpenditures': '-1540000000'},
    ]
    metrics, _ = calculate_metrics(data)
    assert metrics['free_cash_flow']['value'] == 12_102_000_000
    assert metrics['free_cash_flow_growth_pct']['value'] == 2.9082
    assert metrics['operating_cash_flow_growth_pct']['value'] == -0.8045


@pytest.mark.parametrize('field,value', [
    ('fiscalDateEnding', '2023-12-31'), ('reportedCurrency', 'EUR'),
    ('operatingCashflow', '0'), ('operatingCashflow', None),
])
def test_cash_growth_rejects_incomparable_or_nonpositive_prior(data, field, value):
    data['CASH_FLOW']['annualReports'][1][field] = value
    metrics, _ = calculate_metrics(data)
    assert metrics['operating_cash_flow_growth_pct']['value'] is None
    assert metrics['free_cash_flow_growth_pct']['value'] is None
