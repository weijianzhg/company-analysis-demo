# Alpha Vantage MCP server

Six tools served over stateless streamable HTTP at `/mcp` on port 8000:

- `get_stock_quote`
- `get_company_overview`
- `get_income_statement`
- `get_balance_sheet`
- `get_cash_flow`
- `get_company_snapshot`

All tools require a ticker. Statement tools accept `period=annual|quarterly` and `limit=1..5`. A snapshot makes up to five upstream requests and calculates annual metrics. Start with the [AWS deployment guide](../README.md) or [local setup](../docs/local.md).

Read [server.py](mcp_server/server.py), [alpha_vantage.py](mcp_server/alpha_vantage.py), and [financials.py](mcp_server/financials.py) for the complete implementation. The server has no language model.

Live responses retain provider dates and retrieval timestamps. Requests are cached for 15 minutes per process. Partial results, provider refusals and missing values remain explicit. Fixture mode serves labeled synthetic IBM data only and is never selected automatically.

Annual growth requires comparable years and currencies. Balance-sheet and cash-flow metrics must match the income statement's period and currency. Free cash flow is `operatingCashflow - abs(capitalExpenditures)`; liabilities/equity is not labeled as debt/equity. Provider trailing and forward P/E remain separate from the calculated latest-price/trailing-EPS ratio.

Derived from [bedrock-agent-blueprint](https://github.com/weijianzhg/bedrock-agent-blueprint/tree/c65654ff433f8e9cbc8b916a3a579497a93537dc), under the MIT license.
