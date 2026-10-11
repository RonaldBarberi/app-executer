import os, sys, unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
from main import ActivitiesPage

LOCK = {'run_id': '20261011120001518-bot', 'bot': 'bot', 'trigger': 'cron', 'start': '2026-10-11T12:00:01'}
END = {'event': 'end', 'id': LOCK['run_id'], 'bot': 'bot', 'end': '2026-10-11T12:03:23', 'status': 'succeeded', 'code': 0}


class TestActivitiesTrack(unittest.TestCase):

    def page(self, history):
        # only the tracking state, without building the Tk widgets
        page = object.__new__(ActivitiesPage)
        page.app = SimpleNamespace(scheduler=SimpleNamespace(history=lambda: history))
        page.finished, page.seen = {}, {}
        return page

    def test_run_that_ends_on_another_tab_is_kept(self):
        page = self.page([END])
        page.track({'bot': LOCK})
        page.track({})
        item = page.finished[LOCK['run_id']]
        self.assertEqual(item['kind'], 'finished')
        self.assertEqual(item['status'], 'succeeded')
        self.assertEqual(item['end'], END['end'])
        self.assertEqual(item['start'], LOCK['start'])

    def test_end_not_in_history_yet(self):
        page = self.page([])
        page.track({'bot': LOCK})
        page.track({})
        self.assertEqual(page.finished[LOCK['run_id']]['status'], 'running')

    def test_still_running_is_not_finished(self):
        page = self.page([END])
        page.track({'bot': LOCK})
        page.track({'bot': LOCK})
        self.assertEqual(page.finished, {})

    def test_runs_ended_before_the_app_opened_are_not_listed(self):
        page = self.page([END])
        page.track({})
        self.assertEqual(page.finished, {})


if __name__ == '__main__':
    unittest.main()
