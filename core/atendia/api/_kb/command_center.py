# ruff: noqa: E501
"""Operational Knowledge Command Center endpoints.

These routes expose the B2 cockpit surface used by the rebuilt frontend:
health, risks, mixed knowledge items, unanswered WhatsApp questions, RAG
simulation, chunk impact, funnel coverage, conflicts and audit activity.

The first implementation is intentionally deterministic and local-dev
friendly. It returns seeded operational data while preserving REST contracts
that can later be backed by the richer KB tables and workers.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.api._auth_helpers import AuthUser
from atendia.api._deps import current_tenant_id, current_user, demo_tenant
from atendia.db.models.knowledge_document import KnowledgeChunk, KnowledgeDocument
from atendia.db.models.tenant_config import TenantCatalogItem, TenantFAQ
from atendia.db.session import get_db_session

router = APIRouter()
AuthenticatedUser = Annotated[AuthUser, Depends(current_user)]


def _empty_health() -> HealthResponse:
    """Health shape for tenants with no KB data yet. UI shows empty state."""
    return HealthResponse(
        overall_score=0,
        label="Sin contenido",
        status="warning",
        change_vs_yesterday=0,
        metrics=[],
        updated_at=NOW,
    )


Status = Literal["good", "warning", "critical"]
Severity = Literal["low", "medium", "high", "critical"]


class HealthMetric(BaseModel):
    key: str
    label: str
    score: int
    status: Status
    tooltip: str
    trend: int


class HealthResponse(BaseModel):
    overall_score: int
    label: str
    status: Status
    change_vs_yesterday: int
    metrics: list[HealthMetric]
    updated_at: datetime


class HealthHistoryPoint(BaseModel):
    date: str
    overall_score: int
    retrieval_quality_score: int
    answer_confidence_score: int


class RiskFinding(BaseModel):
    id: str
    category: str
    title: str
    description: str
    severity: Severity
    affected_sources: int
    affected_conversations: int
    recommended_action: str
    quick_action_type: str


class RiskResponse(BaseModel):
    items: list[RiskFinding]
    updated_at: datetime


class KnowledgeItem(BaseModel):
    id: str
    title: str
    source_type: str
    collection: str
    retrieval_score: float
    status: str
    freshness: str
    freshness_days: int
    conflicts: int
    last_used_at: str
    risk_level: Severity
    owner: str


class KnowledgeItemsResponse(BaseModel):
    items: list[KnowledgeItem]
    total: int
    page: int
    page_size: int


class UnansweredQuestion(BaseModel):
    id: str
    question: str
    frequency: int
    trend_percent: int
    funnel_stage: str
    last_seen_at: str
    suggested_action: str


class UnansweredQuestionsResponse(BaseModel):
    items: list[UnansweredQuestion]
    total: int


class FunnelStage(BaseModel):
    id: str
    label: str
    coverage_percent: int
    confidence_average: int
    unanswered_count: int
    conflict_count: int
    highest_risk_source: str
    status: Status


class FunnelCoverageResponse(BaseModel):
    stages: list[FunnelStage]


class BottomActionCard(BaseModel):
    id: str
    title: str
    value: str
    trend: str
    cta: str
    status: Status
    sparkline: list[int] = Field(default_factory=list)


class DashboardCardsResponse(BaseModel):
    items: list[BottomActionCard]


class RetrievedChunk(BaseModel):
    id: str
    source_name: str
    page_number: int
    preview: str
    retrieval_score: float
    freshness_status: str
    warnings: list[str]


class SimulationRequest(BaseModel):
    message: str = Field(min_length=1, max_length=500)
    agent: str = Field(default="Sales Agent", min_length=1, max_length=80)
    model: str = Field(default="gpt-4o-mini", min_length=1, max_length=80)


class SimulationResponse(BaseModel):
    id: str
    agent: str
    model: str
    user_message: str
    prompt_preview: str
    retrieved_chunks: list[RetrievedChunk]
    confidence_score: int
    coverage_score: int
    risk_flags: list[str]
    answer: str
    source_summary: str
    mode: Literal["mock", "llm", "sources_only"]


class ChunkImpact(BaseModel):
    chunk_id: str
    source_document: str
    page_number: int
    chunk_text: str
    embedding_status: str
    retrieval_score: float
    used_in_answers_week: int
    affected_active_conversations: int
    affected_funnel_stages: list[str]
    risk_level: Severity
    related_conflicts: list[str]
    last_edited_by: str
    last_indexed_at: str


class ConflictItem(BaseModel):
    id: str
    title: str
    severity: Severity
    sources: list[str]
    status: str
    recommended_resolution: str


class ConflictsResponse(BaseModel):
    items: list[ConflictItem]
    total: int


class AuditLogItem(BaseModel):
    id: str
    action: str
    actor: str
    target: str
    created_at: str


class AuditLogsResponse(BaseModel):
    items: list[AuditLogItem]


NOW = datetime.now(UTC)

HEALTH = HealthResponse(
    overall_score=89,
    label="Buena",
    status="good",
    change_vs_yesterday=6,
    updated_at=NOW,
    metrics=[
        HealthMetric(
            key="sales_coverage_score",
            label="Cobertura comercial",
            score=91,
            status="good",
            tooltip="Porcentaje de preguntas de ventas cubiertas por FAQs, catalogo y documentos publicados.",
            trend=4,
        ),
        HealthMetric(
            key="credit_accuracy_score",
            label="Precision credito",
            score=86,
            status="good",
            tooltip="Consistencia entre reglas de credito, FAQs y respuestas simuladas.",
            trend=3,
        ),
        HealthMetric(
            key="catalog_freshness_score",
            label="Frescura catalogo",
            score=74,
            status="warning",
            tooltip="Edad promedio de SKUs, precios y stock usados por RAG.",
            trend=-2,
        ),
        HealthMetric(
            key="faq_conflict_score",
            label="Conflictos FAQs",
            score=32,
            status="critical",
            tooltip="Conflictos abiertos ponderados por conversaciones activas impactadas.",
            trend=-9,
        ),
        HealthMetric(
            key="retrieval_quality_score",
            label="Calidad recuperacion RAG",
            score=87,
            status="good",
            tooltip="Precision de chunks recuperados contra pruebas automaticas y feedback de operadores.",
            trend=5,
        ),
        HealthMetric(
            key="answer_confidence_score",
            label="Confianza respuesta",
            score=90,
            status="good",
            tooltip="Promedio de confianza de respuestas trazables a fuentes publicadas.",
            trend=2,
        ),
        HealthMetric(
            key="obsolete_source_score",
            label="Docs obsoletos",
            score=18,
            status="critical",
            tooltip="Porcentaje de documentos usados por RAG con vencimiento o frescura critica.",
            trend=-4,
        ),
    ],
)

RISKS = [
    RiskFinding(
        id="risk-commercial-1",
        category="Riesgo comercial",
        title="FAQ de enganche contradice politica de credito",
        description="La FAQ indica 10% para negocio propio, pero la regla vigente exige 20%.",
        severity="high",
        affected_sources=12,
        affected_conversations=134,
        recommended_action="Actualizar FAQ y bloquear respuesta hasta publicar la regla corregida.",
        quick_action_type="Actualizar informacion",
    ),
    RiskFinding(
        id="risk-credit-1",
        category="Riesgo legal/credito",
        title="INE de otro estado tiene respuestas inconsistentes",
        description="Dos documentos permiten INE vigente de cualquier estado y una FAQ pide comprobante local.",
        severity="high",
        affected_sources=7,
        affected_conversations=98,
        recommended_action="Revisar politicas y resolver conflicto con supervisor.",
        quick_action_type="Revisar politicas",
    ),
    RiskFinding(
        id="risk-inventory-1",
        category="Riesgo de inventario",
        title="Catalogo Dinamo U5 no ha sido actualizado",
        description="El SKU DINM-U5-2024 se uso hoy con stock sin sincronizar desde hace 9 dias.",
        severity="medium",
        affected_sources=9,
        affected_conversations=76,
        recommended_action="Sincronizar catalogo antes de cotizar disponibilidad.",
        quick_action_type="Sincronizar catalogo",
    ),
    RiskFinding(
        id="risk-hallucination-1",
        category="Riesgo de alucinacion",
        title="Agente respondio precio sin plan_credito",
        description="Se detectaron respuestas con mensualidad estimada sin tipo_credito ni plan_credito validos.",
        severity="high",
        affected_sources=5,
        affected_conversations=54,
        recommended_action="Crear regla de bloqueo y exigir confirmacion de asesor.",
        quick_action_type="Crear/Actualizar FAQs",
    ),
    RiskFinding(
        id="risk-conflict-1",
        category="Respuestas en conflicto",
        title="Promocion vencida sigue disponible para RAG",
        description="Promociones_Mayo_2024.pdf conserva chunks activos en produccion.",
        severity="high",
        affected_sources=11,
        affected_conversations=129,
        recommended_action="Resolver conflictos y desactivar chunks vencidos.",
        quick_action_type="Resolver conflictos",
    ),
]

KNOWLEDGE_ITEMS = [
    KnowledgeItem(
        id="faq-credit-reqs",
        title="¿Cuales son los requisitos para credito?",
        source_type="FAQ",
        collection="Credito",
        retrieval_score=0.92,
        status="Publicado",
        freshness="Buena",
        freshness_days=3,
        conflicts=0,
        last_used_at="Hoy 09:41",
        risk_level="low",
        owner="AI Supervisor",
    ),
    KnowledgeItem(
        id="faq-buro",
        title="¿Aceptan buro malo?",
        source_type="FAQ",
        collection="Credito",
        retrieval_score=0.76,
        status="Publicado",
        freshness="Media",
        freshness_days=9,
        conflicts=2,
        last_used_at="Ayer 21:32",
        risk_level="high",
        owner="Gerencia credito",
    ),
    KnowledgeItem(
        id="sku-dinm-u5-2024",
        title="SKU DINM-U5-2024 · Dinamo U5",
        source_type="Catalogo",
        collection="Motos",
        retrieval_score=0.91,
        status="Publicado",
        freshness="Buena",
        freshness_days=1,
        conflicts=0,
        last_used_at="Hoy 10:12",
        risk_level="low",
        owner="Catalogo",
    ),
    KnowledgeItem(
        id="sku-dinm-r1-2024",
        title="SKU DINM-R1-2024 · Dinamo R1",
        source_type="Catalogo",
        collection="Motos",
        retrieval_score=0.78,
        status="Publicado",
        freshness="Buena",
        freshness_days=1,
        conflicts=1,
        last_used_at="Hoy 08:55",
        risk_level="medium",
        owner="Catalogo",
    ),
    KnowledgeItem(
        id="doc-credit-policy",
        title="Politicas_Credito_2024.docx",
        source_type="Documento",
        collection="Credito",
        retrieval_score=0.88,
        status="Publicado",
        freshness="Buena",
        freshness_days=5,
        conflicts=1,
        last_used_at="Ayer 16:21",
        risk_level="medium",
        owner="Credito",
    ),
    KnowledgeItem(
        id="doc-warranty",
        title="Manual_Garantias_2024.pdf",
        source_type="Documento",
        collection="Legal",
        retrieval_score=0.83,
        status="Publicado",
        freshness="Media",
        freshness_days=12,
        conflicts=0,
        last_used_at="7 may 14:02",
        risk_level="low",
        owner="Postventa",
    ),
    KnowledgeItem(
        id="doc-promos-may",
        title="Promociones_Mayo_2024.pdf",
        source_type="Promocion",
        collection="Promociones",
        retrieval_score=0.81,
        status="Publicado",
        freshness="Buena",
        freshness_days=2,
        conflicts=2,
        last_used_at="Hoy 09:12",
        risk_level="high",
        owner="Marketing",
    ),
    KnowledgeItem(
        id="doc-agent-rules",
        title="Reglas_AgentIA_2024.md",
        source_type="Documento",
        collection="Interno",
        retrieval_score=0.64,
        status="Borrador",
        freshness="Critica",
        freshness_days=25,
        conflicts=0,
        last_used_at="-",
        risk_level="medium",
        owner="AI Supervisor",
    ),
]

UNANSWERED = [
    UnansweredQuestion(
        id="cluster-ine-other-state",
        question="¿Aceptan INE de otro estado?",
        frequency=18,
        trend_percent=40,
        funnel_stage="Calificacion",
        last_seen_at="Hoy 10:22",
        suggested_action="Crear FAQ",
    ),
    UnansweredQuestion(
        id="cluster-cash-payroll",
        question="¿Puedo sacar moto si me pagan en efectivo?",
        frequency=15,
        trend_percent=25,
        funnel_stage="Credito",
        last_seen_at="Hoy 09:58",
        suggested_action="Crear FAQ",
    ),
    UnansweredQuestion(
        id="cluster-delivery-time",
        question="¿Cuanto tarda la entrega?",
        frequency=12,
        trend_percent=9,
        funnel_stage="Catalogo",
        last_seen_at="Ayer 19:14",
        suggested_action="Crear FAQ",
    ),
    UnansweredQuestion(
        id="cluster-capital-payment",
        question="¿Puedo abonar a capital?",
        frequency=9,
        trend_percent=80,
        funnel_stage="Credito",
        last_seen_at="Ayer 15:48",
        suggested_action="Asignar a fuente",
    ),
    UnansweredQuestion(
        id="cluster-electric",
        question="¿Tienen motos electricas?",
        frequency=7,
        trend_percent=0,
        funnel_stage="Catalogo",
        last_seen_at="8 may 12:30",
        suggested_action="Escalar",
    ),
]

FUNNEL = [
    FunnelStage(
        id="new-lead",
        label="New lead",
        coverage_percent=92,
        confidence_average=91,
        unanswered_count=4,
        conflict_count=0,
        highest_risk_source="FAQ bienvenida",
        status="good",
    ),
    FunnelStage(
        id="qualification",
        label="Qualification",
        coverage_percent=90,
        confidence_average=88,
        unanswered_count=6,
        conflict_count=0,
        highest_risk_source="INE foranea",
        status="good",
    ),
    FunnelStage(
        id="credit",
        label="Credit",
        coverage_percent=78,
        confidence_average=74,
        unanswered_count=18,
        conflict_count=2,
        highest_risk_source="Buro/enganche",
        status="warning",
    ),
    FunnelStage(
        id="documents",
        label="Documents",
        coverage_percent=85,
        confidence_average=82,
        unanswered_count=9,
        conflict_count=1,
        highest_risk_source="Comprobante domicilio",
        status="good",
    ),
    FunnelStage(
        id="catalog",
        label="Catalog",
        coverage_percent=91,
        confidence_average=89,
        unanswered_count=7,
        conflict_count=0,
        highest_risk_source="Stock Dinamo U5",
        status="good",
    ),
    FunnelStage(
        id="appointment",
        label="Appointment",
        coverage_percent=88,
        confidence_average=86,
        unanswered_count=5,
        conflict_count=0,
        highest_risk_source="Horarios sucursal",
        status="good",
    ),
    FunnelStage(
        id="closing",
        label="Closing",
        coverage_percent=76,
        confidence_average=71,
        unanswered_count=11,
        conflict_count=1,
        highest_risk_source="Promociones vencidas",
        status="warning",
    ),
    FunnelStage(
        id="post-sale",
        label="Post-sale",
        coverage_percent=94,
        confidence_average=90,
        unanswered_count=3,
        conflict_count=0,
        highest_risk_source="Garantia 2024",
        status="good",
    ),
]

CARDS = [
    BottomActionCard(
        id="conflicts",
        title="Conflictos detectados",
        value="32",
        trend="+12 vs ayer",
        cta="Ver conflictos",
        status="critical",
        sparkline=[5, 7, 6, 9, 8, 14, 11, 18, 16, 23],
    ),
    BottomActionCard(
        id="unanswered",
        title="Preguntas sin respuesta",
        value="118",
        trend="+18 vs ayer",
        cta="Ver preguntas",
        status="warning",
        sparkline=[7, 9, 8, 11, 10, 13, 12, 15, 16, 18],
    ),
    BottomActionCard(
        id="tests",
        title="Pruebas automaticas",
        value="24/30",
        trend="80% aprobadas",
        cta="Ver pruebas",
        status="good",
        sparkline=[12, 16, 14, 18, 15, 21, 19, 23, 20, 24],
    ),
    BottomActionCard(
        id="permissions",
        title="Violaciones de permisos",
        value="7",
        trend="+3 vs ayer",
        cta="Ver incidencias",
        status="critical",
        sparkline=[1, 2, 2, 3, 4, 3, 5, 4, 6, 7],
    ),
    BottomActionCard(
        id="promos",
        title="Promociones por vencer",
        value="5",
        trend="En proximos 7 dias",
        cta="Ver promociones",
        status="warning",
        sparkline=[8, 7, 7, 6, 6, 5, 5, 5, 5, 5],
    ),
    BottomActionCard(
        id="chunks",
        title="Editor de chunks",
        value="1,243",
        trend="Chunks activos",
        cta="Abrir editor",
        status="good",
        sparkline=[20, 21, 19, 24, 25, 27, 26, 29, 31, 33],
    ),
    BottomActionCard(
        id="rag",
        title="Analitica RAG",
        value="87%",
        trend="Rendimiento global",
        cta="Ver analitica",
        status="good",
        sparkline=[64, 65, 70, 68, 72, 75, 76, 80, 83, 87],
    ),
    BottomActionCard(
        id="index-errors",
        title="Docs con errores index.",
        value="14",
        trend="Requieren atencion",
        cta="Ver documentos",
        status="critical",
        sparkline=[9, 10, 11, 12, 12, 13, 12, 14, 13, 14],
    ),
]

RETRIEVED_CHUNKS = [
    RetrievedChunk(
        id="chunk-credit-policy-p5",
        source_name="Politicas_Credito_2024.docx",
        page_number=5,
        preview="Identificacion oficial vigente. Puede ser INE o pasaporte; debe coincidir con el comprobante de domicilio.",
        retrieval_score=0.91,
        freshness_status="vigente",
        warnings=[],
    ),
    RetrievedChunk(
        id="chunk-credit-faq-ine",
        source_name="FAQ_Credito.html",
        page_number=3,
        preview="Para credito aceptamos INE nacional vigente. Validar domicilio cuando no coincida con el comprobante.",
        retrieval_score=0.84,
        freshness_status="vigente",
        warnings=["posible conflicto"],
    ),
    RetrievedChunk(
        id="chunk-ops-manual-p12",
        source_name="Manual_Operaciones.pdf",
        page_number=12,
        preview="Requisitos generales de identificacion del cliente y criterios para validacion manual por asesor.",
        retrieval_score=0.71,
        freshness_status="media",
        warnings=["revision supervisor"],
    ),
    RetrievedChunk(
        id="chunk-agent-rules-p8",
        source_name="Reglas_AgentIA.md",
        page_number=8,
        preview="Siempre verificar identidad del solicitante; no prometer aprobacion ni disponibilidad sin datos confirmados.",
        retrieval_score=0.63,
        freshness_status="vigente",
        warnings=["baja confianza"],
    ),
]

DEFAULT_SIMULATION = SimulationResponse(
    id="sim-ine-other-state",
    agent="Sales Agent",
    model="gpt-4o-mini",
    user_message="¿Aceptan INE de otro estado?",
    prompt_preview=(
        "Eres AtendIA, asistente de ventas de un distribuidor de motos en Mexico. "
        "Responde con informacion precisa basada solo en conocimiento disponible, "
        "sin inventar aprobaciones, precios, stock, promociones ni terminos de credito."
    ),
    retrieved_chunks=RETRIEVED_CHUNKS,
    confidence_score=78,
    coverage_score=72,
    risk_flags=["Politica puede estar desactualizada", "Posible conflicto con otra fuente"],
    answer=(
        "Si, aceptamos INE de cualquier estado de la Republica Mexicana siempre que este vigente, "
        "legible y coincida con los datos del solicitante. Si hay diferencia de domicilio, "
        "un asesor debe validar el caso."
    ),
    source_summary="2 documentos",
    mode="mock",
)

CHUNK_IMPACT = ChunkImpact(
    chunk_id="chunk-credit-policy-p5",
    source_document="Politicas_Credito_2024.docx",
    page_number=5,
    chunk_text=(
        "Identificacion oficial vigente. Puede ser INE o pasaporte; debe coincidir con el "
        "comprobante de domicilio. Cuando el domicilio difiera, el asesor debe validar el caso "
        "antes de continuar con la solicitud de credito."
    ),
    embedding_status="publicada",
    retrieval_score=0.91,
    used_in_answers_week=214,
    affected_active_conversations=98,
    affected_funnel_stages=["Calificacion", "Credito", "Cierre"],
    risk_level="high",
    related_conflicts=["INE foranea vs comprobante local", "FAQ credito duplicada"],
    last_edited_by="Mariana Gomez",
    last_indexed_at="Hoy 08:36",
)

CONFLICTS = [
    ConflictItem(
        id="conflict-enganche",
        title="Enganche para negocio propio",
        severity="high",
        sources=["FAQ requisitos credito", "Regla 20% Negocio propio"],
        status="abierto",
        recommended_resolution="Actualizar FAQ y publicar nueva version.",
    ),
    ConflictItem(
        id="conflict-ine",
        title="INE de otro estado",
        severity="high",
        sources=["Politicas_Credito_2024.docx", "FAQ_Credito.html"],
        status="abierto",
        recommended_resolution="Unificar criterio y marcar documento oficial como prioritario.",
    ),
]

AUDIT_LOGS = [
    AuditLogItem(
        id="audit-1",
        action="kb.source.reindexed",
        actor="AI Supervisor",
        target="Politicas_Credito_2024.docx",
        created_at="Hoy 08:36",
    ),
    AuditLogItem(
        id="audit-2",
        action="kb.simulation.marked_incomplete",
        actor="Centro Demo MX",
        target="¿Aceptan INE de otro estado?",
        created_at="Ayer 18:41",
    ),
    AuditLogItem(
        id="audit-3",
        action="kb.chunk.disabled",
        actor="Mariana Gomez",
        target="Promociones_Mayo_2024.pdf p.2",
        created_at="Ayer 11:03",
    ),
]


@router.get("/health", response_model=HealthResponse)
async def get_health(
    _user: AuthenticatedUser,
    is_demo: bool = Depends(demo_tenant),
) -> HealthResponse:
    if not is_demo:
        return _empty_health()
    return HEALTH


@router.get("/health/history", response_model=list[HealthHistoryPoint])
async def get_health_history(
    _user: AuthenticatedUser,
    is_demo: bool = Depends(demo_tenant),
) -> list[HealthHistoryPoint]:
    if not is_demo:
        return []
    return [
        HealthHistoryPoint(
            date="2026-05-04",
            overall_score=82,
            retrieval_quality_score=80,
            answer_confidence_score=84,
        ),
        HealthHistoryPoint(
            date="2026-05-05",
            overall_score=84,
            retrieval_quality_score=82,
            answer_confidence_score=85,
        ),
        HealthHistoryPoint(
            date="2026-05-06",
            overall_score=83,
            retrieval_quality_score=81,
            answer_confidence_score=85,
        ),
        HealthHistoryPoint(
            date="2026-05-07",
            overall_score=86,
            retrieval_quality_score=84,
            answer_confidence_score=87,
        ),
        HealthHistoryPoint(
            date="2026-05-08",
            overall_score=87,
            retrieval_quality_score=85,
            answer_confidence_score=88,
        ),
        HealthHistoryPoint(
            date="2026-05-09",
            overall_score=83,
            retrieval_quality_score=81,
            answer_confidence_score=86,
        ),
        HealthHistoryPoint(
            date="2026-05-10",
            overall_score=89,
            retrieval_quality_score=87,
            answer_confidence_score=90,
        ),
    ]


@router.get("/risks", response_model=RiskResponse)
async def get_risks(
    _user: AuthenticatedUser,
    is_demo: bool = Depends(demo_tenant),
) -> RiskResponse:
    if not is_demo:
        return RiskResponse(items=[], updated_at=NOW)
    return RiskResponse(items=RISKS, updated_at=NOW)


@router.post("/risks/{risk_id}/resolve")
async def resolve_risk(risk_id: str, _user: AuthenticatedUser) -> dict[str, str]:
    return {"id": risk_id, "status": "resolved"}


@router.get("/items", response_model=KnowledgeItemsResponse)
async def get_items(
    _user: AuthenticatedUser,
    q: str | None = Query(default=None, max_length=120),
    collection: str | None = Query(default=None, max_length=80),
    status: str | None = Query(default=None, max_length=80),
    risk: str | None = Query(default=None, max_length=40),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    is_demo: bool = Depends(demo_tenant),
    tenant_id=Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> KnowledgeItemsResponse:
    if not is_demo:
        # Real tenants get a unified view across FAQs + Catalog + Documents.
        # No risk/status filtering yet — those columns don't exist on the
        # legacy KB tables; the UI shows all items with "good" status.
        faq_count = (
            await session.execute(
                sql_text("SELECT COUNT(*) FROM tenant_faqs WHERE tenant_id = :t"),
                {"t": str(tenant_id)},
            )
        ).scalar_one()
        catalog_count = (
            await session.execute(
                sql_text("SELECT COUNT(*) FROM tenant_catalogs WHERE tenant_id = :t"),
                {"t": str(tenant_id)},
            )
        ).scalar_one()
        docs_count = (
            await session.execute(
                sql_text("SELECT COUNT(*) FROM knowledge_documents WHERE tenant_id = :t"),
                {"t": str(tenant_id)},
            )
        ).scalar_one()
        # Build a minimal item-list summary; deeper per-row UI happens via
        # the legacy /knowledge/faqs, /catalog, /documents endpoints.
        summary_items: list[KnowledgeItem] = []
        if faq_count > 0:
            summary_items.append(
                KnowledgeItem(
                    id="summary-faqs",
                    title=f"FAQs ({faq_count})",
                    type="faq",
                    collection="FAQs",
                    status="Publicado",
                    risk_level="ninguno",
                    last_updated="—",
                    owner="—",
                    coverage_score=100,
                    excerpt="Administra desde la pestaña Conocimiento.",
                )
            )
        if catalog_count > 0:
            summary_items.append(
                KnowledgeItem(
                    id="summary-catalog",
                    title=f"Catálogo ({catalog_count})",
                    type="catalog",
                    collection="Catálogo",
                    status="Publicado",
                    risk_level="ninguno",
                    last_updated="—",
                    owner="—",
                    coverage_score=100,
                    excerpt="Administra desde la pestaña Conocimiento.",
                )
            )
        if docs_count > 0:
            summary_items.append(
                KnowledgeItem(
                    id="summary-docs",
                    title=f"Documentos ({docs_count})",
                    type="document",
                    collection="Documentos",
                    status="Publicado",
                    risk_level="ninguno",
                    last_updated="—",
                    owner="—",
                    coverage_score=100,
                    excerpt="Administra desde la pestaña Conocimiento.",
                )
            )
        return KnowledgeItemsResponse(
            items=summary_items,
            total=len(summary_items),
            page=page,
            page_size=page_size,
        )

    items = KNOWLEDGE_ITEMS
    if q:
        needle = q.strip().lower()
        items = [item for item in items if needle in item.title.lower()]
    if collection and collection != "Todas":
        items = [item for item in items if item.collection == collection]
    if status and status != "Todos":
        items = [item for item in items if item.status == status]
    if risk and risk != "Todos":
        items = [item for item in items if item.risk_level == risk]
    start = (page - 1) * page_size
    return KnowledgeItemsResponse(
        items=items[start : start + page_size],
        total=len(items),
        page=page,
        page_size=page_size,
    )


@router.post("/items/{item_id}/publish")
async def publish_item(item_id: str, _user: AuthenticatedUser) -> dict[str, str]:
    return {"id": item_id, "status": "Publicado"}


@router.post("/items/{item_id}/archive")
async def archive_item(item_id: str, _user: AuthenticatedUser) -> dict[str, str]:
    return {"id": item_id, "status": "Archivado"}


@router.post("/items/{item_id}/reindex")
async def reindex_item(item_id: str, _user: AuthenticatedUser) -> dict[str, str]:
    return {"id": item_id, "status": "processing"}


@router.get("/unanswered-questions", response_model=UnansweredQuestionsResponse)
async def get_unanswered_questions(
    _user: AuthenticatedUser,
    is_demo: bool = Depends(demo_tenant),
    tenant_id=Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> UnansweredQuestionsResponse:
    if not is_demo:
        # Real tenants: read from kb_unanswered_questions table when it
        # exists. Empty for fresh tenants — the bot has to be running
        # and detect unanswered queries before rows appear here.
        try:
            total = (
                await session.execute(
                    sql_text("SELECT COUNT(*) FROM kb_unanswered_questions WHERE tenant_id = :t"),
                    {"t": str(tenant_id)},
                )
            ).scalar_one()
        except Exception:
            total = 0
        return UnansweredQuestionsResponse(items=[], total=total or 0)
    return UnansweredQuestionsResponse(items=UNANSWERED, total=118)


@router.post("/unanswered-questions/{question_id}/create-faq")
async def create_faq_from_question(question_id: str, _user: AuthenticatedUser) -> dict[str, str]:
    return {"id": question_id, "status": "faq_draft_created"}


@router.post("/unanswered-questions/{question_id}/ignore")
async def ignore_question(question_id: str, _user: AuthenticatedUser) -> dict[str, str]:
    return {"id": question_id, "status": "ignored"}


@router.post("/unanswered-questions/{question_id}/escalate")
async def escalate_question(question_id: str, _user: AuthenticatedUser) -> dict[str, str]:
    return {"id": question_id, "status": "escalated"}


@router.get("/funnel-coverage", response_model=FunnelCoverageResponse)
async def get_funnel_coverage(
    _user: AuthenticatedUser,
    is_demo: bool = Depends(demo_tenant),
) -> FunnelCoverageResponse:
    if not is_demo:
        return FunnelCoverageResponse(stages=[])
    return FunnelCoverageResponse(stages=FUNNEL)


@router.get("/dashboard-cards", response_model=DashboardCardsResponse)
async def get_dashboard_cards(
    _user: AuthenticatedUser,
    is_demo: bool = Depends(demo_tenant),
) -> DashboardCardsResponse:
    if not is_demo:
        return DashboardCardsResponse(items=[])
    return DashboardCardsResponse(items=CARDS)


@router.post("/simulate", response_model=SimulationResponse)
async def simulate(
    body: SimulationRequest,
    _user: AuthenticatedUser,
    is_demo: bool = Depends(demo_tenant),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> SimulationResponse:
    # Demo tenants → hardcoded showcase.
    # Real tenants → ILIKE search across the tenant's FAQs / catalog /
    # document chunks. Empty KB falls through to the "no content" stub
    # so the UI still shows a coherent message. The full embedding /
    # LLM-answer path lives at /knowledge/test in knowledge_routes.py;
    # this surface is the cockpit's lightweight preview.
    if is_demo:
        return DEFAULT_SIMULATION.model_copy(
            update={
                "user_message": body.message,
                "agent": body.agent,
                "model": body.model,
            }
        )

    retrieved = await _search_tenant_kb(session, tenant_id, body.message)
    if not retrieved:
        return SimulationResponse(
            id="sim-stub",
            agent=body.agent,
            model=body.model,
            user_message=body.message,
            prompt_preview="(sin contenido en la base de conocimiento)",
            retrieved_chunks=[],
            confidence_score=0,
            coverage_score=0,
            risk_flags=["no_kb_content"],
            answer=(
                "Aún no hay contenido suficiente en la base de "
                "conocimiento para responder. Carga FAQs, catálogo o "
                "documentos en la pestaña Conocimiento, o usa "
                "'/knowledge/test' para correr una consulta RAG real."
            ),
            source_summary="0 fuentes",
            mode="sources_only",
        )
    summary = f"{len(retrieved)} fuente{'s' if len(retrieved) != 1 else ''} reales"
    return SimulationResponse(
        id=f"sim-{datetime.now(UTC).timestamp():.0f}",
        agent=body.agent,
        model=body.model,
        user_message=body.message,
        prompt_preview=(
            f"Pregunta: {body.message}\n\n"
            f"Contexto: {len(retrieved)} fuente(s) recuperadas del KB del "
            "tenant. Use /knowledge/test para una respuesta sintetizada por LLM."
        ),
        retrieved_chunks=retrieved,
        confidence_score=60 if len(retrieved) >= 2 else 35,
        coverage_score=min(100, len(retrieved) * 20),
        risk_flags=[],
        answer=(
            "Encontré fuentes relevantes en el KB del tenant. Para una "
            "respuesta sintetizada por el modelo, usa /knowledge/test "
            "(esta vista del cockpit muestra solo el ranking de fuentes)."
        ),
        source_summary=summary,
        mode="sources_only",
    )


async def _search_tenant_kb(
    session: AsyncSession, tenant_id: UUID, query: str
) -> list[RetrievedChunk]:
    """ILIKE-based search across FAQs, catalog items and document chunks.

    Embedding search lives at /knowledge/test; the cockpit's simulate is
    intentionally lighter so it stays usable without OpenAI access. Returns
    up to 6 chunks ranked by source type (FAQs first, then catalog, then
    document chunks) — operators typically curate FAQs as the highest
    signal source so we rank them top.
    """
    like = f"%{query.strip()}%"
    chunks: list[RetrievedChunk] = []

    faq_rows = (
        (
            await session.execute(
                select(TenantFAQ)
                .where(
                    TenantFAQ.tenant_id == tenant_id,
                    func.lower(TenantFAQ.question + " " + TenantFAQ.answer).like(func.lower(like)),
                )
                .limit(3)
            )
        )
        .scalars()
        .all()
    )
    for row in faq_rows:
        preview = f"{row.question}\n{row.answer}"
        chunks.append(
            RetrievedChunk(
                id=str(row.id),
                source_name=f"FAQ: {row.question[:60]}",
                page_number=0,
                preview=preview[:600],
                retrieval_score=0.85,
                freshness_status="fresh",
                warnings=[],
            )
        )

    catalog_rows = (
        (
            await session.execute(
                select(TenantCatalogItem)
                .where(
                    TenantCatalogItem.tenant_id == tenant_id,
                    TenantCatalogItem.name.ilike(like),
                )
                .limit(3)
            )
        )
        .scalars()
        .all()
    )
    for row in catalog_rows:
        chunks.append(
            RetrievedChunk(
                id=str(row.id),
                source_name=f"Catálogo: {row.name}",
                page_number=0,
                preview=row.name[:600],
                retrieval_score=0.7,
                freshness_status="fresh",
                warnings=[],
            )
        )

    if len(chunks) < 6:
        doc_chunks = (
            await session.execute(
                select(KnowledgeChunk, KnowledgeDocument.filename)
                .join(
                    KnowledgeDocument,
                    KnowledgeDocument.id == KnowledgeChunk.document_id,
                )
                .where(
                    KnowledgeChunk.tenant_id == tenant_id,
                    KnowledgeChunk.text.ilike(like),
                )
                .limit(6 - len(chunks))
            )
        ).all()
        for row, filename in doc_chunks:
            chunks.append(
                RetrievedChunk(
                    id=str(row.id),
                    source_name=f"Doc: {filename}",
                    page_number=getattr(row, "page_number", None) or 0,
                    preview=row.text[:600],
                    retrieval_score=0.6,
                    freshness_status="fresh",
                    warnings=[],
                )
            )
    return chunks


@router.get("/simulate/{simulation_id}", response_model=SimulationResponse)
async def get_simulation(simulation_id: str, _user: AuthenticatedUser) -> SimulationResponse:
    return DEFAULT_SIMULATION.model_copy(update={"id": simulation_id})


@router.post("/simulate/{simulation_id}/mark-correct")
async def mark_simulation_correct(simulation_id: str, _user: AuthenticatedUser) -> dict[str, str]:
    return {"id": simulation_id, "status": "correct"}


@router.post("/simulate/{simulation_id}/mark-incomplete")
async def mark_simulation_incomplete(
    simulation_id: str, _user: AuthenticatedUser
) -> dict[str, str]:
    return {"id": simulation_id, "status": "incomplete"}


@router.post("/simulate/{simulation_id}/mark-incorrect")
async def mark_simulation_incorrect(simulation_id: str, _user: AuthenticatedUser) -> dict[str, str]:
    return {"id": simulation_id, "status": "incorrect"}


@router.post("/simulate/{simulation_id}/create-faq")
async def simulation_create_faq(simulation_id: str, _user: AuthenticatedUser) -> dict[str, str]:
    return {"id": simulation_id, "status": "faq_draft_created"}


@router.post("/simulate/{simulation_id}/block-answer")
async def simulation_block_answer(simulation_id: str, _user: AuthenticatedUser) -> dict[str, str]:
    return {"id": simulation_id, "status": "blocked"}


@router.get("/chunks/{chunk_id}/impact", response_model=ChunkImpact)
async def get_chunk_impact(chunk_id: str, _user: AuthenticatedUser) -> ChunkImpact:
    return CHUNK_IMPACT.model_copy(update={"chunk_id": chunk_id})


@router.post("/chunks/{chunk_id}/disable")
async def disable_chunk(chunk_id: str, _user: AuthenticatedUser) -> dict[str, str]:
    return {"id": chunk_id, "status": "disabled"}


@router.post("/chunks/{chunk_id}/split")
async def split_chunk(chunk_id: str, _user: AuthenticatedUser) -> dict[str, str]:
    return {"id": chunk_id, "status": "split_queued"}


@router.post("/chunks/{chunk_id}/merge")
async def merge_chunk(chunk_id: str, _user: AuthenticatedUser) -> dict[str, str]:
    return {"id": chunk_id, "status": "merge_queued"}


@router.post("/chunks/{chunk_id}/prioritize")
async def prioritize_chunk(chunk_id: str, _user: AuthenticatedUser) -> dict[str, str]:
    return {"id": chunk_id, "status": "prioritized"}


@router.post("/chunks/{chunk_id}/reindex")
async def reindex_chunk(chunk_id: str, _user: AuthenticatedUser) -> dict[str, str]:
    return {"id": chunk_id, "status": "reindex_queued"}


@router.get("/conflicts", response_model=ConflictsResponse)
async def get_conflicts(
    _user: AuthenticatedUser,
    is_demo: bool = Depends(demo_tenant),
    tenant_id=Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> ConflictsResponse:
    if not is_demo:
        try:
            total = (
                await session.execute(
                    sql_text("SELECT COUNT(*) FROM kb_conflicts WHERE tenant_id = :t"),
                    {"t": str(tenant_id)},
                )
            ).scalar_one()
        except Exception:
            total = 0
        return ConflictsResponse(items=[], total=total or 0)
    return ConflictsResponse(items=CONFLICTS, total=len(CONFLICTS))


@router.post("/conflicts/{conflict_id}/resolve")
async def resolve_conflict(conflict_id: str, _user: AuthenticatedUser) -> dict[str, str]:
    return {"id": conflict_id, "status": "resolved"}


@router.get("/audit-logs", response_model=AuditLogsResponse)
async def get_audit_logs(
    _user: AuthenticatedUser,
    is_demo: bool = Depends(demo_tenant),
) -> AuditLogsResponse:
    if not is_demo:
        return AuditLogsResponse(items=[])
    return AuditLogsResponse(items=AUDIT_LOGS)
