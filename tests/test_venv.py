import os, sys, tempfile, unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
from main import find_venv


class TestFindVenv(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def make_venv(self, folder, cfg=True):
        scripts = os.path.join(self.path, folder, 'Scripts')
        os.makedirs(scripts)
        open(os.path.join(scripts, 'python.exe'), 'w').close()
        if cfg:
            open(os.path.join(self.path, folder, 'pyvenv.cfg'), 'w').close()
        return os.path.join(self.path, folder)

    def test_prefers_standard_name(self):
        self.make_venv('.venv')
        expected = self.make_venv('venv-bot')
        self.assertEqual(find_venv(self.path, 'bot'), expected)

    def test_any_name(self):
        for folder in ('.venv', 'venv', 'env', 'venv-other-name'):
            with self.subTest(folder=folder), tempfile.TemporaryDirectory() as tmp:
                self.path = tmp
                expected = self.make_venv(folder)
                self.assertEqual(find_venv(tmp, 'bot'), expected)

    def test_ignores_folders_that_are_not_venvs(self):
        self.make_venv('src', cfg=False)
        self.assertEqual(find_venv(self.path, 'bot'), os.path.join(self.path, 'venv-bot'))

    def test_no_venv_falls_back_to_standard_name(self):
        self.assertEqual(find_venv(self.path, 'bot'), os.path.join(self.path, 'venv-bot'))


if __name__ == '__main__':
    unittest.main()
