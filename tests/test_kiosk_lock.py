"""
Unit tests for core/kiosk_lock.py (KioskLockManager).
"""

from core.kiosk_lock import KioskLockManager


def test_kiosk_singleton():
    k1 = KioskLockManager.get_instance()
    k2 = KioskLockManager.get_instance()
    assert k1 is k2


def test_kiosk_lock_and_unlock_flow():
    mgr = KioskLockManager.get_instance()
    # Test locking with non-existent or test HWND string
    mgr.lock("NonExistentWindow_Test_12345")
    assert mgr._is_locked is True

    # Calling lock again while already locked should be a no-op
    mgr.lock("NonExistentWindow_Test_12345")
    assert mgr._is_locked is True

    # Test unlocking
    mgr.unlock()
    assert mgr._is_locked is False

    # Calling unlock again should be safe
    mgr.unlock()
    assert mgr._is_locked is False


def test_taskbars_visibility_toggle():
    mgr = KioskLockManager.get_instance()
    # Should execute safely without raising exceptions
    mgr._set_taskbars_visible(True)
    mgr._set_taskbars_visible(False)
    mgr._set_taskbars_visible(True)
