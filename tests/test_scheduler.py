import os, sys, json, tempfile, unittest
from datetime import datetime, timedelta
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
from main import Scheduler, LocalizedError, iso

NOW = datetime(2026, 10, 9, 12, 0)


class FakeRunner:
    # the test process itself plays the runner, so running() sees it alive until its lock is removed
    pid = os.getpid()


class TestScheduler(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = os.path.join(self.tmp.name, 'app')
        os.makedirs(os.path.join(base, 'config'))
        self.config = {'APP_NAME': 'app-test', 'PROJECTS_PATH': '..', 'WATCH_PATH': '../watch',
                       'SCHEDULES_FILE': 'config/schedules.json', 'MAX_PARALLEL': 2, 'MISSED_AFTER_MINUTES': 5, 'HISTORY_DAYS': 30}
        self.sched = Scheduler(base, self.config, state_dir=os.path.join(self.tmp.name, 'state'))
        self.spawned = []
        patcher = mock.patch.object(Scheduler, '_spawn', side_effect=lambda args: self.spawned.append(args) or FakeRunner())
        patcher.start()
        self.addCleanup(patcher.stop)
        clock = mock.patch.object(Scheduler, 'now', staticmethod(lambda: NOW))
        clock.start()
        self.addCleanup(clock.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def schedules(self, data):
        with open(self.sched.schedules_path, 'w', encoding='utf-8') as fh:
            json.dump(data, fh)

    def state(self, **values):
        self.sched._write_json(self.sched.state_path, values)

    def started(self):
        return [args[args.index('--run') + 1] for args in self.spawned]

    def events(self, kind):
        return [r for r in self.sched.history() if r.get('event') == kind]

    def finish(self, bot):
        os.remove(self.sched.lock_path(bot))

    def test_due_bot_is_launched_with_its_lock_and_history(self):
        self.schedules({'bot': {'CRON_DRIVER': ['0 12 * * *'], 'ENABLED': True}})
        self.state(last_tick=iso(NOW - timedelta(minutes=1)))
        self.sched.tick(NOW)
        self.assertEqual(self.started(), ['bot'])
        args = self.spawned[0]
        self.assertEqual(args[args.index('--trigger') + 1], 'cron')
        self.assertEqual(args[args.index('--scheduled-for') + 1], '2026-10-09T12:00:00')
        self.assertIn('bot', self.sched.running())
        [run] = self.sched.history()
        self.assertEqual((run['bot'], run['status'], run['trigger']), ('bot', 'running', 'cron'))

    def test_not_due(self):
        self.schedules({'bot': {'CRON_DRIVER': ['0 10 * * *']}})
        self.state(last_tick=iso(NOW - timedelta(minutes=1)))
        self.sched.tick(NOW)
        self.assertEqual(self.spawned, [])

    def test_late_runs_are_missed_once_and_the_current_one_runs(self):
        # PC off from 09:00: 10:00 and 11:00 are missed, 12:00 is on time
        self.schedules({'bot': {'CRON_DRIVER': ['0 * * * *']}})
        self.state(last_tick=iso(datetime(2026, 10, 9, 9, 0)))
        self.sched.tick(NOW)
        [missed] = self.events('missed')
        self.assertEqual((missed['count'], missed['first'], missed['last']), (2, '2026-10-09T10:00:00', '2026-10-09T11:00:00'))
        self.assertEqual(self.started(), ['bot'])

    def test_a_slightly_late_tick_still_runs(self):
        self.schedules({'bot': {'CRON_DRIVER': ['58 11 * * *']}})
        self.state(last_tick=iso(datetime(2026, 10, 9, 11, 50)))
        self.sched.tick(NOW)
        self.assertEqual(self.started(), ['bot'])
        self.assertEqual(self.events('missed'), [])

    def test_running_bot_is_queued_once_and_starts_when_it_finishes(self):
        self.schedules({'bot': {'CRON_DRIVER': ['* * * * *']}})
        self.state(last_tick=iso(NOW - timedelta(minutes=1)))
        self.sched.tick(NOW)
        self.sched.tick(NOW + timedelta(minutes=1))
        self.sched.tick(NOW + timedelta(minutes=2))
        self.assertEqual(self.started(), ['bot'])
        self.assertIn('bot', self.sched.read_state()['queue'])
        [queued] = self.events('queued')
        self.assertEqual(queued['reason'], 'already_running')
        self.finish('bot')
        self.schedules({})
        self.sched.tick(NOW + timedelta(minutes=3))
        self.assertEqual(self.started(), ['bot', 'bot'])
        self.assertEqual(self.sched.read_state()['queue'], {})

    def test_max_parallel_queues_the_rest(self):
        self.config['MAX_PARALLEL'] = 1
        self.schedules({'a': {'CRON_DRIVER': ['0 12 * * *']}, 'b': {'CRON_DRIVER': ['0 12 * * *']}})
        self.state(last_tick=iso(NOW - timedelta(minutes=1)))
        self.sched.tick(NOW)
        self.assertEqual(self.started(), ['a'])
        self.assertEqual(self.events('queued')[0]['reason'], 'max_parallel')
        self.finish('a')
        self.sched.tick(NOW + timedelta(minutes=1))
        self.assertEqual(self.started(), ['a', 'b'])

    def test_disabled_paused_and_invalid_are_ignored(self):
        self.schedules({'off': {'CRON_DRIVER': ['* * * * *'], 'ENABLED': False}, 'bad': {'CRON_DRIVER': ['99 * * * *']}})
        self.state(last_tick=iso(NOW - timedelta(minutes=1)))
        self.sched.tick(NOW)
        self.schedules({'on': {'CRON_DRIVER': ['* * * * *']}})
        self.sched.set_paused_here(True)
        self.sched.tick(NOW + timedelta(minutes=1))
        self.assertEqual(self.spawned, [])
        self.assertEqual(self.sched.read_state()['last_tick'], iso(NOW + timedelta(minutes=1)))

    def test_manual_request(self):
        self.assertEqual(self.sched.request_run('bot'), 'started')
        self.assertEqual(self.sched.request_run('bot'), 'queued')
        self.assertEqual(self.sched.request_run('bot'), 'already_queued')
        self.assertTrue(self.sched.cancel_queued('bot'))
        self.assertEqual(self.sched.read_state()['queue'], {})

    def test_stale_lock_is_closed_as_interrupted(self):
        self.sched._write_json(self.sched.lock_path('bot'), {'bot': 'bot', 'run_id': 'r1', 'runner_pid': os.getpid(), 'runner_started': 1})
        self.sched.tick(NOW)
        self.assertFalse(os.path.exists(self.sched.lock_path('bot')))
        self.assertEqual(self.sched.history()[0]['status'], 'interrupted')

    def test_history_merges_start_and_end(self):
        self.sched._history_add(event='start', id='r1', bot='bot', trigger='manual', start='2026-10-09T10:00:00')
        self.sched._history_add(event='end', id='r1', bot='bot', end='2026-10-09T10:05:00', status='succeeded', code=0)
        self.sched._history_add(event='missed', id='m1', bot='bot', time='2026-10-09T11:00:00', count=1)
        history = self.sched.history()
        self.assertEqual([h['id'] for h in history], ['m1', 'r1'])
        self.assertEqual((history[1]['status'], history[1]['code'], history[1]['start']), ('succeeded', 0, '2026-10-09T10:00:00'))

    def test_prune_keeps_runs_that_ended_recently(self):
        old = NOW - timedelta(days=40)
        self.sched._history_add(event='start', id='old', bot='b', start=iso(old))
        self.sched._history_add(event='end', id='old', bot='b', end=iso(old))
        self.sched._history_add(event='start', id='long', bot='b', start=iso(old))
        self.sched._history_add(event='end', id='long', bot='b', end=iso(NOW - timedelta(days=1)))
        self.sched._prune(NOW)
        self.assertEqual([h['id'] for h in self.sched.history()], ['long'])
        self.assertEqual(self.sched.history()[0]['start'], iso(old))

    def test_driver_status_missing(self):
        # 'app-test driver' is never registered
        self.assertEqual(self.sched.driver_status(), 'missing')

    def test_save_schedules_refuses_changes_on_disk(self):
        data, mtime = self.sched.load_schedules()
        self.assertEqual((data, mtime), ({}, None))
        mtime = self.sched.save_schedules({'bot': {'CRON_DRIVER': ['@daily'], 'ENABLED': True}}, mtime)
        os.utime(self.sched.schedules_path, (1, 1))
        with self.assertRaises(LocalizedError):
            self.sched.save_schedules({}, mtime)


if __name__ == '__main__':
    unittest.main()
