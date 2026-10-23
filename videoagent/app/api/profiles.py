"""API · Profile trình duyệt."""
from .. import browser_profiles

from .common import _fail, _ok


class ProfilesApi:
    # ------------------------------------------------------------------ profile trình duyệt
    def _profiles_call(self, fn, *args) -> dict:
        try:
            return _ok(profiles=fn(*args))
        except browser_profiles.ProfileError as exc:
            return _fail(exc)

    def profiles_list(self) -> dict:
        return _ok(profiles=browser_profiles.list_profiles())

    def profiles_create(self, name: str, sites: list, channel: str = "") -> dict:
        return self._profiles_call(browser_profiles.create, name, sites, channel)

    def profiles_update(self, profile_id: str, name=None, sites=None, channel=None) -> dict:
        return self._profiles_call(browser_profiles.update, profile_id, name, sites, channel)

    def profiles_delete(self, profile_id: str) -> dict:
        return self._profiles_call(browser_profiles.delete, profile_id)
