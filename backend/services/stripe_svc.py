"""
HouseRadar — Stripe integration (test mode).

ENV vars:
  STRIPE_SECRET_KEY        sk_test_...
  STRIPE_PUBLISHABLE_KEY   pk_test_...   (esposto al frontend, opzionale)
  STRIPE_WEBHOOK_SECRET    whsec_...
  APP_BASE_URL             https://houseradar.it (success/cancel URLs)

I price_id vengono creati lazy al primo deploy se mancano,
e salvati in tabella app_config (key/value).
"""

import os
import sys
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import get_conn, _cur, _sql
from auth.dependencies import require_auth
from auth.users_db import (
    set_subscription, set_stripe_customer,
    find_user_by_stripe_customer, get_user_by_id,
)


STRIPE_SECRET     = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_PUB        = os.environ.get("STRIPE_PUBLISHABLE_KEY", "")
WEBHOOK_SECRET    = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
APP_BASE_URL      = os.environ.get("APP_BASE_URL", "https://houseradar.it").rstrip("/")
TRIAL_DAYS        = 14

router = APIRouter(prefix="/api/stripe", tags=["stripe"])


def _stripe():
    """Import lazy + guard se chiave mancante."""
    if not STRIPE_SECRET:
        raise HTTPException(status_code=503, detail="Stripe non configurato (STRIPE_SECRET_KEY mancante)")
    import stripe
    stripe.api_key = STRIPE_SECRET
    return stripe


# ─── app_config (key/value) ──────────────────────────────────────────────────

def _cfg_get(key: str) -> Optional[str]:
    conn = get_conn(); cur = _cur(conn)
    cur.execute(_sql("SELECT value FROM app_config WHERE key = ?"), (key,))
    row = cur.fetchone(); conn.close()
    if not row:
        return None
    return row[0] if not isinstance(row, dict) else row.get("value")


def _cfg_set(key: str, value: str):
    conn = get_conn(); cur = _cur(conn)
    cur.execute(_sql("DELETE FROM app_config WHERE key = ?"), (key,))
    cur.execute(_sql("INSERT INTO app_config (key, value) VALUES (?, ?)"), (key, value))
    conn.commit(); conn.close()


# ─── Lazy bootstrap prodotti/prezzi ──────────────────────────────────────────

PLANS = {
    "solo": {
        "product_name": "HouseRadar Solo",
        "monthly_amount": 19700,  # cents EUR
        "yearly_amount":  197000,
    },
    "agenzia": {
        "product_name": "HouseRadar Agenzia",
        "monthly_amount": 39700,
        "yearly_amount":  397000,
    },
}


def ensure_stripe_prices() -> dict:
    """
    Garantisce che esistano i 4 price_id (solo/agenzia × monthly/yearly).
    Ritorna la mappa { 'solo_monthly': 'price_xxx', ... }.
    Salva in app_config per non ricrearli ad ogni boot.
    """
    if not STRIPE_SECRET:
        return {}
    stripe = _stripe()
    out = {}
    for plan, cfg in PLANS.items():
        # Trova/crea Product
        product_id = _cfg_get(f"stripe_product_{plan}")
        if not product_id:
            try:
                prod = stripe.Product.create(name=cfg["product_name"])
                product_id = prod["id"]
                _cfg_set(f"stripe_product_{plan}", product_id)
            except Exception as e:
                print(f"[Stripe] errore Product {plan}: {e}")
                continue
        # Mensile + annuale
        for interval, amount_key in (("month", "monthly_amount"), ("year", "yearly_amount")):
            cfg_key = f"stripe_price_{plan}_{interval}"
            price_id = _cfg_get(cfg_key)
            if not price_id:
                try:
                    price = stripe.Price.create(
                        product=product_id,
                        unit_amount=cfg[amount_key],
                        currency="eur",
                        recurring={"interval": interval},
                    )
                    price_id = price["id"]
                    _cfg_set(cfg_key, price_id)
                except Exception as e:
                    print(f"[Stripe] errore Price {plan}/{interval}: {e}")
                    continue
            out[f"{plan}_{interval}"] = price_id
    return out


# ─── Routes ──────────────────────────────────────────────────────────────────

@router.post("/create-checkout-session")
async def create_checkout_session(request: Request, user=Depends(require_auth)):
    """
    Body JSON:
      { "plan": "solo"|"agenzia", "interval": "month"|"year" }
    OPPURE
      { "price_id": "price_xxx", "plan_name": "Solo" }   (compatibilità)
    """
    body = await request.json()
    stripe = _stripe()

    price_id = body.get("price_id")
    if not price_id:
        plan     = body.get("plan", "solo")
        interval = body.get("interval", "month")
        prices   = ensure_stripe_prices()
        price_id = prices.get(f"{plan}_{interval}")
        if not price_id:
            raise HTTPException(status_code=500, detail="Price Stripe non configurato")

    try:
        sess = stripe.checkout.Session.create(
            mode="subscription",
            payment_method_types=["card"],
            customer_email=user["email"],
            client_reference_id=str(user["id"]),
            line_items=[{"price": price_id, "quantity": 1}],
            subscription_data={"trial_period_days": TRIAL_DAYS,
                               "metadata": {"user_id": str(user["id"])}},
            success_url=f"{APP_BASE_URL}/app?welcome=1",
            cancel_url=f"{APP_BASE_URL}/pricing?canceled=1",
            metadata={"user_id": str(user["id"]),
                      "plan_name": body.get("plan_name") or body.get("plan", "")},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Stripe error: {e}")
    return {"checkout_url": sess["url"]}


@router.post("/customer-portal")
async def customer_portal(user=Depends(require_auth)):
    if not user.get("stripe_customer_id"):
        raise HTTPException(status_code=400, detail="Nessun abbonamento attivo")
    stripe = _stripe()
    try:
        portal = stripe.billing_portal.Session.create(
            customer=user["stripe_customer_id"],
            return_url=f"{APP_BASE_URL}/app",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Stripe error: {e}")
    return {"portal_url": portal["url"]}


@router.post("/webhook")
async def webhook(request: Request):
    payload = await request.body()
    sig     = request.headers.get("Stripe-Signature", "")
    stripe  = _stripe()

    try:
        event = stripe.Webhook.construct_event(payload, sig, WEBHOOK_SECRET) \
                if WEBHOOK_SECRET else stripe.Event.construct_from(
                    __import__("json").loads(payload), STRIPE_SECRET)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Webhook signature: {e}")

    typ = event["type"]
    obj = event["data"]["object"]
    print(f"[Stripe webhook] {typ}")

    try:
        if typ == "checkout.session.completed":
            user_id  = int((obj.get("metadata") or {}).get("user_id") or
                           obj.get("client_reference_id") or 0)
            cust_id  = obj.get("customer")
            sub_id   = obj.get("subscription")
            if user_id and cust_id:
                set_stripe_customer(user_id, cust_id)
            if user_id and sub_id:
                # Recupera sottoscrizione per trial_end / status
                sub = stripe.Subscription.retrieve(sub_id)
                set_subscription(
                    user_id,
                    subscription_id=sub_id,
                    status=sub.get("status") or "trialing",
                    trial_ends_at=_iso(sub.get("trial_end")),
                    customer_id=cust_id,
                )

        elif typ in ("customer.subscription.updated",
                     "customer.subscription.created"):
            cust_id = obj.get("customer")
            user = find_user_by_stripe_customer(cust_id) if cust_id else None
            if user:
                set_subscription(
                    user["id"],
                    subscription_id=obj.get("id"),
                    status=obj.get("status"),
                    trial_ends_at=_iso(obj.get("trial_end")),
                )

        elif typ == "customer.subscription.deleted":
            cust_id = obj.get("customer")
            user = find_user_by_stripe_customer(cust_id) if cust_id else None
            if user:
                set_subscription(user["id"], status="canceled")

        elif typ == "invoice.paid":
            cust_id = obj.get("customer")
            user = find_user_by_stripe_customer(cust_id) if cust_id else None
            if user:
                set_subscription(user["id"], status="active")

        elif typ == "invoice.payment_failed":
            cust_id = obj.get("customer")
            user = find_user_by_stripe_customer(cust_id) if cust_id else None
            if user:
                set_subscription(user["id"], status="past_due")
    except Exception as e:
        print(f"[Stripe webhook] handler error ({typ}): {e}")

    return JSONResponse({"received": True})


def _iso(ts) -> Optional[str]:
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
    except Exception:
        return None
