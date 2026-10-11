import os, sys, unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
from main import RunView


class TestParsers(unittest.TestCase):

    def test_tqdm_with_desc(self):
        line = 'download_falabella_data:  45%|████▌     | 45/100 [00:10<00:12,  4.50it/s]'
        self.assertEqual(RunView.parse_tqdm(line), {'desc': 'download_falabella_data', 'pct': 45, 'n': '45', 'total': '100'})

    def test_tqdm_without_desc_ascii(self):
        line = ' 100%|##########| 3/3 [00:01<00:00,  2.00it/s]'
        self.assertEqual(RunView.parse_tqdm(line), {'desc': '', 'pct': 100, 'n': '3', 'total': '3'})

    def test_tqdm_ignores_plain_text(self):
        self.assertIsNone(RunView.parse_tqdm('Traceback (most recent call last):'))
        self.assertIsNone(RunView.parse_tqdm('download: 4'))

    def test_log_line(self):
        line = 'rpa-bot-x§20261008145557§2026-10-08 14:55:59§ERROR§step 1/2 failed: a§b\n'
        self.assertEqual(RunView.parse_log_line(line), {'time': '2026-10-08 14:55:59', 'level': 'ERROR', 'message': 'step 1/2 failed: a§b'})

    def test_log_line_invalid(self):
        self.assertIsNone(RunView.parse_log_line('free text'))

    def test_log_filter_by_level(self):
        self.assertTrue(RunView.log_matches('ERROR', 'ERROR', '2026-10-09 08:39:24', '[ERROR] step 3/3 failed'))
        self.assertTrue(RunView.log_matches('error', 'ERROR', '', '[ERROR] x'))
        # a level filter doesn't match other levels that only mention the word
        self.assertFalse(RunView.log_matches('ERROR', 'INFO', '', '[INFO] no error found'))
        self.assertTrue(RunView.log_matches('warn', 'WARNING', '', '[WARNING] x'))
        self.assertFalse(RunView.log_matches('ERROR', '', '', 'Traceback (most recent call last)'))

    def test_log_filter_by_text(self):
        self.assertTrue(RunView.log_matches('  ha_1 ', 'ERROR', '', '[ERROR] download not finished: 20261008_HA_1.zip'))
        self.assertTrue(RunView.log_matches('08:39', 'INFO', '2026-10-09 08:39:24', '[INFO] x'))
        self.assertTrue(RunView.log_matches('traceback', '', '', 'Traceback (most recent call last)'))
        self.assertFalse(RunView.log_matches('celulares', 'INFO', '', '[INFO] report HA_1 ok'))
        self.assertTrue(RunView.log_matches('', 'INFO', '', '[INFO] x'))

    def test_traceback_is_one_block(self):
        lines = ['Traceback (most recent call last):', '  File "x.py", line 3, in <module>', '    main()']
        self.assertTrue(RunView.continues_block(lines[:1], lines[1]))
        self.assertTrue(RunView.continues_block(lines, '             ^^^^^^'))
        # the exception line closes the traceback
        self.assertTrue(RunView.continues_block(lines, 'TimeoutError: download not finished'))
        self.assertFalse(RunView.continues_block(lines + ['TimeoutError: x'], 'pipeline finished'))
        self.assertFalse(RunView.continues_block(['some console text'], 'other console text'))

    def test_split_selenium_stacktrace(self):
        message = ('[WARNING] error to click tried (1/5): Message: no such element: Unable to locate element: '
                   '{"method":"xpath","selector":"//div[contains(@title, \'Get Variant\')]"} (Session info: chrome=154.0.8037.98); '
                   'For documentation on this error, please visit: https://www.selenium.dev/x#nosuchelementexception '
                   'Stacktrace: chromedriver!GetHandleVerifier [0x7ff67e849d55+5a55] chromedriver!(No symbol) [0x7ff67e76f540] '
                   'KERNEL32!BaseThreadInitThunk [0x7ffd150dcd87+17] ntdll!RtlUserThreadStart [0x7ffd1614caec+2c]')
        self.assertEqual(RunView.split_message(message), [
            '[WARNING] error to click tried (1/5): Message: no such element: Unable to locate element: '
            '{"method":"xpath","selector":"//div[contains(@title, \'Get Variant\')]"}',
            '(Session info: chrome=154.0.8037.98);',
            'For documentation on this error, please visit: https://www.selenium.dev/x#nosuchelementexception',
            'Stacktrace:',
            'chromedriver!GetHandleVerifier [0x7ff67e849d55+5a55]',
            'chromedriver!(No symbol) [0x7ff67e76f540]',
            'KERNEL32!BaseThreadInitThunk [0x7ffd150dcd87+17]',
            'ntdll!RtlUserThreadStart [0x7ffd1614caec+2c]',
        ])

    def test_split_python_traceback(self):
        message = ('[ERROR] failed [1] job.py: Traceback (most recent call last): File "C:\\x\\job.py", line 9, in <module> '
                   'main() File "C:\\x\\job.py", line 5, in main raise TimeoutError(\'download not finished\') '
                   'TimeoutError: download not finished')
        self.assertEqual(RunView.split_message(message), [
            '[ERROR] failed [1] job.py:',
            'Traceback (most recent call last):',
            'File "C:\\x\\job.py", line 9, in <module> main()',
            'File "C:\\x\\job.py", line 5, in main raise TimeoutError(\'download not finished\')',
            'TimeoutError: download not finished',
        ])

    def test_split_keeps_plain_messages(self):
        for message in ('[INFO] pipeline finished: 0/2 OK', '[ERROR] can not download data from SAP: No active exception to reraise',
                        '[INFO] done! next step'):
            self.assertEqual(RunView.split_message(message), [message])

    def test_format_elapsed(self):
        self.assertEqual(RunView.format_elapsed(3725.9), '01:02:05')


if __name__ == '__main__':
    unittest.main()
