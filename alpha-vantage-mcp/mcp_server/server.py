"""Alpha Vantage tools, served using the blueprint's MCP runtime contract."""

import os
from typing import Literal

from mcp.server.mcpserver import MCPServer

from alpha_vantage import AlphaVantage, AlphaVantageError
from financials import calculate_metrics

mcp = MCPServer("alpha-vantage-financials")
api = AlphaVantage.from_environment()


@mcp.tool()
async def get_stock_quote(symbol: str) -> dict:
    """Get the latest available stock quote and its trading date, not a live tick."""
    return await api.fetch("GLOBAL_QUOTE", symbol)


@mcp.tool()
async def get_company_overview(symbol: str) -> dict:
    """Get company identity, currency, market cap, EPS, trailing P/E and forward P/E."""
    return await api.fetch("OVERVIEW", symbol)


async def statement(function: str, symbol: str, period: str, limit: int) -> dict:
    if not 1 <= limit <= 5:
        raise AlphaVantageError("limit must be between 1 and 5")
    response = await api.fetch(function, symbol)
    key = "annualReports" if period == "annual" else "quarterlyReports"
    response["data"] = {"symbol": response["symbol"], "period": period,
                        "reports": response["data"].get(key, [])[:limit]}
    return response


@mcp.tool()
async def get_income_statement(symbol: str, period: Literal["annual", "quarterly"] = "annual",
                               limit: int = 2) -> dict:
    """Get P&L: revenue, gross profit, operating income and net income by fiscal date."""
    return await statement("INCOME_STATEMENT", symbol, period, limit)


@mcp.tool()
async def get_balance_sheet(symbol: str, period: Literal["annual", "quarterly"] = "annual",
                            limit: int = 2) -> dict:
    """Get assets, liabilities, debt and equity by fiscal date."""
    return await statement("BALANCE_SHEET", symbol, period, limit)


@mcp.tool()
async def get_cash_flow(symbol: str, period: Literal["annual", "quarterly"] = "annual",
                        limit: int = 2) -> dict:
    """Get operating cash flow, capital expenditures and other cash flows by fiscal date."""
    return await statement("CASH_FLOW", symbol, period, limit)


@mcp.tool()
async def get_company_snapshot(symbol: str) -> dict:
    """Start here for company performance: quote, valuation, two annual P&Ls,
    balance sheets and cash flows, plus calculated growth, margins and ratios.
    Uses up to five Alpha Vantage requests, cached for 15 minutes. Partial data
    and provider errors are explicit; missing values are never treated as zero.
    """
    symbol = api.normalize_symbol(symbol)
    datasets, errors = {}, {}
    for function in ("GLOBAL_QUOTE", "OVERVIEW", "INCOME_STATEMENT", "BALANCE_SHEET", "CASH_FLOW"):
        try:
            response = await api.fetch(function, symbol)
            if "annualReports" in response["data"]:
                response["data"] = {"symbol": symbol,
                                    "annualReports": response["data"]["annualReports"][:2]}
            datasets[function] = response
        except AlphaVantageError as exc:
            errors[function] = str(exc)
    if not datasets:
        raise AlphaVantageError("No financial data available. " + "; ".join(sorted(set(errors.values()))))
    metrics, notes = calculate_metrics({name: value["data"] for name, value in datasets.items()})
    source = "Alpha Vantage" if api.mode == "live" else "Local synthetic fixture (Alpha Vantage schema)"
    return {"symbol": symbol, "source": source, "mode": api.mode,
            "status": "partial" if errors else "complete", "datasets": datasets,
            "metrics": metrics, "notes": notes, "errors": errors}


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host=os.environ.get("MCP_HOST", "127.0.0.1"),
            port=int(os.environ.get("MCP_PORT", "8000")), stateless_http=True)
