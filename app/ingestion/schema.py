"""匯入欄位表：importer、範本、UI 說明與錯誤訊息共用的單一真相。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Kind = Literal["str", "float", "int", "date", "enum", "shares"]


@dataclass(frozen=True)
class Column:
    name: str
    label: str
    kind: Kind
    required: bool = False
    example: str = ""
    note: str | None = None


@dataclass(frozen=True)
class EntitySpec:
    entity: str
    label: str
    natural_key: tuple[str, ...]
    columns: tuple[Column, ...]

    def column_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns)

    def required_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns if c.required)

    def column(self, name: str) -> Column | None:
        return next((c for c in self.columns if c.name == name), None)


FARM = EntitySpec(
    entity="farm",
    label="發電案場",
    natural_key=("code",),
    columns=(
        Column("code", "案場代碼", "str", required=True, example="WF-001"),
        Column("name", "案場名稱", "str", required=True, example="彰化外海一期"),
        Column("operator_name", "營運商", "str", example="示範能源"),
        Column("location", "場址", "str", example="彰化縣"),
        # WindFarmCreate 是 gt=0、沒有預設值的必填欄——標成 required 讓空白在
        # 這裡就被攔成清楚的中文訊息，不是留給 pydantic 丟英文例外。
        Column(
            "installed_capacity_mw",
            "裝置容量 (MW)",
            "float",
            required=True,
            example="100",
        ),
        Column("feed_in_price_per_kwh", "躉售價 (元/度)", "float", example="2.5"),
        Column(
            "commercial_operation_date",
            "商轉日",
            "date",
            example="2024-01-01",
            note="格式 YYYY-MM-DD",
        ),
        Column(
            "status",
            "狀態",
            "enum",
            example="operational",
            note="operational / under_construction / planned",
        ),
        Column(
            "farm_type",
            "類型",
            "enum",
            example="offshore",
            note="offshore（離岸）/ onshore（陸域）/ solar（太陽能）",
        ),
        Column("capacity_factor_percent", "容量因數 P50 (%)", "float", example="45"),
        Column(
            "p90_capacity_factor_percent", "容量因數 P90 (%)", "float", example="38"
        ),
        Column("turbine_count", "風機數", "int", example="20"),
        Column("grid_connection_voltage", "並網電壓", "str", example="161kV"),
    ),
)

CUSTOMER = EntitySpec(
    entity="customer",
    label="企業客戶",
    natural_key=("code",),
    columns=(
        Column("code", "客戶代碼", "str", required=True, example="CUS-001"),
        Column("company_name", "公司名稱", "str", required=True, example="示範半導體"),
        Column("industry", "產業", "str", example="半導體"),
        Column("annual_consumption_mwh", "年用電量 (MWh)", "float", example="120000"),
        Column("re_target_percent", "RE 目標 (%)", "float", example="30"),
        Column("target_year", "目標年", "int", example="2030"),
        Column(
            "green_target_type",
            "綠電目標型態",
            "enum",
            example="re_percent",
            note="re_percent（比例）/ energy_mwh（絕對量）",
        ),
        Column(
            "target_energy_mwh",
            "目標綠電量 (MWh)",
            "float",
            example="36000",
            note="green_target_type=energy_mwh 時才有意義",
        ),
    ),
)

METER = EntitySpec(
    entity="meter",
    label="電號／廠區",
    natural_key=("code",),
    columns=(
        Column(
            "customer_code",
            "所屬客戶代碼",
            "str",
            required=True,
            example="CUS-001",
            note="必須是已存在的客戶",
        ),
        Column("code", "電號", "str", required=True, example="MTR-001"),
        Column("name", "用電名稱", "str", example="一廠"),
        Column("location", "場址", "str", example="新竹科學園區"),
        Column("re_target_percent", "RE 目標 (%)", "float", example="30"),
        Column("annual_consumption_mwh", "年用電量 (MWh)", "float", example="60000"),
    ),
)

BATTERY = EntitySpec(
    entity="battery",
    label="客戶側儲能",
    natural_key=("code",),
    columns=(
        Column(
            "customer_code",
            "所屬客戶代碼",
            "str",
            required=True,
            example="CUS-001",
            note="必須是已存在的客戶",
        ),
        Column("code", "電池代碼", "str", required=True, example="BAT-001"),
        Column("name", "電池名稱", "str", example="一廠儲能"),
        # BatteryCreate 這兩欄是 gt=0、沒有預設值的必填欄——標成 required
        # 讓空白在這裡就被攔成清楚的中文訊息，不是留給 pydantic 丟英文例外。
        Column(
            "energy_capacity_mwh",
            "電量容量 (MWh)",
            "float",
            required=True,
            example="20",
        ),
        Column("power_mw", "功率 (MW)", "float", required=True, example="5"),
        Column("round_trip_efficiency_percent", "往返效率 (%)", "float", example="88"),
        Column("initial_soc_percent", "初始 SOC (%)", "float", example="0"),
    ),
)

CONTRACT = EntitySpec(
    entity="contract",
    label="綠電合約",
    natural_key=("contract_number",),
    columns=(
        Column(
            "contract_number", "合約編號", "str", required=True, example="PPA-2026-001"
        ),
        Column(
            "wind_farm_code",
            "案場代碼",
            "str",
            required=True,
            example="WF-001",
            note="必須是已存在的案場",
        ),
        Column(
            "customer_code",
            "客戶代碼",
            "str",
            required=True,
            example="CUS-001",
            note="必須是已存在的客戶",
        ),
        # ContractCreate 的 start_date / end_date 是沒有預設值的必填欄——標成
        # required 讓空白在這裡就被攔成清楚的中文訊息，不是留給 pydantic 丟英文
        # 例外。
        Column(
            "start_date",
            "起始日",
            "date",
            required=True,
            example="2026-01-01",
            note="格式 YYYY-MM-DD",
        ),
        Column(
            "end_date",
            "結束日",
            "date",
            required=True,
            example="2035-12-31",
            note="格式 YYYY-MM-DD",
        ),
        Column("contracted_energy_mwh", "年度合約量 (MWh)", "float", example="50000"),
        Column("contracted_percentage", "案場發電比例 (%)", "float", example="40"),
        Column("price_per_kwh", "售電價 (元/度)", "float", example="4.2"),
        Column("priority", "優先序", "int", example="100", note="數字小者優先分配"),
        Column(
            "status",
            "狀態",
            "enum",
            example="active",
            note="active / pending / expired / terminated",
        ),
        Column(
            "monthly_shares",
            "月別配比",
            "shares",
            example="1.35;1.25;1.05;0.85;0.7;0.6;0.6;0.65;0.9;1.15;1.4;1.5",
            note="12 個以分號隔開的相對權重，空白＝平均分攤；不必加總為 1",
        ),
        Column(
            "min_offtake_percent",
            "保證量下限 (%)",
            "float",
            example="80",
            note="take-or-pay：未達此比例仍須付費",
        ),
        Column("price_escalation_percent", "價格年漲幅 (%)", "float", example="2"),
        Column("price_base_year", "價格基準年", "int", example="2026"),
    ),
)

GENERATION = EntitySpec(
    entity="generation",
    label="發電數據",
    natural_key=("wind_farm_code", "period_start", "period_end"),
    columns=(
        Column(
            "wind_farm_code",
            "案場代碼",
            "str",
            required=True,
            example="WF-001",
            note="必須是已存在的案場",
        ),
        Column(
            "period_start",
            "區間起",
            "date",
            required=True,
            example="2026-01-01",
            note="格式 YYYY-MM-DD",
        ),
        Column(
            "period_end",
            "區間迄",
            "date",
            required=True,
            example="2026-01-31",
            note="格式 YYYY-MM-DD",
        ),
        Column(
            "generated_energy_mwh",
            "發電量 (MWh)",
            "float",
            required=True,
            example="12000",
        ),
        Column("data_source", "資料來源", "str", example="mock"),
    ),
)

CONSUMPTION = EntitySpec(
    entity="consumption",
    label="用電數據",
    natural_key=("customer_code", "period_start", "period_end"),
    columns=(
        Column(
            "customer_code",
            "客戶代碼",
            "str",
            required=True,
            example="CUS-001",
            note="必須是已存在的客戶",
        ),
        Column(
            "period_start",
            "區間起",
            "date",
            required=True,
            example="2026-01-01",
            note="格式 YYYY-MM-DD",
        ),
        Column(
            "period_end",
            "區間迄",
            "date",
            required=True,
            example="2026-01-31",
            note="格式 YYYY-MM-DD",
        ),
        Column(
            "consumed_energy_mwh",
            "用電量 (MWh)",
            "float",
            required=True,
            example="10000",
        ),
        Column("data_source", "資料來源", "str", example="mock"),
    ),
)

SPECS: dict[str, EntitySpec] = {
    s.entity: s
    for s in (FARM, CUSTOMER, METER, BATTERY, CONTRACT, GENERATION, CONSUMPTION)
}
