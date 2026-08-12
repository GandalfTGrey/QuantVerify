from datetime import UTC, datetime
from decimal import Decimal
from unittest import TestCase

from pydantic import ValidationError

from quantverify.core.enums import AdjustmentMode, AssetClass, BarFrequency
from quantverify.core.identity import stable_hash
from quantverify.core.models import (
    AssetId,
    CostModel,
    DataSnapshot,
    EngineVersion,
    ExperimentConfig,
    ExperimentIdentity,
    RuntimeContext,
    StrategyVersion,
    TargetPosition,
    TimeRange,
    ValidationConfig,
)


def make_config(parameters: dict[str, int] | None = None) -> ExperimentConfig:
    return ExperimentConfig(
        strategy=StrategyVersion(strategy_id="ma_cross", version="1.0.0", code_hash="abc1234"),
        universe_id="spy",
        dataset=DataSnapshot(
            dataset_id="spy-daily",
            content_hash="a" * 64,
            schema_version="1",
            source="fixture",
            captured_at=datetime(2026, 1, 1, tzinfo=UTC),
            adjustment_mode=AdjustmentMode.TOTAL_RETURN,
        ),
        period=TimeRange(
            start=datetime(2020, 1, 1, tzinfo=UTC),
            end=datetime(2025, 1, 1, tzinfo=UTC),
        ),
        frequency=BarFrequency.DAY,
        parameters=parameters or {"short": 10, "long": 50},
        benchmark_id="SPY:buy_hold",
        cost_model=CostModel(commission_bps=Decimal("2.5")),
        engine=EngineVersion(engine_id="reference", version="0.1.0"),
    )


class IdentityTests(TestCase):
    def test_parameter_order_does_not_change_experiment_identity(self) -> None:
        left = make_config({"short": 10, "long": 50})
        right = make_config({"long": 50, "short": 10})
        self.assertEqual(left.experiment_id, right.experiment_id)

    def test_scientific_input_changes_experiment_identity(self) -> None:
        left = make_config({"short": 10, "long": 50})
        right = make_config({"short": 20, "long": 50})
        self.assertNotEqual(left.experiment_id, right.experiment_id)

    def test_runtime_changes_run_but_not_experiment_identity(self) -> None:
        config = make_config()
        runtime_a = RuntimeContext(
            source_commit="abc1234",
            environment_lock_hash="b" * 64,
            worker_id="local-a",
        )
        runtime_b = runtime_a.model_copy(update={"worker_id": "local-b"})
        identity_a = ExperimentIdentity.create(config, runtime_a)
        identity_b = ExperimentIdentity.create(config, runtime_b)
        self.assertEqual(identity_a.experiment_id, identity_b.experiment_id)
        self.assertNotEqual(identity_a.run_id, identity_b.run_id)

    def test_validation_split_must_sum_to_one(self) -> None:
        with self.assertRaises(ValidationError):
            ValidationConfig(train_fraction=0.7, validation_fraction=0.2, test_fraction=0.2)

    def test_target_position_requires_future_effective_time(self) -> None:
        now = datetime(2026, 1, 1, tzinfo=UTC)
        with self.assertRaises(ValidationError):
            TargetPosition(
                asset=AssetId(
                    symbol="SPY",
                    venue="ARCX",
                    asset_class=AssetClass.ETF,
                    currency="USD",
                ),
                decision_at=now,
                effective_at=now,
                weight=Decimal("1"),
            )

    def test_time_range_requires_timezone(self) -> None:
        with self.assertRaises(ValidationError):
            TimeRange(start=datetime(2020, 1, 1), end=datetime(2021, 1, 1))

    def test_identity_rejects_non_finite_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "non-finite float"):
            stable_hash({"value": float("nan")}, namespace="test")

    def test_identity_rejects_non_string_mapping_keys(self) -> None:
        with self.assertRaisesRegex(TypeError, "string keys"):
            stable_hash({1: "value"}, namespace="test")

    def test_identity_rejects_invalid_namespace_and_digest_length(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not be blank"):
            stable_hash("value", namespace=" ")
        with self.assertRaisesRegex(ValueError, "between 12 and 64"):
            stable_hash("value", namespace="test", length=8)
