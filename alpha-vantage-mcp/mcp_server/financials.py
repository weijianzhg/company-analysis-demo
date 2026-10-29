"""Deterministic annual metrics, with explicit units, dates and formulas."""

from datetime import date
from decimal import Decimal, InvalidOperation


def number(value):
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except InvalidOperation:
        return None


def comparable_years(current, previous):
    """Only compare adjacent annual reports in the same known currency."""
    try:
        gap = (date.fromisoformat(current.get("fiscalDateEnding", ""))
               - date.fromisoformat(previous.get("fiscalDateEnding", ""))).days
        currency = current.get("reportedCurrency")
        return 330 <= gap <= 400 and currency not in (None, "", "unknown") and previous.get("reportedCurrency") == currency
    except (ValueError, TypeError):
        return False


def calculate_metrics(data: dict) -> tuple[dict, list[str]]:
    metrics = {}
    notes = ["Quotes are the latest available trading-day values, not guaranteed real time.",
             "Overview EPS and P/E are provider snapshots; do not substitute annual EPS for trailing EPS."]

    def add(name, value, unit, period, formula):
        metrics[name] = {"value": round(float(value), 4) if value is not None else None,
                         "unit": unit, "period": period, "formula": formula}

    def ratio(numerator, denominator, scale=1):
        if numerator is None or denominator is None or denominator <= 0:
            return None
        return numerator / denominator * scale

    def reports(function):
        return sorted(data.get(function, {}).get("annualReports", []),
                      key=lambda row: row.get("fiscalDateEnding", ""), reverse=True)

    overview = data.get("OVERVIEW", {})
    quote = data.get("GLOBAL_QUOTE", {}).get("Global Quote", {})
    price, eps = number(quote.get("05. price")), number(overview.get("EPS"))
    add("price", price, overview.get("Currency", "unknown"), quote.get("07. latest trading day"),
        "GLOBAL_QUOTE: 05. price")
    for name, field in (("trailing_pe", "PERatio"), ("forward_pe", "ForwardPE")):
        value = number(overview.get(field))
        add(name, value if value is not None and value > 0 else None, "multiple",
            "provider overview snapshot", f"OVERVIEW: {field}")
    add("price_to_eps", ratio(price, eps), "multiple", "latest quote / overview trailing EPS",
        "latest available price / positive trailing EPS; dates may differ from provider P/E")
    if not overview:
        notes.append("Company overview unavailable: P/E and trailing EPS are unavailable; do not estimate them from annual net income.")
    income = reports("INCOME_STATEMENT")
    if not income:
        notes.append("Annual income statements unavailable; annual performance metrics omitted.")
        return metrics, notes
    current = income[0]
    period, currency = current.get("fiscalDateEnding"), current.get("reportedCurrency", "unknown")
    revenue = number(current.get("totalRevenue"))
    for name, field in (("revenue", "totalRevenue"), ("gross_profit", "grossProfit"),
                        ("operating_income", "operatingIncome"), ("net_income", "netIncome")):
        add(name, number(current.get(field)), currency, period, f"INCOME_STATEMENT: {field}")
    for name, field in (("gross_margin_pct", "grossProfit"),
                        ("operating_margin_pct", "operatingIncome"), ("net_margin_pct", "netIncome")):
        add(name, ratio(number(current.get(field)), revenue, 100), "percent", period,
            f"{field} / positive totalRevenue × 100")

    previous = income[1] if len(income) > 1 else {}
    comparable = comparable_years(current, previous)
    for name, field in (("revenue_growth_pct", "totalRevenue"), ("net_income_growth_pct", "netIncome")):
        latest, prior = number(current.get(field)), number(previous.get(field))
        growth = ratio(latest - prior, prior, 100) if comparable and latest is not None and prior is not None else None
        add(name, growth, "percent", period, f"({field} - prior annual {field}) / positive prior {field} × 100")
    if not comparable:
        notes.append("Year-over-year growth needs comparable annual periods in the same currency.")

    def matching(function):
        row = next((r for r in reports(function) if r.get("fiscalDateEnding") == period
                    and r.get("reportedCurrency") == currency != "unknown"), {})
        if not row:
            notes.append(f"No {function} annual report matching {period} and {currency}; related metrics unavailable.")
        return row

    balance, cash = matching("BALANCE_SHEET"), matching("CASH_FLOW")
    add("current_ratio", ratio(number(balance.get("totalCurrentAssets")),
                               number(balance.get("totalCurrentLiabilities"))),
        "multiple", period, "totalCurrentAssets / positive totalCurrentLiabilities")
    add("liabilities_to_equity", ratio(number(balance.get("totalLiabilities")),
                                       number(balance.get("totalShareholderEquity"))),
        "multiple", period, "totalLiabilities / positive totalShareholderEquity; not debt-to-equity")
    operating_cash, capex = number(cash.get("operatingCashflow")), number(cash.get("capitalExpenditures"))
    add("operating_cash_flow", operating_cash, currency, period, "CASH_FLOW: operatingCashflow")
    free_cash = operating_cash - abs(capex) if operating_cash is not None and capex is not None else None
    add("free_cash_flow", free_cash,
        currency, period, "operatingCashflow - abs(capitalExpenditures); simple cash-flow proxy")
    prior_cash = next((r for r in reports("CASH_FLOW") if comparable_years(cash, r)), {})
    prior_operating, prior_capex = number(prior_cash.get("operatingCashflow")), number(prior_cash.get("capitalExpenditures"))
    prior_free = prior_operating - abs(prior_capex) if prior_operating is not None and prior_capex is not None else None
    for name, latest, prior in (("operating_cash_flow_growth_pct", operating_cash, prior_operating),
                                ("free_cash_flow_growth_pct", free_cash, prior_free)):
        growth = ratio(latest - prior, prior, 100) if latest is not None and prior is not None else None
        add(name, growth, "percent", period, "(current - prior comparable annual cash flow) / positive prior cash flow × 100")
    if not prior_cash:
        notes.append("Cash-flow growth needs comparable annual reports in the same currency.")
    notes.append("Null means unavailable or not meaningful (including zero/negative ratio denominators).")
    return metrics, notes
