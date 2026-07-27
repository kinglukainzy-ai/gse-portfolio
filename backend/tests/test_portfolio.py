from portfolio import compute_position, _shares_as_of, _price_as_of, _cost_basis_as_of


def test_compute_position_single_buy():
    txs = [{"side": "buy", "shares": 100, "price": 2.50}]
    pos = compute_position(txs)
    assert pos["shares_held"] == 100
    assert pos["avg_cost"] == 2.50
    assert pos["cost_basis"] == 250.0
    assert pos["realized_pl"] == 0.0


def test_compute_position_two_buys_weighted_avg():
    txs = [
        {"side": "buy", "shares": 100, "price": 2.00},
        {"side": "buy", "shares": 100, "price": 4.00},
    ]
    pos = compute_position(txs)
    assert pos["shares_held"] == 200
    assert pos["avg_cost"] == 3.00


def test_compute_position_buy_then_sell():
    txs = [
        {"side": "buy", "shares": 100, "price": 2.00},
        {"side": "sell", "shares": 50, "price": 3.00},
    ]
    pos = compute_position(txs)
    assert pos["shares_held"] == 50
    assert pos["avg_cost"] == 2.00
    assert pos["realized_pl"] == 50.0  # (3.00 - 2.00) * 50


def test_compute_position_sell_to_zero_resets():
    txs = [
        {"side": "buy", "shares": 100, "price": 2.00},
        {"side": "sell", "shares": 100, "price": 3.00},
    ]
    pos = compute_position(txs)
    assert pos["shares_held"] == 0.0
    assert pos["avg_cost"] == 0.0
    assert pos["realized_pl"] == 100.0


def test_compute_position_sell_to_zero_then_rebuy():
    txs = [
        {"side": "buy", "shares": 100, "price": 2.00},
        {"side": "sell", "shares": 100, "price": 3.00},
        {"side": "buy", "shares": 50, "price": 5.00},
    ]
    pos = compute_position(txs)
    assert pos["shares_held"] == 50
    assert pos["avg_cost"] == 5.00
    assert pos["realized_pl"] == 100.0


def test_shares_as_of():
    txs = [
        {"side": "buy", "shares": 100, "trade_date": "2024-01-01"},
        {"side": "buy", "shares": 50, "trade_date": "2024-06-01"},
        {"side": "sell", "shares": 30, "trade_date": "2024-09-01"},
    ]
    assert _shares_as_of(txs, "2023-12-31") == 0.0
    assert _shares_as_of(txs, "2024-01-01") == 100.0
    assert _shares_as_of(txs, "2024-03-15") == 100.0
    assert _shares_as_of(txs, "2024-06-01") == 150.0
    assert _shares_as_of(txs, "2024-09-01") == 120.0


def test_price_as_of():
    points = [
        {"date": "2024-01-01", "price": 2.00},
        {"date": "2024-06-01", "price": 3.50},
        {"date": "2024-12-01", "price": 4.00},
    ]
    assert _price_as_of(points, "2023-12-31") is None
    assert _price_as_of(points, "2024-01-01") == 2.00
    assert _price_as_of(points, "2024-03-15") == 2.00
    assert _price_as_of(points, "2024-06-01") == 3.50
    assert _price_as_of(points, "2024-12-31") == 4.00


def test_cost_basis_as_of():
    txs = [
        {"side": "buy", "shares": 100, "price": 2.00, "trade_date": "2024-01-01"},
        {"side": "buy", "shares": 100, "price": 4.00, "trade_date": "2024-06-01"},
        {"side": "sell", "shares": 50, "price": 5.00, "trade_date": "2024-09-01"},
    ]
    assert _cost_basis_as_of(txs, "2023-12-31") == 0.0
    assert _cost_basis_as_of(txs, "2024-01-01") == 200.0  # 100 * 2.00
    assert _cost_basis_as_of(txs, "2024-06-01") == 600.0  # 200 * 3.00
    assert _cost_basis_as_of(txs, "2024-09-01") == 450.0  # 150 * 3.00
