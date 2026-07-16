from app.core.config import Settings


def test_economics_defaults():
    s = Settings()
    assert s.grey_price_per_kwh == 3.0
    assert s.default_feed_in_price_per_kwh == 4.0


def test_optimization_defaults_present():
    from app.core.config import Settings

    s = Settings()
    assert s.optimize_min_sites_per_customer == 0
    assert s.optimize_min_site_allocation_percent == 0.0


def test_pulp_importable_with_cbc():
    import pulp

    solver = pulp.PULP_CBC_CMD(msg=0, threads=1)
    assert solver.available()
