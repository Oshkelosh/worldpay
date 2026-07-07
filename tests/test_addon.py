"""Minimal unit tests for the worldpay addon."""

from app.addons.payments.worldpay.addon import WorldpayAddon


def test_addon_identity():
    assert WorldpayAddon.addon_id == "worldpay"
    assert WorldpayAddon.addon_category == "payment"
