def action(state: dict) -> dict:
    tick      = state["tick"]
    my        = state["my_bot"]
    cash      = my["cash"]
    total     = my["total_value"]
    portfolio = my["portfolio"]
    stocks    = {s["symbol"]: s for s in state["market"]["stocks"]}
    news      = state["market"]["news"]

    # 뉴스 호재 종목 매수
    bullish = ["계약", "실적", "파트너십", "출시", "[G]"]
    for item in news:
        sym = item["symbol"]
        if any(k in item["headline"] for k in bullish):
            stock = stocks.get(sym, {})
            if stock.get("delisted") or sym in portfolio:
                continue
            price = stock["price"]
            qty = int(cash * 0.15 / (price * 1.002))
            if qty > 0 and cash >= price * qty * 1.002:
                return {"action": "BUY", "symbol": sym, "quantity": qty}

    # 손실 -15% 이하 손절
    for sym, pos in portfolio.items():
        if pos["pnl_pct"] <= -15:
            return {"action": "SELL", "symbol": sym, "quantity": pos["quantity"]}

    # 수익 +20% 이상 절반 익절
    for sym, pos in portfolio.items():
        if pos["pnl_pct"] >= 20:
            qty = pos["quantity"] // 2
            if qty > 0:
                return {"action": "SELL", "symbol": sym, "quantity": qty}

    return {"action": "HOLD"}
