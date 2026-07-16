from app.core.config import Settings


def test_economics_defaults():
    s = Settings()
    assert s.grey_price_per_kwh == 3.0
    assert s.default_feed_in_price_per_kwh == 4.0
