import unittest
from unittest.mock import Mock, patch

from api.tasks import RegisterTaskRequest, _create_task_record, _run_register, _task_store
from core.base_mailbox import BaseMailbox, MailboxAccount
from core.base_platform import Account, BasePlatform


class _FakeMailbox(BaseMailbox):
    def get_email(self) -> MailboxAccount:
        return MailboxAccount(email="demo@example.com")

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
        def poll_once():
            return None

        return self._run_polling_wait(
            timeout=timeout,
            poll_interval=0.01,
            poll_once=poll_once,
        )


class _FakePlatform(BasePlatform):
    name = "fake"
    display_name = "Fake"

    def __init__(self, config=None, mailbox=None):
        super().__init__(config)
        self.mailbox = mailbox

    def register(self, email: str, password: str = None) -> Account:
        account = self.mailbox.get_email()
        self.mailbox.wait_for_code(account, timeout=1)
        return Account(
            platform="fake",
            email=account.email,
            password=password or "pw",
        )

    def check_valid(self, account: Account) -> bool:
        return True


class _FakeLuckMailMailbox(_FakeMailbox):
    def __init__(self):
        self._purchase_id = 321
        self._token = "tok_demo"
        self.mark_purchase_result_tag = Mock()

    def get_email(self) -> MailboxAccount:
        return MailboxAccount(
            email="demo@example.com",
            account_id="tok_demo",
            extra={"purchase_id": self._purchase_id},
        )


class _FakeLuckMailSuccessPlatform(_FakePlatform):
    def register(self, email: str, password: str = None) -> Account:
        account = self.mailbox.get_email()
        return Account(
            platform="fake",
            email=account.email,
            password=password or "pw",
            extra={},
        )


class _FakeLuckMailFailPlatform(_FakePlatform):
    def register(self, email: str, password: str = None) -> Account:
        account = self.mailbox.get_email()
        raise RuntimeError(f"register failed for {account.email}")


class RegisterTaskControlFlowTests(unittest.TestCase):
    def _build_request(self):
        return RegisterTaskRequest(
            platform="fake",
            count=1,
            concurrency=1,
            proxy="http://proxy.local:8080",
            extra={"mail_provider": "fake"},
        )

    def _run_with_control(self, task_id: str, *, stop: bool = False, skip: bool = False):
        req = self._build_request()
        _create_task_record(task_id, req, "manual", None)
        if stop:
            _task_store.request_stop(task_id)
        if skip:
            _task_store.request_skip_current(task_id)

        with (
            patch("core.registry.get", return_value=_FakePlatform),
            patch("core.base_mailbox.create_mailbox", return_value=_FakeMailbox()),
            patch("core.db.save_account", side_effect=lambda account: account),
            patch("api.tasks._save_task_log"),
        ):
            _run_register(task_id, req)

        return _task_store.snapshot(task_id)

    def test_skip_current_marks_attempt_as_skipped(self):
        snapshot = self._run_with_control("task-control-skip", skip=True)

        self.assertEqual(snapshot["status"], "done")
        self.assertEqual(snapshot["success"], 0)
        self.assertEqual(snapshot["skipped"], 1)
        self.assertEqual(snapshot["errors"], [])

    def test_stop_marks_task_as_stopped(self):
        snapshot = self._run_with_control("task-control-stop", stop=True)

        self.assertEqual(snapshot["status"], "stopped")
        self.assertEqual(snapshot["success"], 0)
        self.assertEqual(snapshot["skipped"], 0)
        self.assertEqual(snapshot["errors"], [])

    def test_luckmail_success_marks_purchase_tag(self):
        req = RegisterTaskRequest(
            platform="fake",
            count=1,
            concurrency=1,
            proxy="http://proxy.local:8080",
            extra={"mail_provider": "luckmail"},
        )
        task_id = "task-luckmail-success"
        mailbox = _FakeLuckMailMailbox()
        proxy_pool = Mock()
        config_store = Mock()
        config_store.get_all.return_value = {}
        _create_task_record(task_id, req, "manual", None)

        with (
            patch("core.registry.get", return_value=_FakeLuckMailSuccessPlatform),
            patch("core.config_store.config_store", config_store),
            patch("core.proxy_pool.proxy_pool", proxy_pool),
            patch("core.base_mailbox.create_mailbox", return_value=mailbox),
            patch("core.db.save_account", side_effect=lambda account: account),
            patch("api.tasks._save_task_log"),
        ):
            _run_register(task_id, req)

        mailbox.mark_purchase_result_tag.assert_called_once_with(321, success=True)

    def test_luckmail_failure_marks_purchase_tag(self):
        req = RegisterTaskRequest(
            platform="fake",
            count=1,
            concurrency=1,
            proxy="http://proxy.local:8080",
            extra={"mail_provider": "luckmail"},
        )
        task_id = "task-luckmail-failed"
        mailbox = _FakeLuckMailMailbox()
        proxy_pool = Mock()
        config_store = Mock()
        config_store.get_all.return_value = {}
        _create_task_record(task_id, req, "manual", None)

        with (
            patch("core.registry.get", return_value=_FakeLuckMailFailPlatform),
            patch("core.config_store.config_store", config_store),
            patch("core.proxy_pool.proxy_pool", proxy_pool),
            patch("core.base_mailbox.create_mailbox", return_value=mailbox),
            patch("api.tasks._save_task_log"),
        ):
            _run_register(task_id, req)

        mailbox.mark_purchase_result_tag.assert_called_once_with(321, success=False)

    def test_luckmail_token_mode_does_not_mark_purchase_tag(self):
        req = RegisterTaskRequest(
            platform="fake",
            count=1,
            concurrency=1,
            proxy="http://proxy.local:8080",
            extra={"mail_provider": "luckmail_token"},
        )
        task_id = "task-luckmail-token"
        mailbox = _FakeLuckMailMailbox()
        proxy_pool = Mock()
        config_store = Mock()
        config_store.get_all.return_value = {}
        _create_task_record(task_id, req, "manual", None)

        with (
            patch("core.registry.get", return_value=_FakeLuckMailSuccessPlatform),
            patch("core.config_store.config_store", config_store),
            patch("core.proxy_pool.proxy_pool", proxy_pool),
            patch("core.base_mailbox.create_mailbox", return_value=mailbox),
            patch("core.db.save_account", side_effect=lambda account: account),
            patch("api.tasks._save_task_log"),
        ):
            _run_register(task_id, req)

        mailbox.mark_purchase_result_tag.assert_not_called()


if __name__ == "__main__":
    unittest.main()
