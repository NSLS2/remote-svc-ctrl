"""Shared test configuration and fixtures."""

import os

import pytest


@pytest.fixture(scope="session", autouse=True)
def configure_epics_environment():
    """Restrict all EPICS CA/PVA traffic to localhost to avoid test failures
    caused by firewalls or other network issues.
    """
    os.environ["EPICS_CAS_INTF_ADDR_LIST"] = "127.0.0.1"
    os.environ["EPICS_CAS_BEACON_ADDR_LIST"] = "127.0.0.1"
    os.environ["EPICS_CA_ADDR_LIST"] = "127.0.0.1"
    os.environ["EPICS_CAS_AUTO_ADDR_LIST"] = "NO"
    os.environ["EPICS_CA_AUTO_BEACON_ADDR_LIST"] = "NO"
    os.environ["EPICS_PVAS_INTF_ADDR_LIST"] = "127.0.0.1"
    os.environ["EPICS_PVAS_BEACON_ADDR_LIST"] = "127.0.0.1"
    os.environ["EPICS_PVA_ADDR_LIST"] = "127.0.0.1"
    os.environ["EPICS_PVAS_AUTO_BEACON_ADDR_LIST"] = "NO"
    os.environ["EPICS_PVA_AUTO_ADDR_LIST"] = "NO"
