"""Worldpay addon routes — thin delegates to shared payment route factory."""

from __future__ import annotations

from typing import Any

from app.addons.payments.shared_routes import build_payment_routers


def _parse_worldpay_config_form(form: Any) -> tuple[dict[str, Any], bool]:
    return (
        {
            "username": form.get("username", ""),
            "password": form.get("password", ""),
            "webhook_secret": form.get("webhook_secret", ""),
            "merchant_entity": form.get("merchant_entity", ""),
            "return_url": form.get("return_url", ""),
        },
        form.get("is_enabled") == "on",
    )


admin_router, api_router, jinja_env = build_payment_routers(
    "worldpay",
    template_name="worldpay_config.html",
    page_title="Worldpay Settings",
    secret_keys=("username", "password", "webhook_secret"),
    parse_config_form=_parse_worldpay_config_form,
)
