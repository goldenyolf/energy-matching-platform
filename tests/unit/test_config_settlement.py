from app.core.config import Settings


def test_settlement_defaults():
    s = Settings()
    assert s.wheeling_fee_per_kwh == 0.1
    assert s.grid_emission_factor_kg_per_kwh == 0.494
