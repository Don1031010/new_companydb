from collections import defaultdict
from datetime import date as date_cls
from decimal import Decimal


def compute_nisa_usage(user):
    """Returns NISA枠 usage for the current year."""
    from django.db.models import F, Sum, ExpressionWrapper, DecimalField
    from .models import Transaction, NISA_ANNUAL_LIMITS

    year = date_cls.today().year
    result = {}
    for account_type, limit in NISA_ANNUAL_LIMITS.items():
        used = (
            Transaction.objects.filter(
                owner=user,
                account_type=account_type,
                transaction_type="buy",
                date__year=year,
            ).aggregate(
                total=Sum(
                    ExpressionWrapper(F("quantity") * F("price"), output_field=DecimalField())
                )
            )["total"]
            or Decimal("0")
        )
        result[account_type] = {
            "used":      used,
            "limit":     Decimal(str(limit)),
            "remaining": max(Decimal(str(limit)) - used, Decimal("0")),
            "pct":       min(int(used / limit * 100), 100) if limit else 0,
        }
    return result


def compute_portfolio(user):
    """
    Single-pass portfolio computation.
    Processes all transactions in date order and returns positions,
    realized P&L by month, dividends, and summary totals.
    """
    from .models import Transaction

    txns = list(
        Transaction.objects.filter(owner=user)
        .select_related("company", "broker")
        .order_by("date", "created_at")
    )

    # stock_code/symbol → {qty, total_cost, company, symbol}
    holdings = {}
    realized_monthly = defaultdict(Decimal)   # "YYYY-MM" → realized P&L
    total_dividends = Decimal("0")

    for txn in txns:
        if txn.transaction_type not in ("buy", "sell"):
            if txn.transaction_type == "dividend":
                net = (txn.amount or Decimal("0")) - txn.taxes
                total_dividends += net
            continue

        key = txn.company.stock_code if txn.company else txn.symbol
        if not key:
            continue

        if key not in holdings:
            holdings[key] = {
                "company":      txn.company,
                "symbol":       key,
                "qty":          Decimal("0"),
                "total_cost":   Decimal("0"),
                "account_type": txn.account_type,
            }
        h = holdings[key]

        if txn.transaction_type == "buy":
            cost = (txn.quantity or Decimal("0")) * (txn.price or Decimal("0")) + txn.fees + txn.taxes
            h["qty"] += txn.quantity or Decimal("0")
            h["total_cost"] += cost

        elif txn.transaction_type == "sell" and h["qty"] > 0:
            qty_sold = min(txn.quantity or Decimal("0"), h["qty"])
            avg_cost = h["total_cost"] / h["qty"]
            proceeds = qty_sold * (txn.price or Decimal("0")) - txn.fees - txn.taxes
            pnl = proceeds - avg_cost * qty_sold
            realized_monthly[txn.date.strftime("%Y-%m")] += pnl
            h["total_cost"] -= avg_cost * qty_sold
            h["qty"] -= qty_sold
            if h["qty"] < Decimal("0.0001"):
                h["qty"] = Decimal("0")
                h["total_cost"] = Decimal("0")

    # Build open positions list
    open_positions = []
    for h in holdings.values():
        if h["qty"] < Decimal("0.0001"):
            continue
        avg_cost = h["total_cost"] / h["qty"]
        company = h["company"]
        current_price = (
            Decimal(str(company.share_price)) if company and company.share_price else None
        )
        current_value = current_price * h["qty"] if current_price is not None else None
        unrealized_pnl = (current_value - h["total_cost"]) if current_value is not None else None
        unrealized_pnl_pct = (
            unrealized_pnl / h["total_cost"] * 100
            if unrealized_pnl is not None and h["total_cost"]
            else None
        )
        open_positions.append({
            "company":            company,
            "symbol":             h["symbol"],
            "quantity":           h["qty"],
            "avg_cost":           avg_cost,
            "total_cost":         h["total_cost"],
            "current_price":      current_price,
            "current_value":      current_value,
            "unrealized_pnl":     unrealized_pnl,
            "unrealized_pnl_pct": unrealized_pnl_pct,
            "account_type":       h["account_type"],
            "is_nisa":            h["account_type"] in ("nisa_growth", "nisa_tsumitate"),
        })

    open_positions.sort(key=lambda x: x["symbol"])

    total_cost      = sum(p["total_cost"] for p in open_positions)
    total_value     = sum(p["current_value"] for p in open_positions if p["current_value"] is not None)
    total_unrealized = sum(p["unrealized_pnl"] for p in open_positions if p["unrealized_pnl"] is not None)
    total_realized  = sum(realized_monthly.values())
    realized_monthly_sorted = dict(sorted(realized_monthly.items()))

    # Cumulative realized P&L series for chart
    cum = Decimal("0")
    cumulative_monthly = {}
    for month, val in realized_monthly_sorted.items():
        cum += val
        cumulative_monthly[month] = cum

    return {
        "positions":          open_positions,
        "total_cost":         total_cost,
        "total_value":        total_value,
        "unrealized_pnl":     total_unrealized,
        "realized_pnl":       total_realized,
        "dividends":          total_dividends,
        "total_pnl":          total_unrealized + total_realized + total_dividends,
        "realized_monthly":   realized_monthly_sorted,
        "cumulative_monthly": cumulative_monthly,
    }
