"""Canonical fixture evidence and complete in-memory replay verification."""

from __future__ import annotations

import hashlib
import json
import math
import re
import struct
from decimal import Decimal
from typing import Annotated, Any, Final, Literal

from pydantic import BeforeValidator, Field, StrictInt, ValidationError, model_validator

from quantverify.application.contracts import (
    ConsumedSessionRange,
    DailyTrendParameters,
    FixtureMetricPolicy,
    FixtureRunSpec,
    ReferenceExecutionSpec,
)
from quantverify.core.enums import BarFrequency
from quantverify.core.exceptions import QuantVerifyError
from quantverify.core.models import (
    CostModel,
    DataSnapshot,
    DomainModel,
    EngineVersion,
    ExecutionAssumptions,
    ExperimentConfig,
    RuntimeContext,
    StrategyVersion,
    TargetPosition,
    TimeRange,
    ValidationConfig,
)
from quantverify.engines.reference import LongFlatReferenceEngine, ReferenceResult
from quantverify.fixtures.models import FixtureManifest
from quantverify.implementation_registry import (
    EngineImplementationRefV1,
    ImplementationRegistry,
    StrategyImplementationRefV1,
    builtin_implementation_registry,
)
from quantverify.metrics.models import ReturnBasis
from quantverify.metrics.v2_calculator import calculate_metric_set_v2
from quantverify.metrics.v2_identity import (
    MAX_V2_CANONICAL_BYTES,
    MAX_V2_JSON_NESTING,
    canonicalize_v2,
    parse_decimal_value_v1,
)
from quantverify.metrics.v2_models import (
    AnnualizationPolicyV2,
    EquityObservationV2,
    MetricCalculatorRef,
    MetricInputV2,
    MetricSetV2,
    RiskFreePolicyV2,
)
from quantverify.strategies.trend import price_above_sma_targets

_HEX64 = re.compile(r"^[a-f0-9]{16}$")
_HASH64 = r"^[a-f0-9]{64}$"
_ID24 = r"^(?:exp|fixture-run-spec|run)_[a-f0-9]{24}$"
MAX_EVIDENCE_ROWS: Final = 10_000
V2Decimal = Annotated[Decimal, BeforeValidator(parse_decimal_value_v1)]


class FixtureReplayIntegrityError(QuantVerifyError):
    """Fixture evidence could not be reconstructed and replayed exactly."""


class Binary64ValueV1(DomainModel):
    schema_version: Literal["binary64-value-v1"] = "binary64-value-v1"
    bits: str = Field(pattern=r"^[a-f0-9]{16}$")

    @classmethod
    def from_float(cls, value: float) -> Binary64ValueV1:
        if type(value) is not float or not math.isfinite(value) or value == 0.0:
            raise ValueError("binary64 projection requires one finite nonzero float")
        return cls(bits=struct.pack(">d", value).hex())

    def to_float(self) -> float:
        if not _HEX64.fullmatch(self.bits):
            raise ValueError("binary64 projection is not canonical")
        value = float(struct.unpack(">d", bytes.fromhex(self.bits))[0])
        if not math.isfinite(value) or value == 0.0:
            raise ValueError("binary64 projection requires one finite nonzero float")
        if struct.pack(">d", value).hex() != self.bits:
            raise ValueError("binary64 projection did not round trip")
        return value


class ValidationConfigEvidenceProjectionV1(DomainModel):
    schema_version: Literal["validation-config-evidence-projection-v1"] = (
        "validation-config-evidence-projection-v1"
    )
    train_fraction: Binary64ValueV1
    validation_fraction: Binary64ValueV1
    test_fraction: Binary64ValueV1

    @classmethod
    def from_domain(cls, value: ValidationConfig) -> ValidationConfigEvidenceProjectionV1:
        validated = ValidationConfig.model_validate(value.model_dump(mode="python"))
        return cls(
            train_fraction=Binary64ValueV1.from_float(validated.train_fraction),
            validation_fraction=Binary64ValueV1.from_float(validated.validation_fraction),
            test_fraction=Binary64ValueV1.from_float(validated.test_fraction),
        )

    def to_domain(self) -> ValidationConfig:
        validated = type(self).model_validate(self.model_dump(mode="python"))
        return ValidationConfig(
            train_fraction=validated.train_fraction.to_float(),
            validation_fraction=validated.validation_fraction.to_float(),
            test_fraction=validated.test_fraction.to_float(),
        )


class CostModelEvidenceProjectionV1(DomainModel):
    commission_bps: V2Decimal
    slippage_bps: V2Decimal
    minimum_commission: V2Decimal
    stamp_duty_bps: V2Decimal

    @classmethod
    def from_domain(cls, value: CostModel) -> CostModelEvidenceProjectionV1:
        validated = CostModel.model_validate(value.model_dump(mode="python"))
        return cls.model_validate(validated.model_dump(mode="python"))

    def to_domain(self) -> CostModel:
        return CostModel.model_validate(self.model_dump(mode="python"))


class ExperimentConfigEvidenceProjectionV1(DomainModel):
    strategy: StrategyVersion
    universe_id: str
    dataset: DataSnapshot
    period: TimeRange
    frequency: BarFrequency
    parameters: dict[str, Any]
    benchmark_id: str
    cost_model: CostModelEvidenceProjectionV1
    execution: ExecutionAssumptions
    validation: ValidationConfigEvidenceProjectionV1
    engine: EngineVersion
    base_currency: str
    random_seed: StrictInt

    @classmethod
    def from_domain(cls, value: ExperimentConfig) -> ExperimentConfigEvidenceProjectionV1:
        validated = ExperimentConfig.model_validate(value.model_dump(mode="python"))
        if not isinstance(validated.dataset, DataSnapshot):
            raise ValueError("fixture evidence requires a legacy DataSnapshot")
        return cls(
            strategy=validated.strategy,
            universe_id=validated.universe_id,
            dataset=validated.dataset,
            period=validated.period,
            frequency=validated.frequency,
            parameters=validated.parameters,
            benchmark_id=validated.benchmark_id,
            cost_model=CostModelEvidenceProjectionV1.from_domain(validated.cost_model),
            execution=validated.execution,
            validation=ValidationConfigEvidenceProjectionV1.from_domain(
                validated.validation
            ),
            engine=validated.engine,
            base_currency=validated.base_currency,
            random_seed=validated.random_seed,
        )

    def to_domain(self) -> ExperimentConfig:
        validated = type(self).model_validate(self.model_dump(mode="python"))
        return ExperimentConfig(
            strategy=validated.strategy,
            universe_id=validated.universe_id,
            dataset=validated.dataset,
            period=validated.period,
            frequency=validated.frequency,
            parameters=validated.parameters,
            benchmark_id=validated.benchmark_id,
            cost_model=validated.cost_model.to_domain(),
            execution=validated.execution,
            validation=validated.validation.to_domain(),
            engine=validated.engine,
            base_currency=validated.base_currency,
            random_seed=validated.random_seed,
        )


class ReferenceExecutionEvidenceProjectionV1(DomainModel):
    schema_version: Literal["reference-execution-v1"] = "reference-execution-v1"
    initial_cash: V2Decimal


class FixtureMetricPolicyEvidenceProjectionV1(DomainModel):
    schema_version: Literal["fixture-metric-policy-v1"] = "fixture-metric-policy-v1"
    return_basis: ReturnBasis
    annualization: AnnualizationPolicyV2
    volatility_ddof: StrictInt = Field(ge=0)
    risk_free: RiskFreePolicyV2


class FixtureRunSpecEvidenceProjectionV1(DomainModel):
    schema_version: Literal["fixture-run-spec-evidence-projection-v1"] = (
        "fixture-run-spec-evidence-projection-v1"
    )
    mode: Literal["fixture"] = "fixture"
    fixture_id: str
    experiment: ExperimentConfigEvidenceProjectionV1
    strategy_parameters: DailyTrendParameters
    consumed_sessions: ConsumedSessionRange
    execution: ReferenceExecutionEvidenceProjectionV1
    metrics: FixtureMetricPolicyEvidenceProjectionV1

    @classmethod
    def from_domain(cls, value: FixtureRunSpec) -> FixtureRunSpecEvidenceProjectionV1:
        spec = FixtureRunSpec.model_validate(value.model_dump(mode="python"))
        _require_legacy_policy_decimals(spec.metrics)
        return cls(
            fixture_id=spec.fixture_id,
            experiment=ExperimentConfigEvidenceProjectionV1.from_domain(spec.experiment),
            strategy_parameters=spec.strategy_parameters,
            consumed_sessions=spec.consumed_sessions,
            execution=ReferenceExecutionEvidenceProjectionV1(
                initial_cash=spec.execution.initial_cash
            ),
            metrics=FixtureMetricPolicyEvidenceProjectionV1(
                return_basis=spec.metrics.return_basis,
                annualization=AnnualizationPolicyV2(
                    **spec.metrics.annualization.model_dump(mode="python")
                ),
                volatility_ddof=spec.metrics.volatility_ddof,
                risk_free=RiskFreePolicyV2(
                    **spec.metrics.risk_free.model_dump(mode="python")
                ),
            ),
        )

    def to_domain(self) -> FixtureRunSpec:
        value = type(self).model_validate(self.model_dump(mode="python"))
        return FixtureRunSpec(
            fixture_id=value.fixture_id,
            experiment=value.experiment.to_domain(),
            strategy_parameters=value.strategy_parameters,
            consumed_sessions=value.consumed_sessions,
            execution=ReferenceExecutionSpec(initial_cash=value.execution.initial_cash),
            metrics=FixtureMetricPolicy(
                return_basis=value.metrics.return_basis,
                annualization=value.metrics.annualization.model_dump(mode="python"),
                volatility_ddof=value.metrics.volatility_ddof,
                risk_free=value.metrics.risk_free.model_dump(mode="python"),
            ),
        )


class FixtureRunEvidenceV2(DomainModel):
    schema_version: Literal["fixture-run-evidence-v2"] = "fixture-run-evidence-v2"
    experiment_id: str = Field(pattern=r"^exp_[a-f0-9]{24}$")
    fixture_run_spec_id: str = Field(pattern=r"^fixture-run-spec_[a-f0-9]{24}$")
    run_id: str = Field(pattern=r"^run_[a-f0-9]{24}$")
    fixture_run_spec: FixtureRunSpecEvidenceProjectionV1
    fixture_manifest: FixtureManifest
    strategy: StrategyImplementationRefV1
    target_positions_schema_version: Literal["fixture-target-positions-v1"] = (
        "fixture-target-positions-v1"
    )
    targets: tuple[TargetPosition, ...] = Field(max_length=MAX_EVIDENCE_ROWS)
    targets_content_hash: str = Field(pattern=_HASH64)
    engine: EngineImplementationRefV1
    reference_result: ReferenceResult
    metric_input: MetricInputV2
    metric_input_content_hash: str = Field(pattern=_HASH64)
    calculator: MetricCalculatorRef
    metric_set: MetricSetV2
    metric_set_content_hash: str = Field(pattern=_HASH64)

    @model_validator(mode="after")
    def validate_detached_cross_fields(self) -> FixtureRunEvidenceV2:
        if not isinstance(self.targets, tuple):
            raise ValueError("fixture evidence targets must remain immutable")
        spec = self.fixture_run_spec.to_domain()
        if self.experiment_id != spec.experiment.experiment_id:
            raise ValueError("evidence experiment identity does not match its spec")
        if self.fixture_run_spec_id != spec.fixture_run_spec_id:
            raise ValueError("evidence spec identity does not match its spec")
        if self.targets_content_hash != fixture_target_positions_content_hash_v1(
            self.targets
        ):
            raise ValueError("evidence targets hash does not match ordered targets")
        if self.metric_input_content_hash != self.metric_input.content_hash:
            raise ValueError("evidence metric input hash does not match")
        if self.metric_set_content_hash != self.metric_set.content_hash:
            raise ValueError("evidence metric set hash does not match")
        if self.metric_set.metric_input_content_hash != self.metric_input_content_hash:
            raise ValueError("metric set is detached from its input")
        if self.metric_set.calculator != self.calculator:
            raise ValueError("metric set is detached from its calculator")
        return self

    @property
    def evidence_content_hash(self) -> str:
        return hashlib.sha256(canonical_fixture_run_evidence_v2_bytes(self)).hexdigest()


class ReplayedFixtureEvidenceV2(DomainModel):
    replay_status: Literal["replayed-not-store-verified"] = "replayed-not-store-verified"
    evidence: FixtureRunEvidenceV2


def build_fixture_run_evidence_v2(
    *,
    spec: FixtureRunSpec,
    runtime: RuntimeContext,
    fixture_manifest: FixtureManifest,
    registry: ImplementationRegistry | None = None,
) -> ReplayedFixtureEvidenceV2:
    failed = False
    result: ReplayedFixtureEvidenceV2 | None = None
    try:
        validated_spec = FixtureRunSpec.model_validate(spec.model_dump(mode="python"))
        validated_runtime = RuntimeContext.model_validate(runtime.model_dump(mode="python"))
        manifest = FixtureManifest.model_validate(fixture_manifest.model_dump(mode="python"))
        active_registry = registry or builtin_implementation_registry()
        strategy, engine = active_registry.resolve_versions(
            validated_spec.experiment.strategy, validated_spec.experiment.engine
        )
        _validate_spec_manifest(validated_spec, manifest)
        targets = price_above_sma_targets(
            manifest.bundle.bars,
            window=validated_spec.strategy_parameters.window,
            schedule=manifest.bundle.schedule,
        )
        reference_result = LongFlatReferenceEngine().run(
            manifest.bundle.bars,
            targets,
            initial_cash=validated_spec.execution.initial_cash,
            commission_bps=validated_spec.experiment.cost_model.commission_bps,
            slippage_bps=validated_spec.experiment.cost_model.slippage_bps,
        )
        metric_input, calculator, metric_set = _derive_metrics(
            validated_spec, manifest, reference_result
        )
        evidence = FixtureRunEvidenceV2(
            experiment_id=validated_spec.experiment.experiment_id,
            fixture_run_spec_id=validated_spec.fixture_run_spec_id,
            run_id=validated_spec.run_id(validated_runtime),
            fixture_run_spec=FixtureRunSpecEvidenceProjectionV1.from_domain(validated_spec),
            fixture_manifest=manifest,
            strategy=strategy.ref,
            targets=targets,
            targets_content_hash=fixture_target_positions_content_hash_v1(targets),
            engine=engine.ref,
            reference_result=reference_result,
            metric_input=metric_input,
            metric_input_content_hash=metric_input.content_hash,
            calculator=calculator,
            metric_set=metric_set,
            metric_set_content_hash=metric_set.content_hash,
        )
        result = replay_fixture_run_evidence_v2(
            evidence, runtime=validated_runtime, registry=active_registry
        )
    except (
        AttributeError,
        ArithmeticError,
        QuantVerifyError,
        TypeError,
        ValueError,
        ValidationError,
    ):
        failed = True
    if failed or result is None:
        raise FixtureReplayIntegrityError(
            "fixture evidence build failed integrity validation"
        ) from None
    return result


def replay_fixture_run_evidence_v2(
    evidence: FixtureRunEvidenceV2,
    *,
    runtime: RuntimeContext,
    registry: ImplementationRegistry | None = None,
) -> ReplayedFixtureEvidenceV2:
    failed = False
    replayed: FixtureRunEvidenceV2 | None = None
    try:
        validated = FixtureRunEvidenceV2.model_validate(evidence.model_dump(mode="python"))
        validated_runtime = RuntimeContext.model_validate(runtime.model_dump(mode="python"))
        spec = validated.fixture_run_spec.to_domain()
        if validated.run_id != spec.run_id(validated_runtime):
            raise ValueError("evidence run identity does not match the supplied runtime")
        _validate_spec_manifest(spec, validated.fixture_manifest)
        active_registry = registry or builtin_implementation_registry()
        strategy, engine = active_registry.resolve_versions(
            spec.experiment.strategy, spec.experiment.engine
        )
        if validated.strategy != strategy.ref or validated.engine != engine.ref:
            raise ValueError("evidence implementation refs do not match the registry")
        expected_targets = price_above_sma_targets(
            validated.fixture_manifest.bundle.bars,
            window=spec.strategy_parameters.window,
            schedule=validated.fixture_manifest.bundle.schedule,
        )
        if validated.targets != expected_targets:
            raise ValueError("evidence targets do not match strategy replay")
        expected_result = LongFlatReferenceEngine().run(
            validated.fixture_manifest.bundle.bars,
            expected_targets,
            initial_cash=spec.execution.initial_cash,
            commission_bps=spec.experiment.cost_model.commission_bps,
            slippage_bps=spec.experiment.cost_model.slippage_bps,
        )
        if validated.reference_result != expected_result:
            raise ValueError("evidence result does not match engine replay")
        _validate_first_close_flat(
            spec,
            validated.fixture_manifest,
            expected_targets,
            expected_result,
        )
        metric_input, calculator, metric_set = _derive_metrics(
            spec, validated.fixture_manifest, expected_result
        )
        if (
            validated.metric_input != metric_input
            or validated.calculator != calculator
            or validated.metric_set != metric_set
        ):
            raise ValueError("evidence metrics do not match calculator replay")
        replayed = validated
    except (
        AttributeError,
        ArithmeticError,
        QuantVerifyError,
        TypeError,
        ValueError,
        ValidationError,
    ):
        failed = True
    if failed or replayed is None:
        raise FixtureReplayIntegrityError(
            "fixture evidence replay failed integrity validation"
        ) from None
    return ReplayedFixtureEvidenceV2(evidence=replayed)


def fixture_target_positions_content_hash_v1(
    targets: tuple[TargetPosition, ...],
) -> str:
    if not isinstance(targets, tuple) or len(targets) > MAX_EVIDENCE_ROWS:
        raise ValueError("target positions must remain a bounded immutable tuple")
    validated = tuple(
        TargetPosition.model_validate(item.model_dump(mode="python")) for item in targets
    )
    payload = {
        "schema_version": "fixture-target-positions-v1",
        "targets": validated,
    }
    return hashlib.sha256(_canonical_payload_bytes(payload)).hexdigest()


def canonical_fixture_run_evidence_v2_bytes(evidence: FixtureRunEvidenceV2) -> bytes:
    failed = False
    encoded = b""
    try:
        validated = FixtureRunEvidenceV2.model_validate(evidence.model_dump(mode="python"))
        encoded = _canonical_payload_bytes(validated.model_dump(mode="python"))
        if len(encoded) > MAX_V2_CANONICAL_BYTES:
            raise ValueError("fixture evidence exceeds its canonical byte limit")
    except (
        AttributeError,
        OverflowError,
        QuantVerifyError,
        TypeError,
        UnicodeEncodeError,
        ValueError,
    ):
        failed = True
    if failed:
        raise FixtureReplayIntegrityError(
            "fixture evidence canonical serialization failed integrity validation"
        ) from None
    return encoded


def load_fixture_run_evidence_v2(document: bytes) -> FixtureRunEvidenceV2:
    failed = False
    result: FixtureRunEvidenceV2 | None = None
    try:
        if type(document) is not bytes or not document or len(document) > MAX_V2_CANONICAL_BYTES:
            raise ValueError("fixture evidence document has an invalid byte boundary")
        decoded = document.decode("utf-8")
        _require_bounded_json_depth(decoded)
        payload = json.loads(
            decoded,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_json_constant,
        )
        payload = _decode_decimal_objects(payload)
        result = FixtureRunEvidenceV2.model_validate(payload)
        if canonical_fixture_run_evidence_v2_bytes(result) != document:
            raise ValueError("fixture evidence document is not canonical")
    except (
        AttributeError,
        json.JSONDecodeError,
        MemoryError,
        OverflowError,
        RecursionError,
        TypeError,
        UnicodeDecodeError,
        ValidationError,
        ValueError,
    ):
        failed = True
    if failed or result is None:
        raise FixtureReplayIntegrityError(
            "fixture evidence canonical document failed integrity validation"
        ) from None
    return result


def _validate_spec_manifest(spec: FixtureRunSpec, manifest: FixtureManifest) -> None:
    bundle = manifest.bundle
    dataset = spec.experiment.dataset
    if not isinstance(dataset, DataSnapshot):
        raise ValueError("fixture evidence requires a DataSnapshot")
    consumed = spec.consumed_sessions
    schedule = bundle.schedule
    expected = (
        spec.fixture_id == bundle.fixture_id == dataset.dataset_id,
        dataset == bundle.snapshot,
        spec.experiment.frequency == bundle.frequency == BarFrequency.DAY,
        dataset.adjustment_mode == bundle.adjustment_mode,
        consumed.start_session == schedule.sessions[0].session,
        consumed.end_session == schedule.sessions[-1].session,
        consumed.session_count == len(schedule.sessions),
        consumed.schedule_id == schedule.schedule_id,
        consumed.schedule_content_hash == schedule.content_hash,
    )
    if not all(expected):
        raise ValueError("fixture run spec does not bind the complete fixture manifest")


def _derive_metrics(
    spec: FixtureRunSpec,
    manifest: FixtureManifest,
    result: ReferenceResult,
) -> tuple[MetricInputV2, MetricCalculatorRef, MetricSetV2]:
    _require_legacy_policy_decimals(spec.metrics)
    equity = tuple(
        EquityObservationV2(observed_on=point.session, equity=point.equity)
        for point in result.points
    )
    metric_input = MetricInputV2.from_equity(
        schedule=manifest.bundle.schedule,
        return_basis=spec.metrics.return_basis,
        annualization=AnnualizationPolicyV2(
            **spec.metrics.annualization.model_dump(mode="python")
        ),
        volatility_ddof=spec.metrics.volatility_ddof,
        risk_free=RiskFreePolicyV2(**spec.metrics.risk_free.model_dump(mode="python")),
        equity=equity,
    )
    calculator = MetricCalculatorRef.baseline()
    return metric_input, calculator, calculate_metric_set_v2(
        metric_input, calculator=calculator
    )


def _require_legacy_policy_decimals(policy: FixtureMetricPolicy) -> None:
    values = (
        policy.annualization.periods_per_year,
        policy.annualization.days_per_year,
        policy.risk_free.rate,
    )
    if any(type(value) is not Decimal for value in values):
        raise ValueError("fixture metric policy must preserve strict Decimal values")


def _validate_first_close_flat(
    spec: FixtureRunSpec,
    manifest: FixtureManifest,
    targets: tuple[TargetPosition, ...],
    result: ReferenceResult,
) -> None:
    schedule = manifest.bundle.schedule
    if len(result.points) != len(schedule.sessions):
        raise ValueError("reference points must cover the complete fixture schedule")
    if tuple(point.session for point in result.points) != tuple(
        session.session for session in schedule.sessions
    ):
        raise ValueError("reference points must match the fixture schedule")
    first = result.points[0]
    zero = Decimal("0")
    if (
        first.cash != spec.execution.initial_cash
        or first.equity != spec.execution.initial_cash
        or first.quantity != zero
        or first.target_weight != zero
        or first.actual_weight != zero
    ):
        raise ValueError("fixture evidence violates first-close-flat-v1")
    first_open = schedule.sessions[0].session_open_at
    if any(target.effective_at == first_open for target in targets) or any(
        trade.executed_at == first_open for trade in result.trades
    ):
        raise ValueError("fixture evidence cannot trade at the first session open")


def _canonical_payload_bytes(value: Any) -> bytes:
    return json.dumps(
        canonicalize_v2(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _decode_decimal_objects(value: Any) -> Any:
    if isinstance(value, list):
        return [_decode_decimal_objects(item) for item in value]
    if isinstance(value, dict):
        if set(value) == {"coefficient", "exponent"}:
            return parse_decimal_value_v1(value)
        return {key: _decode_decimal_objects(item) for key, item in value.items()}
    return value


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate fixture evidence JSON key")
        result[key] = value
    return result


def _reject_json_constant(_: str) -> Any:
    raise ValueError("non-finite fixture evidence JSON number")


def _require_bounded_json_depth(document: str) -> None:
    depth = 0
    in_string = False
    escaped = False
    for character in document:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character in "[{":
            depth += 1
            if depth > MAX_V2_JSON_NESTING:
                raise ValueError("fixture evidence JSON nesting exceeds the limit")
        elif character in "]}":
            depth -= 1
            if depth < 0:
                raise ValueError("fixture evidence JSON nesting is invalid")
