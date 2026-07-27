import pytest
import db


def test_add_and_get_transaction():
    db.upsert_user(111111111, "testuser", "Test")
    db.add_transaction(111111111, "MTNGH", "buy", 100, 2.50)
    txs = db.get_transactions(111111111)
    assert len(txs) == 1
    assert txs[0]["symbol"] == "MTNGH"
    assert txs[0]["side"] == "buy"
    assert txs[0]["shares"] == 100
    assert txs[0]["price"] == 2.50


def test_get_transactions_filtered_by_symbol():
    db.upsert_user(111111111, "testuser", "Test")
    db.add_transaction(111111111, "MTNGH", "buy", 100, 2.50)
    db.add_transaction(111111111, "GCB", "buy", 50, 10.00)
    mtn = db.get_transactions(111111111, "MTNGH")
    assert len(mtn) == 1
    assert mtn[0]["symbol"] == "MTNGH"


def test_shares_held():
    db.upsert_user(111111111, "testuser", "Test")
    db.add_transaction(111111111, "MTNGH", "buy", 100, 2.50)
    db.add_transaction(111111111, "MTNGH", "buy", 50, 3.00)
    assert db.shares_held(111111111, "MTNGH") == 150.0

    db.add_transaction(111111111, "MTNGH", "sell", 30, 4.00)
    assert db.shares_held(111111111, "MTNGH") == 120.0


def test_sell_short_prevention():
    db.upsert_user(111111111, "testuser", "Test")
    db.add_transaction(111111111, "MTNGH", "buy", 10, 2.50)
    with pytest.raises(ValueError, match="cannot sell"):
        db.add_transaction(111111111, "MTNGH", "sell", 20, 3.00)


def test_held_symbols():
    db.upsert_user(111111111, "testuser", "Test")
    db.add_transaction(111111111, "MTNGH", "buy", 100, 2.50)
    db.add_transaction(111111111, "GCB", "buy", 50, 10.00)
    assert set(db.held_symbols(111111111)) == {"MTNGH", "GCB"}

    db.add_transaction(111111111, "MTNGH", "sell", 100, 3.00)
    assert db.held_symbols(111111111) == ["GCB"]


def test_delete_transaction():
    db.upsert_user(111111111, "testuser", "Test")
    db.add_transaction(111111111, "MTNGH", "buy", 100, 2.50)
    txs = db.get_transactions(111111111)
    tx_id = txs[0]["id"]
    assert db.delete_transaction(111111111, tx_id) is True
    assert db.delete_transaction(111111111, tx_id) is False
    assert len(db.get_transactions(111111111)) == 0


def test_delete_transaction_wrong_user():
    db.upsert_user(111111111, "user1", "User1")
    db.upsert_user(222222222, "user2", "User2")
    db.add_transaction(111111111, "MTNGH", "buy", 100, 2.50)
    txs = db.get_transactions(111111111)
    tx_id = txs[0]["id"]
    assert db.delete_transaction(222222222, tx_id) is False


def test_save_and_get_snapshots():
    db.save_snapshot("MTNGH", 2.50, "2024-01-01", change=0.05, volume=1000)
    db.save_snapshot("MTNGH", 2.60, "2024-01-02", change=-0.02, volume=500)
    snaps = db.get_snapshots("MTNGH")
    assert len(snaps) == 2
    assert snaps[0]["price"] == 2.50
    assert snaps[1]["price"] == 2.60


def test_latest_snapshot_price():
    db.save_snapshot("MTNGH", 2.50, "2024-01-01")
    db.save_snapshot("MTNGH", 2.60, "2024-01-02")
    assert db.latest_snapshot_price("MTNGH") == 2.60
    assert db.latest_snapshot_price("NONEXIST") is None


def test_snapshot_upsert():
    db.save_snapshot("MTNGH", 2.50, "2024-01-01")
    db.save_snapshot("MTNGH", 2.99, "2024-01-01")
    snaps = db.get_snapshots("MTNGH")
    assert len(snaps) == 1
    assert snaps[0]["price"] == 2.99


def test_migration_idempotent():
    db._migrate_snapshots(db._connect())
    db._migrate_snapshots(db._connect())
    db.save_snapshot("TEST", 1.0, change=0.1, volume=100)
    assert db.latest_snapshot_price("TEST") == 1.0
