"""
Lumx HTTP client — thin synchronous wrapper around httpx.

All methods raise LumxError on non-2xx responses (the upstream status code and
response body are included in the message so callers can surface a useful
error instead of a bare "400 Bad Request").
"""
import httpx

from app.config import settings


class LumxError(RuntimeError):
    """Raised when the Lumx API returns a non-2xx response."""

    def __init__(self, status_code: int, body: str, method: str, path: str) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(f"Lumx {method} {path} -> {status_code}: {body[:400]}")


def _check(response: httpx.Response, method: str, path: str) -> dict:
    if response.status_code >= 400:
        raise LumxError(response.status_code, response.text, method, path)
    if not response.content:
        return {}
    return response.json()


class LumxClient:
    def __init__(self) -> None:
        self.base_url = settings.LUMX_BASE_URL
        self._headers = {
            "Authorization": f"Bearer {settings.LUMX_API_KEY}",
            "Content-Type":  "application/json",
        }

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.base_url,
            headers=self._headers,
            timeout=30.0,
        )

    # ── HTTP verbs ────────────────────────────────────────────────────────────

    def post(
        self,
        path: str,
        data: dict,
        idempotency_key: str | None = None,
    ) -> dict:
        extra_headers: dict[str, str] = {}
        if idempotency_key:
            extra_headers["Idempotency-Key"] = idempotency_key
        with self._client() as client:
            response = client.post(path, json=data, headers=extra_headers)
            return _check(response, "POST", path)

    def get(self, path: str, params: dict | None = None) -> dict:
        with self._client() as client:
            response = client.get(path, params=params or {})
            return _check(response, "GET", path)

    def patch(self, path: str, data: dict) -> dict:
        with self._client() as client:
            response = client.patch(path, json=data)
            return _check(response, "PATCH", path)

    def delete(self, path: str) -> dict | None:
        with self._client() as client:
            response = client.delete(path)
            _check(response, "DELETE", path)
            return response.json() if response.content else None

    # ── Convenience wrappers ──────────────────────────────────────────────────

    def create_customer(self, payload: dict, idempotency_key: str) -> dict:
        return self.post("/customers", payload, idempotency_key=idempotency_key)

    def get_customer(self, customer_id: str) -> dict:
        return self.get(f"/customers/{customer_id}")

    def create_destination(
        self,
        customer_id: str,
        payload: dict,
        idempotency_key: str,
    ) -> dict:
        # Lumx expects the customer on the body, not in the path:
        # POST /destinations  { "customerId": ..., "rail": ..., ... }
        return self.post(
            "/destinations",
            payload,
            idempotency_key=idempotency_key,
        )

    def create_offramp(self, payload: dict, idempotency_key: str) -> dict:
        return self.post(
            "/transactions/off-ramp",
            payload,
            idempotency_key=idempotency_key,
        )

    def create_onramp(self, payload: dict, idempotency_key: str) -> dict:
        return self.post(
            "/transactions/on-ramp",
            payload,
            idempotency_key=idempotency_key,
        )

    def get_transaction(self, tx_id: str) -> dict:
        return self.get(f"/transactions/{tx_id}")

    def lock_exchange_rate(self, payload: dict) -> dict:
        return self.post("/exchange-rates", payload)

    def patch_customer_info(self, customer_id: str, payload: dict) -> dict:
        return self.patch(
            f"/customers/{customer_id}/additional-information",
            payload,
        )


# Module-level singleton — import this everywhere
lumx = LumxClient()
