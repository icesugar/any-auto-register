import unittest
from unittest.mock import patch

from core.base_mailbox import BaseMailbox, MailboxAccount


class _RetryMailbox(BaseMailbox):
    def __init__(self, failures_before_success: int):
        self.calls = 0
        self.failures_before_success = failures_before_success

    def get_email(self) -> MailboxAccount:
        self.calls += 1
        if self.calls <= self.failures_before_success:
            raise RuntimeError(f"no stock #{self.calls}")
        return MailboxAccount(email="demo@example.com", account_id="demo")

    def get_current_ids(self, account: MailboxAccount) -> set:
        return set()

    def wait_for_code(
        self,
        account: MailboxAccount,
        keyword: str = "",
        timeout: int = 120,
        before_ids: set = None,
        code_pattern: str = None,
        **kwargs,
    ) -> str:
        raise NotImplementedError


class BaseMailboxRetryTests(unittest.TestCase):
    @staticmethod
    def _mock_config_get(key: str, default: str = "") -> str:
        values = {
            "mailbox_get_retry_count": "2",
            "mailbox_get_retry_wait_seconds": "0",
        }
        return values.get(key, default)

    def test_acquire_email_retries_until_success(self):
        mailbox = _RetryMailbox(failures_before_success=2)

        with patch(
            "core.config_store.config_store.get",
            side_effect=self._mock_config_get,
        ):
            account = mailbox.acquire_email()

        self.assertEqual(mailbox.calls, 3)
        self.assertEqual(account.email, "demo@example.com")

    def test_acquire_email_raises_after_retry_limit(self):
        mailbox = _RetryMailbox(failures_before_success=3)

        with patch(
            "core.config_store.config_store.get",
            side_effect=self._mock_config_get,
        ):
            with self.assertRaisesRegex(RuntimeError, "no stock #3"):
                mailbox.acquire_email()

        self.assertEqual(mailbox.calls, 3)


if __name__ == "__main__":
    unittest.main()
