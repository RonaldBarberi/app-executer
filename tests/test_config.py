import os, sys, json, tempfile, unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
from main import ProjectConfig


JSON_TEXT = '''{
    "SQL_SCHEMA": "bbdd_a",
    "TIMEOUT": 600,
    "ENABLED": true,
    "LIST_MARKETS": ["A", "B"],
    "ARGS_TB": {"tb_x": {"keys": ["id"]}},
    "LAST": null
}
'''

ENV_TEXT = 'OWNER_USER="user@x.com"\nOWNER_PASSWORD=abc\n# comment\nURL=http://x # inline\nexport TOKEN=\'t\'\n'


class TestProjectConfig(unittest.TestCase):

    def test_update_json_keeps_other_formatting(self):
        new = ProjectConfig.update_json(JSON_TEXT, {'TIMEOUT': 900, 'SQL_SCHEMA': 'bbdd_b'})
        self.assertEqual(new, JSON_TEXT.replace('600', '900').replace('bbdd_a', 'bbdd_b'))

    def test_update_json_nested_value(self):
        new = ProjectConfig.update_json(JSON_TEXT, {'LIST_MARKETS': ['A', 'B', 'C']})
        self.assertEqual(new, JSON_TEXT.replace('["A", "B"]', '["A", "B", "C"]'))

    def test_update_json_multiline_value_stays_multiline(self):
        text = '{\n    "A": [\n        1,\n        2\n    ],\n    "B": 1\n}'
        new = ProjectConfig.update_json(text, {'A': [1, 2, 3]})
        self.assertEqual(new, '{\n    "A": [\n        1,\n        2,\n        3\n    ],\n    "B": 1\n}')

    def test_update_json_last_key_and_types(self):
        new = json.loads(ProjectConfig.update_json(JSON_TEXT, {'LAST': 'x', 'ENABLED': False}))
        self.assertEqual((new['LAST'], new['ENABLED']), ('x', False))

    def test_parse_env(self):
        parsed = {k: (v, q) for k, v, q in ProjectConfig.parse_env(ENV_TEXT)}
        self.assertEqual(parsed, {
            'OWNER_USER': ('user@x.com', '"'),
            'OWNER_PASSWORD': ('abc', ''),
            'URL': ('http://x', ''),
            'TOKEN': ('t', "'"),
        })

    def test_update_env_keeps_quotes_and_lines(self):
        new = ProjectConfig.update_env(ENV_TEXT, {'OWNER_USER': 'other@x.com', 'OWNER_PASSWORD': 'a b'})
        self.assertEqual(new.splitlines(), [
            'OWNER_USER="other@x.com"', 'OWNER_PASSWORD="a b"', '# comment', 'URL=http://x # inline', "export TOKEN='t'"])

    def test_update_env_keeps_crlf(self):
        new = ProjectConfig.update_env('A=1\r\nB=2\r\n', {'A': '3'})
        self.assertEqual(new, 'A=3\r\nB=2\r\n')

    def test_load_overrides_and_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            projects = os.path.join(tmp, 'projects')
            path = os.path.join(projects, 'bot')
            os.makedirs(os.path.join(path, 'src'))
            os.makedirs(os.path.join(path, 'config'))
            os.makedirs(os.path.join(tmp, 'common'))
            with open(os.path.join(path, 'src', 'main.py'), 'w') as f:
                f.write("def main():\n    filename_args_json = '../config/config.json'\n"
                        "    filename_args_env = ['../../../common/.env', '../config/.env']\n")
            with open(os.path.join(path, 'config', 'config.json'), 'w') as f:
                f.write(JSON_TEXT)
            with open(os.path.join(tmp, 'common', '.env'), 'w') as f:
                f.write('SQL_SCHEMA="from_common"\nOWNER_PASSWORD="p"\n')
            with open(os.path.join(path, 'config', '.env'), 'w') as f:
                f.write('OWNER_PASSWORD=q\n')

            project = {'name': 'bot', 'path': path, 'main': os.path.join(path, 'src', 'main.py')}
            cfg = ProjectConfig(project, projects)
            self.assertEqual([f['label'] for f in cfg.files], ['config/config.json', 'common/.env', 'config/.env'])
            self.assertEqual([f['shared'] for f in cfg.files], [False, True, False])
            self.assertEqual(cfg.files[0]['entries']['SQL_SCHEMA']['overridden_by'], 'common/.env')
            self.assertEqual(cfg.files[1]['entries']['OWNER_PASSWORD']['overridden_by'], 'config/.env')
            self.assertTrue(cfg.files[2]['entries']['OWNER_PASSWORD']['secret'])

            cfg.files[0]['entries']['TIMEOUT']['value'] = 30
            cfg.files[2]['entries']['OWNER_PASSWORD']['value'] = 'new'
            self.assertEqual(len(cfg.changes()), 2)
            cfg.save()
            with open(os.path.join(path, 'config', 'config.json')) as f:
                self.assertEqual(f.read(), JSON_TEXT.replace('600', '30'))
            with open(os.path.join(path, 'config', '.env')) as f:
                self.assertEqual(f.read(), 'OWNER_PASSWORD=new\n')
            with open(os.path.join(tmp, 'common', '.env')) as f:
                self.assertEqual(f.read(), 'SQL_SCHEMA="from_common"\nOWNER_PASSWORD="p"\n')

    def test_save_refuses_file_changed_on_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'projects', 'bot')
            os.makedirs(os.path.join(path, 'src'))
            os.makedirs(os.path.join(path, 'config'))
            with open(os.path.join(path, 'src', 'main.py'), 'w') as f:
                f.write("Pipeline(filename_args_json='../config/config.json')\n")
            cfg_path = os.path.join(path, 'config', 'config.json')
            with open(cfg_path, 'w') as f:
                f.write(JSON_TEXT)
            cfg = ProjectConfig({'name': 'bot', 'path': path, 'main': os.path.join(path, 'src', 'main.py')}, os.path.join(tmp, 'projects'))
            self.assertFalse(cfg.files[1]['exists'])
            cfg.files[0]['entries']['TIMEOUT']['value'] = 1
            os.utime(cfg_path, (1, 1))
            with self.assertRaises(ValueError):
                cfg.save()


if __name__ == '__main__':
    unittest.main()
