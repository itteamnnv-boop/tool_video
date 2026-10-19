import unittest

from app.seedance.notices import classify_notice


class NoticeTests(unittest.TestCase):
    def test_concurrency_limit_is_not_daily_quota(self):
        for text in ('Chỉ có thể tạo tối đa 2 video cùng lúc', 'You can only generate 2 videos at a time.'):
            self.assertEqual(classify_notice(text), 'CONCURRENCY_LIMIT')

    def test_credit_daily_and_generic_account_limits_are_separate(self):
        self.assertEqual(classify_notice('Not enough credits to generate a video.'), 'INSUFFICIENT_CREDITS')
        self.assertEqual(classify_notice('Daily limit reached. Try again tomorrow.'), 'DAILY_LIMIT')
        self.assertEqual(classify_notice('Account limit reached.'), 'ACCOUNT_LIMIT')
        self.assertEqual(classify_notice('Quota exceeded.'), 'ACCOUNT_LIMIT')
        self.assertEqual(classify_notice('Too many requests. Try again in 30 seconds.'), 'RATE_LIMIT')

    def test_unrelated_video_content_does_not_trigger_limit(self):
        self.assertIsNone(classify_notice('Create two videos of a boat.'))
        self.assertIsNone(classify_notice('Your video is ready to download.'))


if __name__ == '__main__':
    unittest.main()
