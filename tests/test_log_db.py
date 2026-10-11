import os, sys, types, sqlite3, tempfile, unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
import main as m


class FakeCursor:
    """pymysql-like cursor over sqlite: %s placeholders, `db`.`table` names and SHOW COLUMNS."""

    def __init__(self, server):
        self.server = server
        self.cur = server.db.cursor()
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def _check(self, params):
        if self.server.fail_on and self.server.fail_on in repr(params):
            raise RuntimeError('insert failed')

    def _sql(self, sql):
        return sql.replace('%s', '?').replace('`bbdd`.`logs`', 'logs')

    def execute(self, sql, params=()):
        if sql.startswith('SHOW COLUMNS'):
            self.rows = [(row[1],) for row in self.server.db.execute('PRAGMA table_info(logs)')]
            return
        self._check(params)
        self.cur.execute(self._sql(sql), params)
        self.rows = None

    def executemany(self, sql, seq):
        seq = list(seq)
        self._check(seq)
        self.cur.executemany(self._sql(sql), seq)

    def fetchall(self):
        return self.rows if self.rows is not None else self.cur.fetchall()

    def fetchone(self):
        return self.rows[0] if self.rows else self.cur.fetchone()


class FakeServer:
    def __init__(self):
        self.db = sqlite3.connect(':memory:')
        self.db.execute('CREATE TABLE logs (id INTEGER PRIMARY KEY AUTOINCREMENT, process_name TEXT, id_process INTEGER, '
                        'timestamp_log TEXT, type_log TEXT, message TEXT, update_at TEXT)')
        self.db.commit()
        self.fail_on = None
        self.connected_with = None

    def connect(self, **kwargs):
        self.connected_with = kwargs
        server = self

        class Conn:
            def cursor(self):
                return FakeCursor(server)

            def commit(self):
                server.db.commit()

            def rollback(self):
                server.db.rollback()

            def close(self):
                pass

        return Conn()

    def rows(self):
        return self.db.execute('SELECT process_name, id_process, timestamp_log, type_log, message FROM logs ORDER BY id').fetchall()


def log_line(group, run_id, stamp, level, message):
    return f'{group}§{run_id}§{stamp}§{level}§{message}\r\n'


class LogDbTestCase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = self.tmp.name
        self.watch = os.path.join(self.base, 'watch')
        os.makedirs(self.watch)
        self.env = os.path.join(self.base, '.env')
        with open(self.env, 'w', encoding='utf-8') as f:
            f.write('OWNER_SQL_HOST=10.0.0.5\nOWNER_SQL_PORT=3306\nOWNER_SQL_USER=rpa\nOWNER_SQL_PASSWORD="se#cret"\n')
        self.db = {'ENV_FILE': self.env, 'DATABASE': 'bbdd', 'TABLE': 'logs', 'QUERY_LIMIT': 3,
                   'ENV_KEYS': {'host': 'OWNER_SQL_HOST', 'port': 'OWNER_SQL_PORT', 'user': 'OWNER_SQL_USER',
                                'password': 'OWNER_SQL_PASSWORD'}}
        self.server = FakeServer()
        sys.modules['pymysql'] = types.SimpleNamespace(connect=self.server.connect)

    def tearDown(self):
        sys.modules.pop('pymysql', None)
        self.server.db.close()
        self.tmp.cleanup()

    def write_log(self, group, run_id, lines):
        folder = os.path.join(self.watch, group)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f'{run_id}.txt')
        with open(path, 'w', encoding='utf-8', newline='') as f:
            f.write(''.join(log_line(group, run_id, *line) for line in lines))
        return path

    def database(self):
        return m.LogDatabase(self.base, self.db)


class TestParseAndSettings(LogDbTestCase):

    def test_parse_watch_log(self):
        text = ('garbage before the first event\r\n'
                + log_line('bot-a', '20261011100001', '2026-10-11 10:00:01', 'INFO', 'start')
                + log_line('bot-a', '20261011100001', '2026-10-11 10:00:02', 'ERROR', 'Traceback (most recent call last):')
                + '  File "x.py", line 1\r\n')
        self.assertEqual(m.parse_watch_log(text), [
            ('bot-a', 20261011100001, '2026-10-11 10:00:01', 'INFO', 'start'),
            ('bot-a', 20261011100001, '2026-10-11 10:00:02', 'ERROR', 'Traceback (most recent call last):\n  File "x.py", line 1'),
        ])

    def test_apply_settings_only_overrides_editable_fields(self):
        config = {'APP_NAME': 'x', 'WATCH_PATH': '../../kreton-watch', 'LOG_DB': {'ENV_FILE': 'a', 'TABLE': 't', 'ENV_KEYS': {'host': 'H'}}}
        merged = m.apply_settings(config, {'WATCH_PATH': r'C:\logs', 'LOG_DB': {'TABLE': 'other', 'ENV_KEYS': {'host': 'X'}}})
        self.assertEqual(merged['WATCH_PATH'], r'C:\logs')
        self.assertEqual(merged['LOG_DB'], {'ENV_FILE': 'a', 'TABLE': 'other', 'ENV_KEYS': {'host': 'H'}})
        self.assertEqual(config['LOG_DB']['TABLE'], 't')
        self.assertEqual(m.apply_settings(config, {}), {**config, 'LOG_DB': config['LOG_DB']})

    def test_env_values_and_credentials(self):
        values = m.LogDatabase.env_values(self.env, self.db['ENV_KEYS'])
        self.assertEqual(values, {'host': '10.0.0.5', 'port': '3306', 'user': 'rpa', 'password': 'se#cret'})
        with open(self.env, 'w', encoding='utf-8') as f:
            f.write('OWNER_SQL_HOST=10.0.0.5\nOWNER_SQL_PORT=abc\n')
        with self.assertRaises(m.LocalizedError) as ctx:
            self.database().credentials()
        self.assertEqual(ctx.exception.key, 'db.err_env_keys')
        self.assertEqual(ctx.exception.params['keys'], 'OWNER_SQL_USER, OWNER_SQL_PASSWORD')

    def test_invalid_names(self):
        self.db['TABLE'] = 'logs; DROP TABLE x'
        with self.assertRaises(m.LocalizedError) as ctx:
            self.database().credentials()
        self.assertEqual(ctx.exception.key, 'db.err_name')

    def test_invalid_port(self):
        with open(self.env, 'a', encoding='utf-8') as f:
            f.write('OWNER_SQL_PORT=33o6\n')
        with self.assertRaises(m.LocalizedError) as ctx:
            self.database().credentials()
        self.assertEqual((ctx.exception.key, ctx.exception.params), ('db.err_port', {'var': 'OWNER_SQL_PORT'}))

    def test_missing_env_file(self):
        os.remove(self.env)
        with self.assertRaises(m.LocalizedError) as ctx:
            self.database().credentials()
        self.assertEqual(ctx.exception.key, 'db.err_env_missing')

    def test_find_db_python(self):
        projects = os.path.join(self.base, 'projects')
        for bot, lib in (('a-bot', None), ('b-bot', 'pymysql')):
            scripts = os.path.join(projects, bot, '.venv', 'Scripts')
            os.makedirs(scripts)
            open(os.path.join(scripts, 'python.exe'), 'w').close()
            if lib:
                os.makedirs(os.path.join(projects, bot, '.venv', 'Lib', 'site-packages', lib))
        self.assertEqual(m.find_db_python(projects), os.path.join(projects, 'b-bot', '.venv', 'Scripts', 'python.exe'))
        self.assertEqual(m.find_db_python(os.path.join(self.base, 'nothing')), '')


class TestUpload(LogDbTestCase):

    def test_connects_with_the_env_values(self):
        self.assertEqual(self.database().test(), {'rows': 0})
        self.assertEqual(self.server.connected_with['host'], '10.0.0.5')
        self.assertEqual(self.server.connected_with['port'], 3306)
        self.assertEqual(self.server.connected_with['password'], 'se#cret')
        self.assertEqual(self.server.connected_with['database'], 'bbdd')

    def test_uploads_deletes_and_removes_empty_folders(self):
        a = self.write_log('bot-a', '20261011100001', [('2026-10-11 10:00:01', 'INFO', 'a1'), ('2026-10-11 10:00:02', 'WARNING', 'a2')])
        b = self.write_log('bot-b', '20261011110000', [('2026-10-11 11:00:00', 'ERROR', 'b1')])
        progress = []
        result = self.database().upload(self.watch, [], lambda **data: progress.append(data))
        self.assertEqual(result, {'files': 2, 'rows': 3, 'skipped': 0, 'failed': 0, 'error': ''})
        self.assertEqual(progress, [{'progress': 1, 'total': 2}, {'progress': 2, 'total': 2}])
        self.assertFalse(os.path.exists(a) or os.path.exists(b))
        self.assertEqual(os.listdir(self.watch), [])
        self.assertEqual([r[4] for r in self.server.rows()], ['a1', 'a2', 'b1'])
        update_at = self.server.db.execute('SELECT DISTINCT update_at FROM logs').fetchall()
        self.assertEqual(len(update_at), 1)
        self.assertRegex(update_at[0][0], r'^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d$')

    def test_running_log_is_not_touched(self):
        done = self.write_log('bot-a', '20261011100001', [('2026-10-11 10:00:01', 'INFO', 'done')])
        running = self.write_log('bot-a', '20261011120000', [('2026-10-11 12:00:00', 'INFO', 'still running')])
        result = self.database().upload(self.watch, [running.upper()], lambda **d: None)
        self.assertEqual((result['files'], result['skipped']), (1, 1))
        self.assertFalse(os.path.exists(done))
        self.assertTrue(os.path.exists(running))
        self.assertEqual([r[4] for r in self.server.rows()], ['done'])

    def test_log_held_open_by_a_bot_is_skipped(self):
        path = self.write_log('bot-x', '20261011130000', [('2026-10-11 13:00:00', 'INFO', 'open')])
        # a bot started outside the app (no lock) still writing: Python opens files without FILE_SHARE_DELETE
        with open(path, 'a', encoding='utf-8'):
            result = self.database().upload(self.watch, [], lambda **d: None)
        self.assertEqual((result['files'], result['skipped']), (0, 1))
        self.assertTrue(os.path.exists(path))
        self.assertEqual(self.server.rows(), [])

    def test_failed_file_stays_and_is_rolled_back(self):
        good = self.write_log('bot-a', '20261011100001', [('2026-10-11 10:00:01', 'INFO', 'fine')])
        bad = self.write_log('bot-b', '20261011110000', [('2026-10-11 11:00:00', 'INFO', 'x'), ('2026-10-11 11:00:01', 'INFO', 'BOOM')])
        self.server.fail_on = 'BOOM'
        result = self.database().upload(self.watch, [], lambda **d: None)
        self.assertEqual((result['files'], result['failed']), (1, 1))
        self.assertIn('20261011110000.txt', result['error'])
        self.assertFalse(os.path.exists(good))
        self.assertTrue(os.path.exists(bad))
        self.assertEqual([r[4] for r in self.server.rows()], ['fine'])

    def test_retry_does_not_duplicate_and_claimed_files_are_resumed(self):
        lines = [('2026-10-11 10:00:01', 'INFO', 'one'), ('2026-10-11 10:00:02', 'INFO', 'two')]
        self.write_log('bot-a', '20261011100001', lines)
        self.database().upload(self.watch, [], lambda **d: None)
        # the same run again, left claimed by an upload that was interrupted after the commit
        path = self.write_log('bot-a', '20261011100001', lines)
        os.rename(path, path + m.UPLOAD_SUFFIX)
        result = self.database().upload(self.watch, [], lambda **d: None)
        self.assertEqual(result['files'], 1)
        self.assertEqual([r[4] for r in self.server.rows()], ['one', 'two'])
        self.assertEqual(os.listdir(self.watch), [])


class TestQuery(LogDbTestCase):

    def setUp(self):
        super().setUp()
        self.write_log('bot-a', '20261010090000', [('2026-10-10 09:00:00', 'INFO', 'old day')])
        self.write_log('bot-a', '20261011100001', [('2026-10-11 10:00:01', 'INFO', 'hello'), ('2026-10-11 10:00:02', 'ERROR', 'it failed')])
        self.write_log('bot-b', '20261011110000', [('2026-10-11 11:00:00', 'WARNING', 'careful'), ('2026-10-11 11:00:01', 'INFO', 'bye')])
        self.database().upload(self.watch, [], lambda **d: None)

    def test_newest_first_with_limit(self):
        result = self.database().query({})
        self.assertEqual([r[4] for r in result['rows']], ['bye', 'careful', 'it failed'])
        self.assertTrue(result['more'])
        self.assertEqual(result['processes'], ['bot-a', 'bot-b'])

    def test_filters(self):
        query = self.database().query
        self.assertEqual([r[4] for r in query({'level': 'ERROR'})['rows']], ['it failed'])
        self.assertEqual([r[4] for r in query({'process': 'bot-a', 'text': 'ell'})['rows']], ['hello'])
        result = query({'date_from': '2026-10-10', 'date_to': '2026-10-10'})
        self.assertEqual([r[4] for r in result['rows']], ['old day'])
        self.assertFalse(result['more'])
        self.assertEqual(result['rows'][0][:4], ['2026-10-10 09:00:00', 'bot-a', '20261010090000', 'INFO'])


if __name__ == '__main__':
    unittest.main()
