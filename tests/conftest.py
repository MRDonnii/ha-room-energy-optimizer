"""Shared fixtures for Home Assistant integration tests."""

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(request):
    """Load custom_components/ in tests that run a Home Assistant instance.

    A recorder must exist before the hass fixture, so it is set up first.
    """
    if "recorder_mock" in request.fixturenames:
        request.getfixturevalue("recorder_mock")
    if "hass" in request.fixturenames:
        request.getfixturevalue("enable_custom_integrations")
    yield
