from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal, localcontext
from unittest import TestCase

from pydantic import ValidationError
from pydantic_core import PydanticSerializationError

import quantverify.application as application_api
from quantverify.application import (
    ApplicationErrorCode,
    ApplicationFailure,
    ConsumedSessionRange,
    DailyTrendParameters,
    FixtureMetricPolicy,
    FixtureRunSpec,
    InspectResult,
    InspectRunCommand,
    PlanFixtureCommand,
    PlanResult,
    ReferenceExecutionSpec,
)
from quantverify.core.enums import AdjustmentMode, BarFrequency
from quantverify.core.models import (
    ArtifactRef,
    CostModel,
    DatasetReleaseRef,
    DataSnapshot,
    EngineVersion,
    ExecutionAssumptions,
    ExperimentConfig,
    RuntimeContext,
    StrategyVersion,
    TimeRange,
)
from quantverify.metrics.models import (
    AnnualizationPolicy,
    ReturnBasis,
    RiskFreePolicy,
    RiskFreeRateKind,
)
from tests.test_dataset_release_contract import release


def experiment(**updates: object) -> ExperimentConfig:
    values: dict[str, object] = {
        "strategy": StrategyVersion(
            strategy_id="daily_trend", version="1.0.0", code_hash="abc1234"
        ),
        "universe_id": "spy",
        "dataset": DataSnapshot(
            dataset_id="spy-daily-fixture",
            content_hash="a" * 64,
            schema_version="normalized-bar-v1",
            source="fixture",
            captured_at=datetime(2026, 8, 12, tzinfo=UTC),
            adjustment_mode=AdjustmentMode.TOTAL_RETURN,
        ),
        "period": TimeRange(
            start=datetime(2020, 1, 1, tzinfo=UTC),
            end=datetime(2025, 1, 1, tzinfo=UTC),
        ),
        "frequency": BarFrequency.DAY,
        "parameters": {"window": 3},
        "benchmark_id": "SPY:buy_hold",
        "cost_model": CostModel(
            commission_bps=Decimal("2.5"), slippage_bps=Decimal("3")
        ),
        "execution": ExecutionAssumptions(),
        "engine": EngineVersion(engine_id="reference", version="0.1.0"),
        "base_currency": "USD",
        "random_seed": 42,
    }
    values.update(updates)
    return ExperimentConfig.model_validate(values)


def metric_policy() -> FixtureMetricPolicy:
    return FixtureMetricPolicy(
        return_basis=ReturnBasis.NET_OF_COSTS,
        annualization=AnnualizationPolicy(
            policy_id="xnas-daily-v1",
            periods_per_year=Decimal("252"),
            days_per_year=Decimal("365.2425"),
        ),
        volatility_ddof=1,
        risk_free=RiskFreePolicy(
            policy_id="fixture-zero-rf-v1",
            kind=RiskFreeRateKind.ANNUAL_EFFECTIVE,
            rate=Decimal("0"),
            source_id="fixture-assumption",
            source_version="1",
        ),
    )


def spec(**updates: object) -> FixtureRunSpec:
    values: dict[str, object] = {
        "fixture_id": "spy-daily-fixture",
        "experiment": experiment(),
        "strategy_parameters": DailyTrendParameters(window=3),
        "consumed_sessions": ConsumedSessionRange(
            start_session=date(2020, 1, 2),
            end_session=date(2024, 12, 31),
            session_count=1258,
            schedule_id="session-schedule_" + "1" * 24,
            schedule_content_hash="2" * 64,
        ),
        "execution": ReferenceExecutionSpec(initial_cash=Decimal("10000")),
        "metrics": metric_policy(),
    }
    values.update(updates)
    return FixtureRunSpec.model_validate(values)


def runtime(**updates: object) -> RuntimeContext:
    values = {
        "source_commit": "abcdef1",
        "environment_lock_hash": "3" * 64,
        "worker_id": "mac-m1-local",
    }
    values.update(updates)
    return RuntimeContext.model_validate(values)


class FixtureRunSpecTests(TestCase):
    def test_fixed_identity_binds_missing_execution_and_metric_inputs(self) -> None:
        baseline = spec()
        self.assertEqual(
            baseline.fixture_run_spec_id,
            "fixture-run-spec_486b2dee5c51dc53aa956d8b",
        )
        changes = (
            {"execution": ReferenceExecutionSpec(initial_cash=Decimal("20000"))},
            {
                "metrics": metric_policy().model_copy(
                    update={"volatility_ddof": 0}
                )
            },
            {
                "consumed_sessions": baseline.consumed_sessions.model_copy(
                    update={"schedule_content_hash": "4" * 64}
                )
            },
            {
                "metrics": metric_policy().model_copy(
                    update={
                        "risk_free": metric_policy().risk_free.model_copy(
                            update={"source_version": "2"}
                        )
                    }
                )
            },
        )
        for update in changes:
            with self.subTest(update=update):
                self.assertNotEqual(
                    baseline.fixture_run_spec_id,
                    spec(**update).fixture_run_spec_id,
                )

        first_run = baseline.run_id(runtime())
        self.assertEqual(first_run, baseline.run_id(runtime()))
        self.assertNotEqual(first_run, baseline.run_id(runtime(worker_id="other")))
        self.assertEqual(
            baseline.fixture_run_spec_id,
            spec(
                execution=ReferenceExecutionSpec(initial_cash=Decimal("10000.00"))
            ).fixture_run_spec_id,
        )

    def test_spec_identity_normalizes_decimal_scale_and_equivalent_instants(self) -> None:
        baseline = spec()
        offset = timezone(timedelta(hours=8))
        offset_experiment = experiment(
            dataset=experiment().dataset.model_copy(
                update={
                    "captured_at": datetime(2026, 8, 12, 8, tzinfo=offset),
                }
            ),
            period=TimeRange(
                start=datetime(2020, 1, 1, 8, tzinfo=offset),
                end=datetime(2025, 1, 1, 8, tzinfo=offset),
            ),
            cost_model=CostModel(
                commission_bps=Decimal("2.50"),
                slippage_bps=Decimal("3.00"),
            ),
        )
        equivalent = spec(
            experiment=offset_experiment,
            execution=ReferenceExecutionSpec(initial_cash=Decimal("10000.00")),
        )
        self.assertEqual(equivalent.fixture_run_spec_id, baseline.fixture_run_spec_id)

    def test_decimal_identity_is_context_independent_and_collision_resistant(self) -> None:
        first = "12345678901234567890123456781"
        second = "12345678901234567890123456782"
        first_ids: set[str] = set()
        second_ids: set[str] = set()
        for precision in (10, 28, 50):
            with localcontext() as context:
                context.prec = precision
                first_ids.add(
                    spec(
                        execution=ReferenceExecutionSpec(initial_cash=Decimal(first))
                    ).fixture_run_spec_id
                )
                second_ids.add(
                    spec(
                        execution=ReferenceExecutionSpec(initial_cash=Decimal(second))
                    ).fixture_run_spec_id
                )
        self.assertEqual(len(first_ids), 1)
        self.assertEqual(len(second_ids), 1)
        self.assertNotEqual(first_ids, second_ids)

    def test_fixture_mode_rejects_release_and_alias_mismatch(self) -> None:
        release_dataset: DatasetReleaseRef = release()
        with self.assertRaisesRegex(ValidationError, "legacy DataSnapshot"):
            spec(
                experiment=experiment(
                    dataset=release_dataset,
                    universe_id=release_dataset.single_asset_universe_id,
                )
            )
        with self.assertRaisesRegex(ValidationError, "implicit latest"):
            spec(fixture_id="latest")
        alternate_source = spec(
            experiment=experiment(
                dataset=experiment().dataset.model_copy(update={"source": "golden_fixture"})
            )
        )
        self.assertEqual(alternate_source.fixture_id, "spy-daily-fixture")
        with self.assertRaisesRegex(ValidationError, "daily input"):
            spec(experiment=experiment(frequency=BarFrequency.HOUR))

    def test_only_static_daily_trend_reference_capability_is_admitted(self) -> None:
        invalid_experiments = (
            experiment(
                strategy=StrategyVersion(
                    strategy_id="ma_cross", version="1", code_hash="abc1234"
                )
            ),
            experiment(parameters={"window": True}),
            experiment(parameters={"window": 3, "extra": 1}),
            experiment(engine=EngineVersion(engine_id="vectorized", version="1")),
            experiment(cost_model=CostModel(minimum_commission=Decimal("1"))),
            experiment(cost_model=CostModel(stamp_duty_bps=Decimal("1"))),
            experiment(cost_model=CostModel(slippage_bps=Decimal("10000"))),
            experiment(execution=ExecutionAssumptions(signal_lag_bars=2)),
            experiment(execution=ExecutionAssumptions(allow_fractional=False)),
        )
        for candidate in invalid_experiments:
            with self.subTest(candidate=candidate), self.assertRaises(ValidationError):
                spec(experiment=candidate)
        with self.assertRaises(ValidationError):
            DailyTrendParameters(window=True)
        with self.assertRaisesRegex(ValidationError, "strict non-bool"):
            spec(
                experiment=experiment(parameters={"window": True}),
                strategy_parameters=DailyTrendParameters(window=1),
            )
        with self.assertRaisesRegex(ValidationError, "strict non-bool"):
            spec(
                experiment=experiment(parameters={"window": Decimal("3")}),
                strategy_parameters=DailyTrendParameters(window=3),
            )

    def test_identity_revalidates_unsafe_nested_mutations(self) -> None:
        baseline = spec()
        baseline.experiment.parameters["window"] = 4
        with self.assertRaisesRegex(ValidationError, "strict window"):
            _ = baseline.fixture_run_spec_id

        unsafe = spec().model_copy(
            update={
                "execution": spec().execution.model_copy(
                    update={"initial_cash": Decimal("-1")}
                )
            }
        )
        with self.assertRaises(ValidationError):
            _ = unsafe.fixture_run_spec_id

    def test_plan_result_rederives_all_identities(self) -> None:
        command = PlanFixtureCommand(spec=spec(), runtime=runtime())
        plan = PlanResult.create(command)
        self.assertEqual(plan.experiment_id, command.spec.experiment.experiment_id)
        self.assertEqual(plan.fixture_run_spec_id, command.spec.fixture_run_spec_id)
        self.assertEqual(plan.run_id, command.spec.run_id(command.runtime))
        replayed = PlanResult.model_validate_json(plan.model_dump_json())
        self.assertEqual(replayed, plan)

        for field in ("experiment_id", "fixture_run_spec_id", "run_id"):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                PlanResult.model_validate(
                    {**plan.model_dump(mode="python"), field: "run_" + "f" * 24}
                )

        unsafe_plan = plan.model_copy(update={"run_id": "run_" + "f" * 24})
        with self.assertRaisesRegex(
            PydanticSerializationError, "PlanResult failed integrity validation"
        ) as captured:
            unsafe_plan.model_dump(mode="json")
        self.assertNotIn("ffffffff", str(captured.exception))
        unsafe_command = command.model_copy(
            update={
                "spec": command.spec.model_copy(
                    update={
                        "execution": command.spec.execution.model_copy(
                            update={"initial_cash": Decimal("-1")}
                        )
                    }
                )
            }
        )
        with self.assertRaisesRegex(
            PydanticSerializationError, "PlanResult failed integrity validation"
        ):
            plan.model_copy(update={"command": unsafe_command}).model_dump(mode="json")

    def test_scientific_integer_fields_reject_bool(self) -> None:
        with self.assertRaises(ValidationError):
            ConsumedSessionRange(
                start_session=date(2020, 1, 2),
                end_session=date(2020, 1, 2),
                session_count=True,
                schedule_id="session-schedule_" + "1" * 24,
                schedule_content_hash="2" * 64,
            )
        with self.assertRaises(ValidationError):
            FixtureMetricPolicy(
                **{
                    **metric_policy().model_dump(mode="python"),
                    "volatility_ddof": True,
                }
            )

    def test_run_identity_keeps_legacy_experiment_id_as_compatibility_anchor(self) -> None:
        offset = timezone(timedelta(hours=8))
        offset_experiment = experiment(
            period=TimeRange(
                start=datetime(2020, 1, 1, 8, tzinfo=offset),
                end=datetime(2025, 1, 1, 8, tzinfo=offset),
            )
        )
        equivalent = spec(experiment=offset_experiment)
        baseline = spec()
        self.assertEqual(equivalent.fixture_run_spec_id, baseline.fixture_run_spec_id)
        self.assertNotEqual(
            equivalent.experiment.experiment_id,
            baseline.experiment.experiment_id,
        )
        self.assertNotEqual(equivalent.run_id(runtime()), baseline.run_id(runtime()))


class BoundaryResultTests(TestCase):
    def test_run_handler_and_receipt_are_absent_until_core06(self) -> None:
        self.assertFalse(hasattr(application_api, "RunFixtureHandler"))
        self.assertFalse(hasattr(application_api, "RunReceipt"))

    def test_inspect_command_requires_explicit_portable_manifest(self) -> None:
        accepted = "run_manifests/run_abc123def456/hash/stamp-hash.json"
        self.assertEqual(InspectRunCommand(manifest_path=accepted).manifest_path, accepted)
        for invalid in (
            "latest",
            "run_manifests/latest/file.json",
            "../file.json",
            "/tmp/file.json",
            "run_manifests\\file.json",
            "run_manifests/file.txt",
            "run_manifests//file.json",
            "run_manifests/latest.json",
            "run_manifests/evil\x00.json",
            "run_manifests/evil\n.json",
            " run_manifests/file.json",
            "run_manifests/file.json ",
            "run_manifests/file.json\t",
            b"run_manifests/file.json",
            b" run_manifests/file.json ",
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                InspectRunCommand(manifest_path=invalid)

    def test_inspect_result_revalidates_before_serialization(self) -> None:
        manifest_hash = "d" * 64
        artifact_hash = "c" * 64
        run_id = "run_" + "b" * 24
        result = InspectResult(
            experiment_id="exp_" + "a" * 24,
            run_id=run_id,
            artifact=ArtifactRef(
                kind="reference_result",
                uri=f"artifacts/reference_result/cc/{artifact_hash}.json",
                content_hash=artifact_hash,
                schema_version="reference-result-v1",
            ),
            manifest_path=(
                f"run_manifests/{run_id}/{artifact_hash}/"
                f"20260812T010203123456Z-{manifest_hash}.json"
            ),
            manifest_hash=manifest_hash,
            point_count=2,
            trade_count=1,
        )
        self.assertEqual(
            result.model_dump(mode="json")["trust_scope"],
            "artifact_v1_integrity_only",
        )
        unsafe = result.model_copy(update={"trust_scope": "replayable"})
        with self.assertRaisesRegex(
            PydanticSerializationError, "InspectResult failed integrity validation"
        ):
            unsafe.model_dump(mode="json")

        for raw_path in (" " + result.manifest_path, b" x.json "):
            with self.subTest(raw_path=raw_path), self.assertRaisesRegex(
                PydanticSerializationError, "InspectResult failed integrity validation"
            ):
                result.model_copy(update={"manifest_path": raw_path}).model_dump(mode="json")

        invalid_artifacts = (
            result.artifact.model_copy(update={"kind": "anything"}),
            result.artifact.model_copy(update={"schema_version": "arbitrary-v9"}),
            result.artifact.model_copy(update={"uri": "latest://bad"}),
        )
        for artifact in invalid_artifacts:
            with self.subTest(artifact=artifact), self.assertRaises(ValidationError):
                InspectResult.model_validate(
                    {**result.model_dump(mode="python"), "artifact": artifact}
                )
        unsafe_artifacts = (
            result.artifact.model_copy(update={"kind": " reference_result"}),
            result.artifact.model_copy(
                update={"schema_version": "reference-result-v1 "}
            ),
            result.artifact.model_copy(update={"uri": result.artifact.uri + " "}),
            result.artifact.model_copy(
                update={"content_hash": " " + result.artifact.content_hash}
            ),
        )
        for artifact in unsafe_artifacts:
            with self.subTest(artifact=artifact), self.assertRaisesRegex(
                PydanticSerializationError, "InspectResult failed integrity validation"
            ):
                result.model_copy(update={"artifact": artifact}).model_dump(mode="json")
        invalid_paths = (
            result.manifest_path.replace(run_id, "run_" + "e" * 24),
            result.manifest_path.replace(artifact_hash, "e" * 64),
            result.manifest_path.replace(manifest_hash, "e" * 64),
            result.manifest_path.replace("20260812T010203123456Z", "bad-stamp"),
            result.manifest_path.replace(
                "20260812T010203123456Z", "20260230T250061999999Z"
            ),
            result.manifest_path.replace(
                "20260812T010203123456Z", "99999999T999999999999Z"
            ),
            result.manifest_path.replace(
                "20260812T010203123456Z", "00000000T000000000000Z"
            ),
            f"run_manifests/{run_id}/{artifact_hash}/extra/"
            f"20260812T010203123456Z-{manifest_hash}.json",
        )
        for manifest_path in invalid_paths:
            with self.subTest(manifest_path=manifest_path), self.assertRaises(ValidationError):
                InspectResult.model_validate(
                    {**result.model_dump(mode="python"), "manifest_path": manifest_path}
                )
        for field in ("point_count", "trade_count"):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                InspectResult.model_validate(
                    {**result.model_dump(mode="python"), field: True}
                )

    def test_failure_has_fixed_code_and_exit_mapping_without_raw_message(self) -> None:
        expected = {
            ApplicationErrorCode.CONFIG_INVALID: 2,
            ApplicationErrorCode.FIXTURE_REJECTED: 3,
            ApplicationErrorCode.REAL_DATA_UNAVAILABLE: 3,
            ApplicationErrorCode.PREFLIGHT_REJECTED: 3,
            ApplicationErrorCode.EXECUTION_FAILED: 4,
            ApplicationErrorCode.ARTIFACT_FAILED: 5,
            ApplicationErrorCode.INTERNAL_ERROR: 70,
        }
        for code, exit_code in expected.items():
            with self.subTest(code=code):
                failure = ApplicationFailure(code=code)
                self.assertEqual(failure.exit_code, exit_code)
                self.assertNotIn("message", failure.model_dump())

        unsafe = ApplicationFailure(
            code=ApplicationErrorCode.CONFIG_INVALID
        ).model_copy(update={"code": "raw-secret"})
        self.assertEqual(unsafe.exit_code, 70)
        serialized = unsafe.model_dump(mode="json")
        self.assertEqual(serialized["code"], ApplicationErrorCode.INTERNAL_ERROR)
        self.assertNotIn("raw-secret", str(serialized))
