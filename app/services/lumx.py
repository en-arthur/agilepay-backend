"""
Lumx HTTP client — thin synchronous wrapper around httpx.

All methods raise httpx.HTTPStatusError on non-2xx responses,
which callers should catch and convert to appropriate HTTPExceptions.
"""
import httpx

from app.config import settings


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
            response.raise_for_status()
            return response.json()

    def get(self, path: str, params: dict | None = None) -> dict:
        with self._client() as client:
            response = client.get(path, params=params or {})
            response.raise_for_status()
            return response.json()

    def patch(self, path: str, data: dict) -> dict:
        with self._client() as client:
            response = client.patch(path, json=data)
            response.raise_for_status()
            return response.json()

    def delete(self, path: str) -> dict | None:
        with self._client() as client:
            response = client.delete(path)
            response.raise_for_status()
            if response.content:
                return response.json()
            return None

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
        return self.post(
            f"/customers/{customer_id}/destinations",
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
