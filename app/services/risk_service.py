"""Contract risk alerts — projection over contracts + the matching outcome."""

from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Contract, Customer, WindFarm
from app.models.enums import ContractStatus
from app.schemas.risk import RiskAlert, RiskCounts, RiskReport
from app.services.matching_service import compute_outcome

_SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}


def _add_months(d: date, months: int) -> date:
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def compute_contract_risks(
    db: Session, period: str, *, reference_date: date, horizon_months: int
) -> RiskReport:
    contracts = list(db.execute(select(Contract)).scalars())
    farms = {f.id: f for f in db.execute(select(WindFarm)).scalars()}
    custs = {c.id: c for c in db.execute(select(Customer)).scalars()}
    horizon_end = _add_months(reference_date, horizon_months)

    def fcode(c: Contract) -> str | None:
        f = farms.get(c.wind_farm_id)
        return f.code if f else None

    def ccode(c: Contract) -> str | None:
        cu = custs.get(c.customer_id)
        return cu.code if cu else None

    alerts: list[RiskAlert] = []

    for c in contracts:
        # Rule 1: expiry
        if (
            c.status == ContractStatus.ACTIVE
            and reference_date <= c.end_date <= horizon_end
        ):
            days = (c.end_date - reference_date).days
            sev = "high" if days <= 31 else ("medium" if days <= 92 else "low")
            alerts.append(
                RiskAlert(
                    severity=sev,
                    category="expiry",
                    contract_number=c.contract_number,
                    wind_farm_code=fcode(c),
                    customer_code=ccode(c),
                    title="合約即將到期",
                    detail=(
                        f"{c.contract_number} 於 {c.end_date.isoformat()} "
                        f"到期(約 {days} 天後)。"
                    ),
                    suggested_action="評估提前洽談續約或尋找替代綠電來源。",
                )
            )
        # Rule 4: status mismatch
        if c.end_date < reference_date and c.status == ContractStatus.ACTIVE:
            alerts.append(
                RiskAlert(
                    severity="medium",
                    category="status_mismatch",
                    contract_number=c.contract_number,
                    wind_farm_code=fcode(c),
                    customer_code=ccode(c),
                    title="狀態不一致:已過期仍為有效",
                    detail=(
                        f"{c.contract_number} 已於 {c.end_date.isoformat()} "
                        f"過期,狀態仍為 active。"
                    ),
                    suggested_action="更新合約狀態為 expired,或辦理續約。",
                )
            )
        elif c.start_date <= reference_date and c.status == ContractStatus.PENDING:
            alerts.append(
                RiskAlert(
                    severity="medium",
                    category="status_mismatch",
                    contract_number=c.contract_number,
                    wind_farm_code=fcode(c),
                    customer_code=ccode(c),
                    title="狀態不一致:已到生效日仍待生效",
                    detail=(
                        f"{c.contract_number} 生效日 {c.start_date.isoformat()} "
                        f"已到,狀態仍為 pending。"
                    ),
                    suggested_action="確認是否已生效並更新狀態為 active。",
                )
            )

    # Rule 3: over-commitment (per farm Σ active %)
    farm_pct: dict[int, float] = defaultdict(float)
    for c in contracts:
        if c.status == ContractStatus.ACTIVE and c.contracted_percentage:
            farm_pct[c.wind_farm_id] += c.contracted_percentage
    for fid, total in farm_pct.items():
        if total > 100.0:
            f = farms.get(fid)
            sev = "high" if total > 120.0 else "medium"
            alerts.append(
                RiskAlert(
                    severity=sev,
                    category="over_commitment",
                    contract_number=None,
                    wind_farm_code=(f.code if f else None),
                    customer_code=None,
                    title="風場超額承諾",
                    detail=(
                        f"風場 {f.code if f else fid} 有效合約承諾比例合計 "
                        f"{round(total, 1)}%,超過 100%。"
                    ),
                    suggested_action="檢視合約組合,避免超賣導致供電不足。",
                )
            )

    # Rule 2: under-delivery (period matching)
    outcome = compute_outcome(db, period)
    delivered = {a.contract_id: a.allocated_mwh for a in outcome.allocations}
    farm_gen = {f.farm_id: f.generated_mwh for f in outcome.farm_summaries}
    for c in contracts:
        if c.status != ContractStatus.ACTIVE:
            continue
        caps: list[float] = []
        if c.contracted_energy_mwh:
            caps.append(c.contracted_energy_mwh)
        if c.contracted_percentage:
            caps.append(
                c.contracted_percentage / 100.0 * farm_gen.get(c.wind_farm_id, 0.0)
            )
        if not caps:
            continue
        expected = min(caps)
        if expected <= 0:
            continue
        dv = delivered.get(c.id, 0.0)
        short_pct = (expected - dv) / expected * 100.0
        if short_pct > 5.0:
            sev = (
                "high" if short_pct >= 50 else ("medium" if short_pct >= 20 else "low")
            )
            alerts.append(
                RiskAlert(
                    severity=sev,
                    category="under_delivery",
                    contract_number=c.contract_number,
                    wind_farm_code=fcode(c),
                    customer_code=ccode(c),
                    title="供電不足",
                    detail=(
                        f"{c.contract_number} 於 {period} 實送 {round(dv, 1)} MWh,"
                        f"低於預期上限 {round(expected, 1)} MWh"
                        f"(缺口 {round(short_pct, 1)}%)。"
                    ),
                    suggested_action="檢視優先序或增加供給,以滿足合約電量。",
                )
            )

    alerts.sort(key=lambda a: (_SEVERITY_RANK[a.severity], a.category))
    counts = RiskCounts(
        high=sum(1 for a in alerts if a.severity == "high"),
        medium=sum(1 for a in alerts if a.severity == "medium"),
        low=sum(1 for a in alerts if a.severity == "low"),
        total=len(alerts),
    )
    return RiskReport(
        period=period,
        reference_date=reference_date.isoformat(),
        horizon_months=horizon_months,
        counts=counts,
        alerts=alerts,
    )
