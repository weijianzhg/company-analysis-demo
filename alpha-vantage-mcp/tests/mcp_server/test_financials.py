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
