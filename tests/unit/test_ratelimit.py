"""Unit tests for the in-memory rate limiter and the solver factory."""

from __future__ import annotations

from app.core.ratelimit import RateLimiter
from app.matching.solver import cbc, configure_solver


def test_rate_limiter_allows_then_blocks_within_a_window():
    rl = RateLimiter(2)
    assert rl.check("ip", 0.0) is True  # 1
    assert rl.check("ip", 10.0) is True  # 2 (same minute)
    assert rl.check("ip", 30.0) is False  # 3 → over budget
    # a different key has its own budget
    assert rl.check("other", 30.0) is True
    # next minute resets
    assert rl.check("ip", 61.0) is True


def test_rate_limiter_zero_disables():
    rl = RateLimiter(0)
    assert all(rl.check("x", 0.0) for _ in range(1000))


def test_cbc_applies_configured_time_limit():
    try:
        configure_solver(7.5)
        assert cbc().timeLimit == 7.5
        assert cbc(exact=True).timeLimit == 7.5
        configure_solver(0)  # 0 / None disables the limit
        assert cbc().timeLimit is None
    finally:
        configure_solver(None)
