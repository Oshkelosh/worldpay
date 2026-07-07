# Worldpay (`worldpay`)

Accept payments via Worldpay.

## Overview

| | |
|---|---|
| Addon ID | `worldpay` |
| Category | payment |
| Version | 1.0.0 |
| Category guide | [../README.md](../README.md) |

Only **one** payment addon can be active at a time.

## Enable and configure

1. Install this package under `app/addons/payments/worldpay/`
2. Open **Admin → Payments → Worldpay** at `/admin/payments/worldpay`
3. Enter credentials and enable **Enable this payment processor**

## Configuration schema

| Field | Type | Description |
|-------|------|-------------|
| `username` | secret | Worldpay API username |
| `password` | secret | Worldpay API password |
| `webhook_secret` | secret | Webhook signing secret |
| `merchant_entity` | string | Merchant entity ID (optional) |
| `return_url` | string | Redirect after payment |

Secrets are stored in `addon_configs`, not in `.env`.

## Routes

### Public API

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/payments/worldpay/checkout` | Start checkout (optional; prefer generic order checkout) |
| POST | `/api/v1/payments/worldpay/webhook` | PSP webhook endpoint |

### Admin

| Method | Path | Description |
|--------|------|-------------|
| GET | `/admin/payments/worldpay` | Config form |
| POST | `/admin/payments/worldpay/save` | Save config |

## Core integration

- **Storefront checkout:** `POST /api/v1/orders/{order_id}/checkout` → `PaymentAddon.create_payment()` → redirect URL
- **Webhook:** `POST /api/v1/payments/worldpay/webhook` → `parse_webhook()` → core `process_payment_webhook()`
- **Amounts:** smallest currency unit (cents)

## Provider setup

Register webhook URL (replace `{PUBLIC_APP_URL}` with your public base URL):

```
{PUBLIC_APP_URL}/api/v1/payments/worldpay/webhook
```

Webhook signature header: **`signature (default)`**

1. Configure Access Worldpay credentials in your Worldpay account.
2. Register the webhook URL for payment status notifications.

## Package layout

```
worldpay/
├── README.md
├── addon.py
├── routes.py
└── templates/
```

## See also

- [Payment addon development](../README.md)
- [Oshkelosh addon guide](../../README.md)
