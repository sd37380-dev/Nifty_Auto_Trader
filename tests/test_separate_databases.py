"""
Unit tests for Separate Tick Data Database (market_ticks.db) and
Separate Option Chain Database (option_chain.db) with Supabase Cloud dual-persistence.
"""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from nifty_trader.market_data.tick_service import TickDataService
from nifty_trader.market_data.option_chain_store import OptionChainStore
from nifty_trader.core.supabase_adapter import SupabaseAdapter


class TestSeparateDatabases(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root_dir = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_tick_data_service_isolation_and_crud(self):
        """Verify TickDataService uses dedicated market_ticks.db and records ticks accurately."""
        service = TickDataService(root_dir=self.root_dir)
        self.assertTrue(service.db_path.name == "market_ticks.db")

        # Record ticks
        t1 = service.record_tick(
            symbol="NIFTY",
            price=24150.50,
            open_price=24100.0,
            high_price=24180.0,
            low_price=24090.0,
            close_price=24150.50,
            volume=50000,
            change_pts=50.50,
            change_pct=0.21,
        )
        t2 = service.record_tick(
            symbol="NIFTY",
            price=24160.00,
            volume=55000,
            change_pts=60.00,
            change_pct=0.25,
        )
        t3 = service.record_tick(
            symbol="BANKNIFTY",
            price=51800.00,
            volume=30000,
            change_pts=-120.0,
            change_pct=-0.23,
        )

        self.assertIsNotNone(t1)
        self.assertIsNotNone(t2)
        self.assertIsNotNone(t3)

        # Verify separation and querying
        nifty_ticks = service.get_recent_ticks("NIFTY", limit=10)
        self.assertEqual(len(nifty_ticks), 2)
        self.assertEqual(nifty_ticks[0]["price"], 24160.00)
        self.assertEqual(nifty_ticks[1]["price"], 24150.50)

        bank_ticks = service.get_recent_ticks("BANKNIFTY", limit=10)
        self.assertEqual(len(bank_ticks), 1)
        self.assertEqual(bank_ticks[0]["price"], 51800.00)

        self.assertEqual(service.get_tick_count("NIFTY"), 2)
        self.assertEqual(service.get_tick_count("BANKNIFTY"), 1)
        self.assertEqual(service.get_tick_count(), 3)

        # Ensure no other database files were touched
        self.assertTrue((self.root_dir / "data" / "market" / "market_ticks.db").exists())
        self.assertFalse((self.root_dir / "data" / "market" / "option_chain.db").exists())

    def test_option_chain_store_isolation_and_crud(self):
        """Verify OptionChainStore uses dedicated option_chain.db and handles snapshots."""
        store = OptionChainStore(root_dir=self.root_dir)
        self.assertTrue(store.db_path.name == "option_chain.db")

        # Save snapshot
        mock_strikes = [
            {"strike": 24100, "ce_ltp": 150.0, "ce_oi": 85000, "pe_ltp": 80.0, "pe_oi": 120000},
            {"strike": 24150, "ce_ltp": 115.0, "ce_oi": 95000, "pe_ltp": 110.0, "pe_oi": 90000},
            {"strike": 24200, "ce_ltp": 85.0, "ce_oi": 140000, "pe_ltp": 145.0, "pe_oi": 60000},
        ]
        snap_id = store.save_snapshot(
            symbol="NIFTY",
            expiry="2026-11-26",
            spot_price=24152.0,
            atm_strike=24150.0,
            pcr=1.12,
            max_pain=24150.0,
            total_ce_oi=320000,
            total_pe_oi=358000,
            strikes=mock_strikes,
        )

        self.assertTrue(snap_id.startswith("oc_nifty_2026-11-26_"))
        self.assertEqual(store.get_snapshot_count("NIFTY"), 1)

        # Retrieve latest snapshot
        latest = store.get_latest_snapshot("NIFTY", "2026-11-26")
        self.assertIsNotNone(latest)
        self.assertEqual(latest["spot_price"], 24152.0)
        self.assertEqual(latest["pcr"], 1.12)
        self.assertEqual(len(latest["strikes"]), 3)
        self.assertEqual(latest["strikes"][1]["strike"], 24150)

        # Retrieve history
        history = store.get_historical_snapshots("NIFTY", limit=5)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["snapshot_id"], snap_id)

        # Ensure no other database files were touched
        self.assertTrue((self.root_dir / "data" / "market" / "option_chain.db").exists())
        self.assertFalse((self.root_dir / "data" / "market" / "market_ticks.db").exists())

    def test_supabase_adapter_tick_and_option_chain_sync(self):
        """Verify SupabaseAdapter handles tick and option chain sync calls."""
        with patch.dict("os.environ", {"SUPABASE_URL": "https://fake.supabase.co", "SUPABASE_KEY": "fake_key"}):
            adapter = SupabaseAdapter(root_dir=self.root_dir)
            self.assertTrue(adapter.is_enabled)
            self.assertIn("separate_databases", adapter.get_status())
            self.assertEqual(
                adapter.get_status()["separate_databases"]["tick_data"], "data/market/market_ticks.db"
            )
            self.assertEqual(
                adapter.get_status()["separate_databases"]["option_chain"], "data/market/option_chain.db"
            )

            with patch.object(adapter, "_async_post") as mock_post:
                # 1. Sync tick
                adapter.sync_tick_data({"symbol": "NIFTY", "price": 24150.0})
                mock_post.assert_called_once()
                self.assertEqual(mock_post.call_args[0][0], "market_ticks")

                mock_post.reset_mock()

                # 2. Sync option chain
                adapter.sync_option_chain_snapshot({"snapshot_id": "test_id", "symbol": "NIFTY", "spot_price": 24150.0})
                mock_post.assert_called_once()
                self.assertEqual(mock_post.call_args[0][0], "option_chain_snapshots")


if __name__ == "__main__":
    unittest.main()
