import datetime as dt
import itertools
import unittest
from arena.policy import best_six, submission_open, visible_to_public

class PolicyTests(unittest.TestCase):
    def test_quarantine_boundary_is_exclusive(self):
        opens=dt.datetime(2026,10,23,8,tzinfo=dt.timezone.utc)
        lock=opens+dt.timedelta(hours=2)
        for delta,expected in [(-1,False),(0,True),(1,True)]:
            self.assertEqual(submission_open(now=opens+dt.timedelta(microseconds=delta),opens_at=opens,quarantine_at=lock),expected)
        self.assertTrue(submission_open(now=lock-dt.timedelta(microseconds=1),opens_at=opens,quarantine_at=lock))
        self.assertFalse(submission_open(now=lock,opens_at=opens,quarantine_at=lock))
        self.assertFalse(submission_open(now=lock+dt.timedelta(microseconds=1),opens_at=opens,quarantine_at=lock))
    def test_completed_and_finished_deny_uploads(self):
        now=dt.datetime.now(dt.timezone.utc)
        for completed,finished in [(True,False),(False,True),(True,True)]:
            self.assertFalse(submission_open(now=now,opens_at=now-dt.timedelta(days=1),quarantine_at=now+dt.timedelta(days=1),completed=completed,finished=finished))
    def test_round_files_never_become_public(self):
        for kind in ['round_code','round_json']:
            for gates in itertools.product([False,True],repeat=6):
                self.assertFalse(visible_to_public(kind=kind,current=True,deleted=False,clean=True,approved=True,
                    competition_finished=gates[0],archive_released=gates[1],competition_ended=gates[2],
                    round_completed=gates[3],round_released=gates[4],round_ended=gates[5]))
    def test_package_needs_every_release_gate(self):
        names=['current','clean','approved','competition_finished','archive_released','competition_ended']
        for kind in ['tdp','video','code','bom','poster']:
            for values in itertools.product([False,True],repeat=6):
                self.assertEqual(visible_to_public(kind=kind,deleted=False,public_copy=True,**dict(zip(names,values))),all(values))
    def test_map_requires_completion_and_release_independent_of_scheduled_end(self):
        for completed,released,ended in itertools.product([False,True],repeat=3):
            self.assertEqual(visible_to_public(kind='map',current=True,deleted=False,clean=True,approved=True,
                competition_finished=False,archive_released=False,competition_ended=False,
                round_completed=completed,round_released=released,round_ended=ended),completed and released)
    def test_pending_is_distinct_from_zero(self):
        self.assertEqual(best_six([0,1,2,3,4,5,6]),(21,1))
        self.assertEqual(best_six([None,1,2,3,4,5,6]),(None,None))
        self.assertEqual(best_six([0,0,0,0,0,0,0]),(0,1))
    def test_first_tied_lowest_round_is_excluded(self):
        self.assertEqual(best_six([8,2,2,5,6,7,9]),(37,2))

if __name__=='__main__': unittest.main()
