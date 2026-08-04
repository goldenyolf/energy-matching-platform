"""跨實體的匯入輔助端點：欄位表與範本下載。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel

from app.ingestion import template
from app.ingestion.schema import SPECS

router = APIRouter(prefix="/import", tags=["import"])


class ColumnOut(BaseModel):
    name: str
    label: str
    kind: str
    required: bool
    example: str
    note: str | None = None


class EntityOut(BaseModel):
    entity: str
    label: str
    natural_key: list[str]
    columns: list[ColumnOut]


class SchemaOut(BaseModel):
    entities: list[EntityOut]


@router.get("/schema", response_model=SchemaOut)
def import_schema() -> SchemaOut:
    """欄位定義，供前端畫欄位說明。不含任何資料，因此不需要寫入權限。"""
    return SchemaOut(
        entities=[
            EntityOut(
                entity=spec.entity,
                label=spec.label,
                natural_key=list(spec.natural_key),
                columns=[
                    ColumnOut(
                        name=c.name,
                        label=c.label,
                        kind=c.kind,
                        required=c.required,
                        example=c.example,
                        note=c.note,
                    )
                    for c in spec.columns
                ],
            )
            for spec in SPECS.values()
        ]
    )


@router.get("/template/{entity}")
def import_template(entity: str) -> Response:
    spec = SPECS.get(entity)
    if spec is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"未知的匯入類別「{entity}」。",
        )
    return Response(
        content=template.build_csv(spec),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{entity}_template.csv"'
        },
    )
