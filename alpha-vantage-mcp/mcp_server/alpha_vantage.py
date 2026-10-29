"""One small HTTP client: validation, bounded cache, and safe provider errors."""

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
import time

import boto3
import httpx2
from mcp.server.mcpserver.exceptions import ToolError

FUNCTIONS = {"GLOBAL_QUOTE", "OVERVIEW", "INCOME_STATEMENT", "BALANCE_SHEET", "CASH_FLOW"}
API_URL = "https://www.alphavantage.co/query"


class RedactApiKey(logging.Filter):
    """HTTPX logs full request URLs at INFO; Alpha Vantage keys are in the query."""

    def filter(self, record):
        record.msg = re.sub(r'([?&]apikey=)[^&\s"\']+', r'\1[REDACTED]', record.getMessage())
        record.args = ()
        return True


logging.getLogger("httpx2").addFilter(RedactApiKey())
logging.getLogger("httpcore2").setLevel(logging.WARNING)


class AlphaVantageError(ToolError):
    """A provider failure that is safe to show to an MCP caller."""


class AlphaVantage:
    def __init__(self, api_key: str = "", mode: str = "live", transport=None, request_interval: float = 0):
        if mode not in {"live", "fixture"}:
            raise ValueError("ALPHA_VANTAGE_MODE must be live or fixture")
        self.api_key, self.mode, self.transport = api_key, mode, transport
        if request_interval < 0:
            raise ValueError("Request interval must be nonnegative")
        self.request_interval, self.next_request_at = request_interval, 0
        self.cache = {}
        self.lock = asyncio.Lock()

    @classmethod
    def from_environment(cls):
        mode = os.environ.get("ALPHA_VANTAGE_MODE", "live")
        key = os.environ.get("ALPHA_VANTAGE_API_KEY", "")
        secret_arn = os.environ.get("ALPHA_VANTAGE_SECRET_ARN")
        if mode == "live" and secret_arn:
            # Only the ARN enters the runtime configuration or Terraform state.
            try:
                secret = boto3.client("secretsmanager", region_name=secret_arn.split(":")[3])
                key = secret.get_secret_value(SecretId=secret_arn)["SecretString"].strip()
            except Exception:
                raise AlphaVantageError("Cannot load the Alpha Vantage key from Secrets Manager") from None
        return cls(key, mode, request_interval=float(os.environ.get("ALPHA_VANTAGE_REQUEST_INTERVAL", "15")))

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        symbol = symbol.strip().upper()
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9.\-]{0,19}", symbol):
            raise AlphaVantageError("Use a stock ticker such as IBM, AAPL, or BRK.B")
        return symbol

    async def fetch(self, function: str, symbol: str) -> dict:
        symbol = self.normalize_symbol(symbol)
        if function not in FUNCTIONS:
            raise ValueError("Unsupported Alpha Vantage function")
        async with self.lock:
            cache_key = (function, symbol)
            cached = self.cache.get(cache_key)
            if cached and time.monotonic() - cached[0] < 900:
                result = deepcopy(cached[1])
                result["cached"] = True
                return result
            if self.mode == "live":
                delay = self.next_request_at - time.monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)
                self.next_request_at = time.monotonic() + self.request_interval
            data = await self._request(function, symbol)
            self._validate(data, function, symbol)
            source = "Alpha Vantage" if self.mode == "live" else "Local synthetic fixture (Alpha Vantage schema)"
            result = {"source": source, "mode": self.mode, "symbol": symbol,
                      "function": function, "retrieved_at": datetime.now(timezone.utc).isoformat(),
                      "cached": False, "data": data}
            if self.mode == "fixture":
                result["notice"] = "Synthetic IBM test data; not actual financial results or current prices."
            if len(self.cache) >= 128:
                self.cache.pop(next(iter(self.cache)))
            self.cache[cache_key] = (time.monotonic(), deepcopy(result))
            return result

    async def _request(self, function: str, symbol: str) -> dict:
        if self.mode == "fixture":
            if symbol != "IBM":
                raise AlphaVantageError("Fixture mode contains only synthetic IBM data")
            path = Path(__file__).parent / "fixtures" / "ibm.json"
            return json.loads(path.read_text())[function]
        if not self.api_key:
            raise AlphaVantageError("Set ALPHA_VANTAGE_API_KEY for live data; no fixture fallback is used")
        try:
            async with httpx2.AsyncClient(timeout=30, transport=self.transport) as client:
                response = await client.get(API_URL, params={"function": function,
                                           "symbol": symbol, "apikey": self.api_key})
                response.raise_for_status()
                return response.json()
        except httpx2.HTTPStatusError as exc:
            raise AlphaVantageError(f"Alpha Vantage returned HTTP {exc.response.status_code}") from None
        except httpx2.RequestError:
            raise AlphaVantageError("Alpha Vantage request failed or timed out") from None
        except ValueError:
            raise AlphaVantageError("Alpha Vantage returned invalid JSON") from None

    def _validate(self, data, function: str, symbol: str):
        if not isinstance(data, dict):
            raise AlphaVantageError("Alpha Vantage returned an unexpected response")
        # HTTP 200 errors can contain a key or a URL with credentials.
        for field in ("Note", "Information", "Error Message"):
            if field in data:
                message = str(data[field])
                if self.api_key:
                    message = message.replace(self.api_key, "[REDACTED]")
                message = re.sub(r'(?i)([?&]apikey=)[^&\s"\']+', r'\1[REDACTED]', message)
                raise AlphaVantageError(f"Alpha Vantage {field}: {message[:500]}")
        if function == "GLOBAL_QUOTE":
            quote = data.get("Global Quote", {})
            returned_symbol = quote.get("01. symbol") if isinstance(quote, dict) else None
            available = bool(quote)
        elif function == "OVERVIEW":
            returned_symbol, available = data.get("Symbol"), bool(data.get("Symbol"))
        else:
            returned_symbol = data.get("symbol")
            available = any(isinstance(data.get(key), list) and data[key]
                            for key in ("annualReports", "quarterlyReports"))
        if not available:
            raise AlphaVantageError(f"No {function} data available for {symbol}")
        if not isinstance(returned_symbol, str) or returned_symbol.upper() != symbol:
            raise AlphaVantageError("Alpha Vantage returned data for an unexpected ticker")
