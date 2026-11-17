from __future__ import annotations

import unittest

import server


class BrowserLeaseTest(unittest.TestCase):
    def test_server_stops_when_browser_never_opens(self) -> None:
        lease = server.BrowserLease(now=0)
        self.assertFalse(lease.should_stop(now=29))
        self.assertTrue(lease.should_stop(now=30))

    def test_close_waits_for_grace_period(self) -> None:
        lease = server.BrowserLease(now=0)
        lease.heartbeat(now=1)
        lease.close(now=2)
        self.assertFalse(lease.should_stop(now=4.9))
        self.assertTrue(lease.should_stop(now=5))

    def test_reload_heartbeat_cancels_close(self) -> None:
        lease = server.BrowserLease(now=0)
        lease.heartbeat(now=1)
        lease.close(now=2)
        lease.heartbeat(now=3)
        self.assertFalse(lease.should_stop(now=6))

    def test_abandoned_browser_eventually_expires(self) -> None:
        lease = server.BrowserLease(now=0)
        lease.heartbeat(now=1)
        self.assertFalse(lease.should_stop(now=180.9))
        self.assertTrue(lease.should_stop(now=181))


if __name__ == "__main__":
    unittest.main()
