from datetime import date

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from .forms import BrokerForm, TransactionForm
from .models import Broker, Transaction, TRANSACTION_ASSET_MAP
from .utils import compute_nisa_usage, compute_portfolio


@login_required
def dashboard(request):
    summary = compute_portfolio(request.user)
    nisa = compute_nisa_usage(request.user)
    recent_txns = (
        Transaction.objects.filter(owner=request.user)
        .select_related("company", "broker")[:10]
    )
    return render(request, "portfolio/dashboard.html", {
        "summary": summary,
        "nisa": nisa,
        "recent_txns": recent_txns,
        "today_year": date.today().year,
    })


# ── Transactions ──────────────────────────────────────────────────────────────

@login_required
def transaction_list(request):
    qs = Transaction.objects.filter(owner=request.user).select_related("company", "broker")

    txn_type = request.GET.get("type", "")
    broker_id = request.GET.get("broker", "")
    account = request.GET.get("account", "")
    date_from = request.GET.get("from", "")
    date_to = request.GET.get("to", "")

    if txn_type:
        qs = qs.filter(transaction_type=txn_type)
    if broker_id:
        qs = qs.filter(broker_id=broker_id)
    if account:
        qs = qs.filter(account_type=account)
    if date_from:
        qs = qs.filter(date__gte=date_from)
    if date_to:
        qs = qs.filter(date__lte=date_to)

    brokers = Broker.objects.filter(owner=request.user)
    return render(request, "portfolio/transaction_list.html", {
        "transactions": qs,
        "brokers": brokers,
        "txn_type": txn_type,
        "broker_id": broker_id,
        "account": account,
        "date_from": date_from,
        "date_to": date_to,
    })


@login_required
def transaction_create(request):
    initial = {}
    clone_pk = request.GET.get("clone")
    if clone_pk:
        try:
            src = Transaction.objects.get(pk=clone_pk, owner=request.user)
            initial = {
                "date":             date.today().isoformat(),
                "transaction_type": src.transaction_type,
                "account_type":     src.account_type,
                "broker":           src.broker,
                "stock_code":       src.company.stock_code if src.company else src.symbol,
                "quantity":         src.quantity,
                "price":            src.price,
                "fees":             src.fees,
                "taxes":            src.taxes,
                "amount":           src.amount,
                "note":             src.note,
            }
        except Transaction.DoesNotExist:
            pass

    if request.method == "POST":
        form = TransactionForm(request.POST, user=request.user)
        if form.is_valid():
            txn = form.save(commit=False)
            txn.owner = request.user
            txn.company = form.cleaned_data.get("_company")
            txn.asset_type = TRANSACTION_ASSET_MAP.get(txn.transaction_type, "cash")
            if txn.transaction_type in ("buy", "sell"):
                txn.amount = None
            else:
                txn.quantity = None
                txn.price = None
            txn.save()
            return redirect("portfolio:transaction_list")
    else:
        form = TransactionForm(user=request.user, initial=initial)
    return render(request, "portfolio/transaction_form.html", {
        "form": form,
        "action": "create",
        "is_clone": bool(initial),
    })


@login_required
def transaction_edit(request, pk):
    txn = get_object_or_404(Transaction, pk=pk, owner=request.user)
    if request.method == "POST":
        form = TransactionForm(request.POST, instance=txn, user=request.user)
        if form.is_valid():
            t = form.save(commit=False)
            t.company = form.cleaned_data.get("_company") or txn.company
            t.asset_type = TRANSACTION_ASSET_MAP.get(t.transaction_type, "cash")
            if t.transaction_type in ("buy", "sell"):
                t.amount = None
            else:
                t.quantity = None
                t.price = None
            t.save()
            return redirect("portfolio:transaction_list")
    else:
        form = TransactionForm(instance=txn, user=request.user)
    return render(request, "portfolio/transaction_form.html", {"form": form, "txn": txn, "action": "edit"})


@login_required
def transaction_delete(request, pk):
    txn = get_object_or_404(Transaction, pk=pk, owner=request.user)
    if request.method == "POST":
        txn.delete()
        return redirect("portfolio:transaction_list")
    return render(request, "portfolio/transaction_confirm_delete.html", {"txn": txn})


# ── Brokers ───────────────────────────────────────────────────────────────────

@login_required
def broker_list(request):
    brokers = Broker.objects.filter(owner=request.user)
    return render(request, "portfolio/broker_list.html", {"brokers": brokers})


@login_required
def broker_create(request):
    if request.method == "POST":
        form = BrokerForm(request.POST)
        if form.is_valid():
            b = form.save(commit=False)
            b.owner = request.user
            b.save()
            return redirect("portfolio:broker_list")
    else:
        form = BrokerForm()
    return render(request, "portfolio/broker_form.html", {"form": form, "action": "create"})


@login_required
def broker_edit(request, pk):
    broker = get_object_or_404(Broker, pk=pk, owner=request.user)
    if request.method == "POST":
        form = BrokerForm(request.POST, instance=broker)
        if form.is_valid():
            form.save()
            return redirect("portfolio:broker_list")
    else:
        form = BrokerForm(instance=broker)
    return render(request, "portfolio/broker_form.html", {"form": form, "broker": broker, "action": "edit"})


@login_required
def broker_delete(request, pk):
    broker = get_object_or_404(Broker, pk=pk, owner=request.user)
    if request.method == "POST":
        broker.delete()
        return redirect("portfolio:broker_list")
    return render(request, "portfolio/broker_form.html", {"form": BrokerForm(instance=broker), "broker": broker, "action": "delete"})
