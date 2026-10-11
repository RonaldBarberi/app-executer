import os, sys, json, unittest
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
from main import CronExpression, LocalizedError

with open(os.path.join(os.path.dirname(__file__), '..', 'config', 'i18n.json'), encoding='utf-8') as f:
    I18N = json.load(f)


def t_for(lang):
    return lambda key, **params: I18N[lang][key].format(**params)


class TestCronExpression(unittest.TestCase):

    def test_next_after_same_and_next_day(self):
        cron = CronExpression('0 10 * * *')
        self.assertEqual(cron.next_after(datetime(2026, 10, 9, 9, 30)), datetime(2026, 10, 9, 10, 0))
        self.assertEqual(cron.next_after(datetime(2026, 10, 9, 10, 0)), datetime(2026, 10, 10, 10, 0))

    def test_steps_between(self):
        cron = CronExpression('*/15 * * * *')
        self.assertEqual(cron.between(datetime(2026, 10, 9, 10, 0), datetime(2026, 10, 9, 11, 0)),
                         [datetime(2026, 10, 9, 10, m) for m in (15, 30, 45)] + [datetime(2026, 10, 9, 11, 0)])

    def test_weekdays_skip_weekend(self):
        # 2026-10-09 is a Friday
        cron = CronExpression('0 6-22/2 * * 1-5')
        self.assertEqual(cron.next_after(datetime(2026, 10, 9, 22, 30)), datetime(2026, 10, 12, 6, 0))
        self.assertEqual(cron.next_after(datetime(2026, 10, 9, 7, 0)), datetime(2026, 10, 9, 8, 0))

    def test_names_and_sunday_as_7(self):
        cron = CronExpression('30 8 * jan,JUL MON-FRI')
        self.assertEqual((cron.months, cron.weekdays), ({1, 7}, {1, 2, 3, 4, 5}))
        self.assertEqual(CronExpression('0 0 * * 7').weekdays, {0})

    def test_day_fields_or_when_both_restricted(self):
        cron = CronExpression('0 0 1 * MON')
        self.assertEqual(cron.next_after(datetime(2026, 10, 9)), datetime(2026, 10, 12))
        self.assertEqual(cron.next_after(datetime(2026, 10, 26, 1)), datetime(2026, 11, 1))

    def test_day_fields_and_when_one_starts_with_star(self):
        # Vixie cron: '*/2' counts as '*', so odd days AND Mondays (Oct 2026: Mondays 5, 12, 19, 26)
        self.assertEqual(CronExpression('0 0 */2 * MON').next_after(datetime(2026, 10, 1)), datetime(2026, 10, 5))

    def test_leap_day_and_impossible_date(self):
        self.assertEqual(CronExpression('0 0 29 2 *').next_after(datetime(2026, 3, 1)), datetime(2028, 2, 29))
        self.assertIsNone(CronExpression('0 0 30 2 *').next_after(datetime(2026, 1, 1)))

    def test_macros_and_upcoming(self):
        cron = CronExpression('@daily')
        self.assertEqual(cron.upcoming(datetime(2026, 10, 9, 12), 2), [datetime(2026, 10, 10), datetime(2026, 10, 11)])

    def test_invalid_expressions(self):
        for text, key in (('0 10 * *', 'cron.invalid_fields'), ('61 * * * *', 'cron.invalid_value'),
                          ('*/0 * * * *', 'cron.invalid_value'), ('0 5-1 * * *', 'cron.invalid_value'),
                          ('0 10 * * FUNDAY', 'cron.invalid_value'), ('0 10 0 * *', 'cron.invalid_value')):
            with self.assertRaises(LocalizedError, msg=text) as ctx:
                CronExpression(text)
            self.assertEqual(ctx.exception.key, key, text)

    def test_describe_english(self):
        t = t_for('en')
        cases = {
            '0 10,15,18,22 * * *': 'At 10:00, 15:00, 18:00, 22:00  ·  every day',
            '0 6-22/2 * * 1-5': 'Every 2 h from 06:00 to 22:00  ·  Mon–Fri',
            '*/15 * * * *': 'Every 15 minutes  ·  every day',
            '* * * * *': 'Every minute  ·  every day',
            '30 8 1,15 * *': 'At 08:30  ·  on day 1, 15 of the month',
            '0 9 * 1,7 MON': 'At 09:00  ·  Mon  ·  in Jan, Jul',
            '0 0 1 * MON': 'At 00:00  ·  on day 1 of the month or Mon',
            '0 0 30 2 *': 'Never runs (that date doesn\'t exist)',
            '7,8,9 1,2,3 * * *': '7,8,9 1,2,3 * * *',
        }
        for text, expected in cases.items():
            self.assertEqual(CronExpression(text).describe(t), expected, text)

    def test_describe_spanish(self):
        self.assertEqual(CronExpression('0 6-22/2 * * 1-5').describe(t_for('es')), 'Cada 2 h de 06:00 a 22:00  ·  lun–vie')


if __name__ == '__main__':
    unittest.main()
