"""
Payments (payments/razorpay.py).

    POST /payments/order   {purpose: "analysis" | "expert"} -> Razorpay order for Checkout

Redemption happens where the paid thing is used: the upload routes
(analysis) and POST /expert-review (expert check).
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.payments import razorpay

router = APIRouter(prefix="/payments")


class OrderRequest(BaseModel):
    purpose: str


@router.post("/order", status_code=201)
def create_order(request: OrderRequest):
    try:
        return razorpay.create_order(request.purpose)
    except razorpay.PaymentError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
