"""Pydantic models shared by the pipeline, API and UI. Money is always Decimal."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Money = Annotated[Decimal, Field(decimal_places=2)]


class Category(StrEnum):
    SALARY = "Salary"
    RENT = "Rent"
    UTILITIES = "Utilities"
    SHOPPING = "Shopping"
    FOOD = "Food"
    TRAVEL = "Travel"
    TRANSFERS = "Transfers"
    OTHER = "Other"


class Channel(StrEnum):
    UPI = "UPI"
    NEFT = "NEFT"
    IMPS = "IMPS"
    RTGS = "RTGS"
    ATM = "ATM"
    POS = "POS"
    ACH = "ACH"
    CHQ = "CHQ"
    OTHER = "OTHER"


class Direction(StrEnum):
    CREDIT = "credit"
    DEBIT = "debit"


class CategorySource(StrEnum):
    RULE = "rule"
    LLM = "llm"
    MANUAL = "manual"


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class AnomalyCode(StrEnum):
    AMOUNT_OUTLIER = "AMOUNT_OUTLIER"
    NEW_PAYEE_LARGE = "NEW_PAYEE_LARGE"
    ROUND_NUMBER_LARGE = "ROUND_NUMBER_LARGE"
    DUPLICATE = "DUPLICATE"
    PASS_THROUGH = "PASS_THROUGH"
    LOW_BALANCE = "LOW_BALANCE"
    BOUNCE_PENALTY = "BOUNCE_PENALTY"
    CASH_SPIKE = "CASH_SPIKE"


class StatementMeta(BaseModel):
    account_holder: str | None = None
    account_number_masked: str | None = Field(None, examples=["XXXXXXXX1234"])
    ifsc: str | None = None
    branch: str | None = None
    bank_name: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    opening_balance: Money | None = None
    closing_balance: Money | None = None
    layout: str | None = None
    source_type: Literal["pdf", "csv", "xlsx"] | None = None


class Transaction(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "idx": 3, "date": "2024-03-05",
                "narration": "UPI/412345678901/SWIGGY/swiggy@icici/Order",
                "amount": "452.00", "direction": "debit", "balance": "81234.50",
                "channel": "UPI", "counterparty": "SWIGGY", "counterparty_key": "swiggy",
                "category": "Food", "category_source": "rule", "category_confidence": 0.95,
            }
        }
    )
    idx: int
    date: date
    narration: str
    amount: Money = Field(gt=0)
    direction: Direction
    balance: Money | None = None
    channel: Channel = Channel.OTHER
    counterparty: str | None = None
    counterparty_key: str | None = None
    upi_handle: str | None = None
    reference: str | None = None
    category: Category = Category.OTHER
    category_source: CategorySource = CategorySource.RULE
    category_confidence: float = Field(1.0, ge=0, le=1)
    category_rationale: str | None = None
    is_recurring: bool = False


class ReconciliationIssue(BaseModel):
    idx: int | None = None
    kind: Literal["running_balance", "total_mismatch", "missing_balance"]
    expected: Money | None = None
    actual: Money | None = None
    message: str


class ReconciliationResult(BaseModel):
    passed: bool
    opening: Money | None = None
    total_credits: Money
    total_debits: Money
    expected_closing: Money | None = None
    stated_closing: Money | None = None
    rows_checked: int
    issues: list[ReconciliationIssue] = []


class AnomalyFlag(BaseModel):
    code: AnomalyCode
    severity: Severity
    reason: str
    txn_idx: list[int] = []


class CategorySpend(BaseModel):
    category: Category
    total: Money
    count: int
    pct_of_debits: float


class CounterpartyTotal(BaseModel):
    counterparty: str
    total: Money
    count: int


class MonthlyBreakdown(BaseModel):
    month: str
    credits: Money
    debits: Money
    net: Money


class RecurringPayment(BaseModel):
    counterparty: str
    typical_amount: Money
    occurrences: int
    direction: Direction
    category: Category


class Analytics(BaseModel):
    total_credits: Money
    total_debits: Money
    net: Money
    spend_by_category: list[CategorySpend]
    top_counterparties: list[CounterpartyTotal]
    monthly: list[MonthlyBreakdown]
    recurring: list[RecurringPayment]
    largest_transactions: list[Transaction]


class NarrativeSummary(BaseModel):
    account_summary: str
    period: str
    total_credits: Money
    total_debits: Money
    major_spending: list[CategorySpend]
    unusual_transactions: list[str]
    narrative: str
    source: Literal["llm", "template"]
    faithfulness_passed: bool


class ProcessingInfo(BaseModel):
    mock_mode: bool
    llm_calls: int = 0
    cache_hits: int = 0
    prompt_version: str | None = None
    elapsed_ms: int = 0


class StatementReport(BaseModel):
    meta: StatementMeta
    transactions: list[Transaction]
    reconciliation: ReconciliationResult
    analytics: Analytics
    anomalies: list[AnomalyFlag]
    summary: NarrativeSummary
    processing: ProcessingInfo
    warnings: list[str] = []


class RawTransaction(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {"date": "2024-03-05", "narration": "UPI/412345678901/ZOMATO/zomato@hdfcbank",
                        "amount": "380.00", "direction": "debit"}
        }
    )
    date: date
    narration: str
    amount: Money = Field(gt=0)
    direction: Direction


class ClassifyRequest(BaseModel):
    transactions: list[RawTransaction]
    use_llm: bool = True


class ClassifiedTransaction(BaseModel):
    category: Category
    category_source: CategorySource
    category_confidence: float
    category_rationale: str | None = None
