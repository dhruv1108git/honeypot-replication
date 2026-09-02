import unittest

from cotmon import store
from helpers import make_snapshot, memory_store

DAY = ("2026-08-20T00:00:00Z", "2026-08-21T00:00:00Z")


class SelectTrajectoriesTest(unittest.TestCase):
    def test_selects_snapshots_in_window(self):
        conn = memory_store(
            make_snapshot("s1", "ep1", 4),
            make_snapshot("s2", "ep2", 6, captured_at="2026-08-21T01:00:00Z"),
        )
        got = store.select_trajectories(conn, *DAY)
        self.assertEqual([t.snapshot_id for t in got], ["s1"])

    def test_keeps_longest_snapshot_per_episode(self):
        conn = memory_store(
            make_snapshot("s1", "ep1", 4, captured_at="2026-08-20T09:00:00Z"),
            make_snapshot("s2", "ep1", 12, captured_at="2026-08-20T11:00:00Z"),
            make_snapshot("s3", "ep1", 9, captured_at="2026-08-20T13:00:00Z"),
            make_snapshot("s4", "ep2", 3),
        )
        got = store.select_trajectories(conn, *DAY)
        self.assertEqual([(t.episode_id, t.snapshot_id) for t in got], [("ep1", "s2"), ("ep2", "s4")])
        self.assertEqual(got[0].n_messages, 12)

    def test_tie_on_length_takes_latest(self):
        conn = memory_store(
            make_snapshot("s1", "ep1", 8, captured_at="2026-08-20T09:00:00Z"),
            make_snapshot("s2", "ep1", 8, captured_at="2026-08-20T10:00:00Z"),
        )
        (traj,) = store.select_trajectories(conn, *DAY)
        self.assertEqual(traj.snapshot_id, "s2")

    def test_messages_are_ordered(self):
        conn = memory_store(make_snapshot("s1", "ep1", 7))
        (traj,) = store.select_trajectories(conn, *DAY)
        self.assertEqual([m.idx for m in traj.messages], list(range(7)))
        self.assertEqual(traj.n_messages, 7)


class IterBatchesTest(unittest.TestCase):
    def test_partial_and_empty_batches(self):
        for n in (0, 1, 2, 5, 6):
            with self.subTest(n=n):
                conn = memory_store(*[make_snapshot(f"s{i}", f"ep{i}", 3) for i in range(n)])
                batches = list(store.iter_trajectory_batches(conn, *DAY, batch_size=2))
                self.assertEqual([t.snapshot_id for b in batches for t in b],
                                 [f"s{i}" for i in range(n)])
                self.assertTrue(all(0 < len(b) <= 2 for b in batches))
                conn.close()

    def test_batches_match_select(self):
        conn = memory_store(*[make_snapshot(f"s{i}", f"ep{i}", 3 + i) for i in range(6)])
        batches = list(store.iter_trajectory_batches(conn, *DAY, batch_size=2))
        self.assertEqual([len(b) for b in batches], [2, 2, 2])
        flat = [t.snapshot_id for b in batches for t in b]
        self.assertEqual(flat, [t.snapshot_id for t in store.select_trajectories(conn, *DAY)])

    def test_messages_attached_in_order(self):
        conn = memory_store(make_snapshot("s1", "ep1", 5), make_snapshot("s2", "ep2", 3))
        (batch,) = store.iter_trajectory_batches(conn, *DAY, batch_size=2)
        self.assertEqual([m.idx for m in batch[0].messages], list(range(5)))
        self.assertEqual([m.idx for m in batch[1].messages], list(range(3)))


if __name__ == "__main__":
    unittest.main()
