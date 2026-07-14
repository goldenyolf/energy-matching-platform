"""綠電媒合引擎：比例分配 + RE 目標分析。

演算法概念
==========
1. 每個案場 (WindFarm) 有固定的年發電量。
2. 綁在該案場上的每張合約會產生一筆「需求電量」：
   - ratio  合約：需求 = value * 案場年發電量
   - volume 合約：需求 = value (MWh)
3. 若某案場的合約需求總和 <= 年發電量 → 每張合約拿到全額需求，
   其餘為剩餘綠電 (surplus)。
4. 若需求總和 > 年發電量 (超額認購) → 依需求比例等比削減 (proportional
   curtailment)，讓分配總量剛好等於年發電量。
5. 彙整到企業層級後，計算 RE 覆蓋率與距離 RE 目標的缺口。

此模組為純函式、無副作用，方便單元測試。
"""

from __future__ import annotations

from collections import defaultdict

from .models import (
    AllocationType,
    CompanyResult,
    Contract,
    ContractAllocation,
    Dataset,
    MatchingResult,
    PlatformSummary,
    WindFarm,
    WindFarmResult,
)

# 浮點誤差容忍值 (MWh)
_EPS = 1e-6


def _requested_mwh(contract: Contract, farm: WindFarm) -> float:
    """依合約類型換算成需求電量 (MWh)。"""
    if contract.allocation_type == AllocationType.RATIO:
        return contract.value * farm.annual_generation_mwh
    return contract.value


def match(dataset: Dataset) -> MatchingResult:
    """執行綠電媒合並回傳完整分析結果。

    Raises:
        ValueError: 合約引用了不存在的案場或企業。
    """
    farms_by_id = {f.id: f for f in dataset.wind_farms}
    companies_by_id = {c.id: c for c in dataset.companies}

    # 驗證外鍵並依案場分組
    contracts_by_farm: dict[str, list[Contract]] = defaultdict(list)
    for contract in dataset.contracts:
        if contract.wind_farm_id not in farms_by_id:
            raise ValueError(
                f"合約 {contract.id} 引用了不存在的案場 {contract.wind_farm_id}"
            )
        if contract.company_id not in companies_by_id:
            raise ValueError(
                f"合約 {contract.id} 引用了不存在的企業 {contract.company_id}"
            )
        contracts_by_farm[contract.wind_farm_id].append(contract)

    allocations: list[ContractAllocation] = []
    allocated_by_company: dict[str, float] = defaultdict(float)
    allocated_by_farm: dict[str, float] = defaultdict(float)

    # 逐案場分配
    for farm in dataset.wind_farms:
        farm_contracts = contracts_by_farm.get(farm.id, [])
        requests = {c.id: _requested_mwh(c, farm) for c in farm_contracts}
        total_requested = sum(requests.values())

        oversubscribed = total_requested > farm.annual_generation_mwh + _EPS
        scale = (
            farm.annual_generation_mwh / total_requested
            if oversubscribed and total_requested > 0
            else 1.0
        )

        for contract in farm_contracts:
            requested = requests[contract.id]
            allocated = requested * scale
            allocations.append(
                ContractAllocation(
                    contract_id=contract.id,
                    company_id=contract.company_id,
                    wind_farm_id=contract.wind_farm_id,
                    requested_mwh=round(requested, 6),
                    allocated_mwh=round(allocated, 6),
                    curtailed=oversubscribed,
                )
            )
            allocated_by_company[contract.company_id] += allocated
            allocated_by_farm[farm.id] += allocated

    company_results = _build_company_results(dataset, allocated_by_company)
    wind_farm_results = _build_farm_results(dataset, allocated_by_farm)
    summary = _build_summary(company_results, wind_farm_results)

    return MatchingResult(
        allocations=allocations,
        company_results=company_results,
        wind_farm_results=wind_farm_results,
        summary=summary,
    )


def _build_company_results(
    dataset: Dataset, allocated_by_company: dict[str, float]
) -> list[CompanyResult]:
    results: list[CompanyResult] = []
    for company in dataset.companies:
        allocated = allocated_by_company.get(company.id, 0.0)
        coverage = allocated / company.annual_consumption_mwh
        gap = max(0.0, company.re_target_mwh - allocated)
        results.append(
            CompanyResult(
                company_id=company.id,
                name=company.name,
                annual_consumption_mwh=company.annual_consumption_mwh,
                re_target_ratio=company.re_target_ratio,
                re_target_mwh=round(company.re_target_mwh, 6),
                allocated_mwh=round(allocated, 6),
                coverage_ratio=round(coverage, 6),
                target_gap_mwh=round(gap, 6),
                target_met=gap <= _EPS,
            )
        )
    return results


def _build_farm_results(
    dataset: Dataset, allocated_by_farm: dict[str, float]
) -> list[WindFarmResult]:
    results: list[WindFarmResult] = []
    for farm in dataset.wind_farms:
        allocated = allocated_by_farm.get(farm.id, 0.0)
        surplus = max(0.0, farm.annual_generation_mwh - allocated)
        utilization = allocated / farm.annual_generation_mwh
        results.append(
            WindFarmResult(
                wind_farm_id=farm.id,
                name=farm.name,
                annual_generation_mwh=farm.annual_generation_mwh,
                allocated_mwh=round(allocated, 6),
                surplus_mwh=round(surplus, 6),
                utilization_ratio=round(utilization, 6),
                oversubscribed=utilization >= 1.0 - _EPS,
            )
        )
    return results


def _build_summary(
    company_results: list[CompanyResult],
    wind_farm_results: list[WindFarmResult],
) -> PlatformSummary:
    total_generation = sum(f.annual_generation_mwh for f in wind_farm_results)
    total_allocated = sum(f.allocated_mwh for f in wind_farm_results)
    total_surplus = sum(f.surplus_mwh for f in wind_farm_results)
    total_gap = sum(c.target_gap_mwh for c in company_results)
    met = sum(1 for c in company_results if c.target_met)

    utilization = (
        total_allocated / total_generation if total_generation > 0 else 0.0
    )
    return PlatformSummary(
        total_generation_mwh=round(total_generation, 6),
        total_allocated_mwh=round(total_allocated, 6),
        total_surplus_mwh=round(total_surplus, 6),
        utilization_ratio=round(utilization, 6),
        total_target_gap_mwh=round(total_gap, 6),
        companies_meeting_target=met,
        company_count=len(company_results),
    )
