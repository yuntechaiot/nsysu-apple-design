import pytest

from nsysu.store import Store, diary_email, login


def test_username_login_maps_identity_and_keeps_password_case(monkeypatch):
    calls = []
    def request(self, method, path, payload=None, params=None):
        calls.append((method, path, payload))
        return {'access_token': 'SYNTHETIC', 'user': {'app_metadata': {'diary_staff': True}}}
    monkeypatch.setattr(Store, 'request', request)
    assert login(' research_test ', 'CaseSensitive')['access_token'] == 'SYNTHETIC'
    assert calls == [('POST', '/auth/v1/token?grant_type=password', {'email': 'research_test@diary.nsysu.invalid', 'password': 'CaseSensitive'})]


def test_nonstaff_and_user_editable_metadata_do_not_grant_login(monkeypatch):
    monkeypatch.setattr(Store, 'request', lambda *a, **k: {'user': {'app_metadata': {}, 'user_metadata': {'diary_staff': True}}})
    with pytest.raises(ValueError, match='權限'):
        login('RESEARCH_TEST', 'SYNTHETIC')


@pytest.mark.parametrize('account', ['', 'name@example.invalid', '../admin', '<script>', 'x' * 33])
def test_invalid_account_is_rejected_before_network(account):
    with pytest.raises(ValueError):
        diary_email(account)
