import os, re, json, string, unittest

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


def placeholders(text):
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


class TestI18n(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(BASE, 'config', 'config.json'), encoding='utf-8') as f:
            cls.config = json.load(f)
        with open(os.path.join(BASE, cls.config['I18N_FILE']), encoding='utf-8') as f:
            cls.i18n = json.load(f)
        with open(os.path.join(BASE, 'src', 'main.py'), encoding='utf-8') as f:
            cls.source = f.read()

    def test_default_language_is_english(self):
        self.assertEqual(self.config['LANGUAGE_DEFAULT'], 'en')
        self.assertIn('en', self.i18n)

    def test_same_keys_in_every_language(self):
        for lang, texts in self.i18n.items():
            self.assertEqual(set(texts), set(self.i18n['en']), f'{lang} differs from en')

    def test_same_placeholders_in_every_language(self):
        for lang, texts in self.i18n.items():
            for key, text in texts.items():
                self.assertEqual(placeholders(text), placeholders(self.i18n['en'][key]), f'{lang}.{key}')

    def test_every_key_used_in_code_exists(self):
        prefixes = sorted({key.split('.')[0] for key in self.i18n['en']})
        used = set(re.findall(r"'((?:%s)\.[\w.]+)'" % '|'.join(prefixes), self.source))
        # file names such as 'config.json' or 'main.py' share a prefix but aren't keys
        used = {key for key in used if not re.search(r'\.(json|py|env|txt|bat)$', key)}
        self.assertTrue(used)
        self.assertEqual(used - set(self.i18n['en']), set())

    def test_keys_built_in_code_exist(self):
        # f'hist.col_{col}', f'hist.status_{key}', f'sch.col_{col}', f'sch.driver_{status}' aren't literal in the code
        built = [f'hist.col_{c}' for c in ('start', 'bot', 'trigger', 'status', 'duration', 'code')]
        built += [f'hist.status_{k}' for k in ('all', 'running', 'succeeded', 'failed', 'aborted', 'missed', 'queued')]
        built += [f'sch.col_{c}' for c in ('bot', 'schedule', 'next', 'last', 'enabled')]
        built += [f'sch.driver_{s}' for s in ('ok', 'missing', 'disabled', 'moved')]
        built += [f'settings.var_{r}' for r in ('host', 'port', 'user', 'password')]
        built += [f'server.col_{c}' for c in ('time', 'process', 'run', 'level', 'message')]
        self.assertEqual([k for k in built if k not in self.i18n['en']], [])


if __name__ == '__main__':
    unittest.main()
