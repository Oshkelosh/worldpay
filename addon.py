"""
Worldpay payment integration.

Supports checkout payments via Access Worldpay and webhooks.
"""

from __future__ import annotations

import base64
from typing import Any, Dict, List

import httpx
from fastapi import APIRouter
from pydantic import BaseModel, Field, SecretStr

from typing import Mapping

from app.addons.payments.base import PaymentAddon
from app.addons.payments.helpers import (
    create_payment_error,
    effective_redirect_url,
    extract_order_id,
    mock_checkout,
    verify_paid_via_refetch,
)
from schemas.payment import PaymentWebhookOutcome
from app.addons.log import info, warning
from app.addons.config_serialization import dump_addon_config

_API_BASE = "https://try.access.worldpay.com"


class WorldpayConfig(BaseModel):
    username: SecretStr = Field(default=..., description="Worldpay API username")
    password: SecretStr = Field(default=..., description="Worldpay API password")
    webhook_secret: SecretStr = Field(default=..., description="Webhook signing secret")
    merchant_entity: str = Field(default="", description="Worldpay merchant entity ID")
    return_url: str = Field(
        default="",
        description="Optional override for success redirect (leave blank to use Site URL)",
    )

    @classmethod
    def config_model(cls):
        return cls


class WorldpayAddon(PaymentAddon):
    addon_id: str = "worldpay"
    addon_name: str = "Worldpay"
    addon_description: str = "Accept payments via Worldpay."
    addon_category: str = "payment"
    version: str = "1.0.0"
    is_enabled: bool = False

    _config: Dict[str, Any] | None = None
    _username: str | None = None
    _password: str | None = None
    _webhook_secret: str | None = None
    _merchant_entity: str = ""
    _return_url: str = ""

    @classmethod
    def config_schema(cls):
        return WorldpayConfig

    async def initialize(self, config: dict) -> None:
        validated = self.config_schema()(**config)
        self._config = dump_addon_config(validated)
        self._username = validated.username.get_secret_value()
        self._password = validated.password.get_secret_value()
        self._webhook_secret = validated.webhook_secret.get_secret_value()
        self._merchant_entity = validated.merchant_entity
        self._return_url = validated.return_url
        self.is_enabled = True
        info("Worldpay", "Initialized")

    async def validate_config(self, config: dict) -> None:
        from app.core.exceptions import ValidationError

        validated = self.config_schema()(**config)
        username = validated.username.get_secret_value()
        password = validated.password.get_secret_value()
        if not username or not password:
            return
        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        headers = {
            "Authorization": f"Basic {token}",
            "Content-Type": "application/vnd.worldpay.payments-v7+json",
            "Accept": "application/vnd.worldpay.payments-v7+json",
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(f"{_API_BASE}/payment_pages", headers=headers, json={})
        if resp.status_code == 401:
            raise ValidationError(message="Invalid API credentials — check your credentials")
        if resp.status_code == 403:
            raise ValidationError(
                message="Credentials are valid but missing required permissions: payments:create"
            )
        if resp.status_code >= 500:
            raise ValidationError(message="Worldpay rejected the API credentials")

    async def shutdown(self) -> None:
        self._username = None
        self._password = None
        self._webhook_secret = None
        self.is_enabled = False

    def _auth_headers(self) -> dict[str, str]:
        token = base64.b64encode(
            f"{self._username}:{self._password}".encode()
        ).decode()
        return {
            "Authorization": f"Basic {token}",
            "Content-Type": "application/vnd.worldpay.payments-v7+json",
            "Accept": "application/vnd.worldpay.payments-v7+json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self._username or not self._password:
            raise RuntimeError("Worldpay credentials not configured")

        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.request(
                method,
                f"{_API_BASE}{path}",
                headers=self._auth_headers(),
                json=json_body,
            )
            resp.raise_for_status()
            if resp.content:
                return resp.json()
            return {}

    async def create_payment(
        self,
        amount: int,
        currency: str,
        order_id: str,
        customer_email: str,
        *,
        return_url: str | None = None,
        cancel_url: str | None = None,
    ) -> Dict[str, Any]:
        if not self._username:
            return mock_checkout("worldpay", order_id, amount, currency)

        effective_return = effective_redirect_url(
            self._return_url, fallback=return_url or ""
        )

        body: dict[str, Any] = {
            "transactionReference": order_id,
            "merchant": {"entity": self._merchant_entity or "default"},
            "instruction": {
                "value": {"amount": amount, "currency": currency.upper()},
                "narrative": {"line1": f"Order {order_id}"},
            },
            "customer": {"email": customer_email} if customer_email else {},
            "resultURLs": {"successURL": effective_return},
            "metadata": {"order_id": order_id},
        }

        try:
            data = await self._request("POST", "/payment_pages", json_body=body)
            return {
                "success": True,
                "payment_id": data.get("paymentId", data.get("transactionReference", "")),
                "session_id": data.get("paymentId", order_id),
                "url": data.get("url", data.get("_links", {}).get("paymentPage", {}).get("href", "")),
                "order_id": order_id,
            }
        except Exception as exc:
            warning("Worldpay", "create_payment error: {}", exc)
            return create_payment_error("worldpay", exc, order_id)

    async def confirm_payment(self, payment_id: str) -> Dict[str, Any]:
        status = await self.get_payment_status(payment_id)
        if status.get("status") == "error":
            return {"success": False, "error": status.get("detail", "Unknown error")}
        return {
            "success": status.get("status") in ("authorized", "captured", "success"),
            "payment_id": payment_id,
            "status": status.get("status", "unknown"),
            "amount": status.get("amount", 0),
        }

    async def refund_payment(self, payment_id: str, amount: int) -> Dict[str, Any]:
        if not self._username:
            return {"success": False, "error": "Worldpay credentials not configured"}

        body = {
            "value": {"amount": amount, "currency": "USD"},
            "reference": f"refund_{payment_id}",
        }
        try:
            data = await self._request(
                "POST",
                f"/payments/{payment_id}/refunds",
                json_body=body,
            )
            return {
                "success": True,
                "refund_id": data.get("refundId", data.get("id", "")),
                "amount": amount,
                "status": data.get("status", "success"),
            }
        except Exception as exc:
            warning("Worldpay", "refund_payment({}) error: {}", payment_id, exc)
            return {"success": False, "error": str(exc)}

    async def get_payment_status(self, payment_id: str) -> Dict[str, Any]:
        if not self._username:
            return {"payment_id": payment_id, "status": "error", "detail": "Not configured"}

        try:
            data = await self._request("GET", f"/payments/{payment_id}")
            value = data.get("value", data.get("amount", {}))
            amount = value.get("amount", 0) if isinstance(value, dict) else 0
            return {
                "payment_id": payment_id,
                "status": data.get("status", data.get("lastEvent", "unknown")).lower(),
                "amount": int(amount),
                "currency": (
                    value.get("currency", "usd").lower()
                    if isinstance(value, dict)
                    else "usd"
                ),
            }
        except Exception as exc:
            warning("Worldpay", "get_payment_status({}) error: {}", payment_id, exc)
            return {"payment_id": payment_id, "status": "error", "detail": str(exc)}

    async def verify_webhook(
        self,
        *,
        headers: Mapping[str, str],
        body: bytes,
    ) -> bool:
        """Verify a Worldpay webhook by re-fetching the referenced payment."""
        del headers
        import json

        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            return False
        outcome = await self.parse_webhook(payload, "")
        if not outcome.mark_paid:
            return outcome.handled
        return await verify_paid_via_refetch(
            self.get_payment_status,
            outcome.payment_id or "",
            {"authorized", "captured", "success"},
        )

    async def parse_webhook(
        self, payload: Dict[str, Any], signature: str
    ) -> PaymentWebhookOutcome:
        try:
            event_type = payload.get("eventType", payload.get("type", ""))
            event_data = payload.get("eventDetails", payload.get("data", payload))
            event_id = str(payload.get("eventId", payload.get("id", "")))
            info("Worldpay", "Webhook received: {}", event_type)

            if event_type in ("payment.authorized", "payment.captured", "payment.success"):
                order_id = extract_order_id(event_data.get("metadata"))
                if order_id is None:
                    ref = event_data.get("transactionReference")
                    if ref is not None:
                        try:
                            order_id = int(ref)
                        except (TypeError, ValueError):
                            order_id = None
                payment_id = event_data.get("paymentId") or event_data.get("id")
                return PaymentWebhookOutcome(
                    handled=True,
                    event_id=event_id,
                    event_type=event_type,
                    mark_paid=order_id is not None,
                    order_id=order_id,
                    payment_id=str(payment_id) if payment_id else None,
                )

            return PaymentWebhookOutcome(
                handled=True,
                event_id=event_id,
                event_type=event_type,
            )
        except Exception as exc:
            warning("Worldpay", "parse_webhook error: {}", exc)
            return PaymentWebhookOutcome(handled=False, error=str(exc))

    def get_routers(self) -> List[APIRouter]:
        from app.addons.payments.worldpay.routes import api_router

        return [api_router]

    def get_admin_routes(self) -> List[APIRouter]:
        from app.addons.payments.worldpay.routes import admin_router

        return [admin_router]

    def get_admin_templates(self) -> str:
        from pathlib import Path

        return str(Path(__file__).resolve().parent / "templates")

    def get_admin_static(self) -> str:
        from pathlib import Path

        return str(Path(__file__).resolve().parent / "static")
