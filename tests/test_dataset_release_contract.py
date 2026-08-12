from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest import TestCase

from pydantic import ValidationError

from quantverify import DatasetReleaseRef as PublicDatasetReleaseRef
from quantverify import EligibleInterval as PublicEligibleInterval
from quantverify.core.enums import (
    AdjustmentMode,
    AssetClass,
    BarFrequency,
    SeriesSourceKind,
    SessionLabelPolicy,
)
from quantverify.core.models import (
    AssetId,
    CalendarArtifactRef,
    CostModel,
    DatasetReleaseRef,
    EligibleInterval,
    EngineVersion,
    ExperimentConfig,
    SeriesDescriptor,
    SessionSchedule,
    StrategyVersion,
    TimeRange,
    TradingSession,
)

ASSET = AssetId(
    symbol="QQQ",
    venue="XNAS",
    asset_class=AssetClass.ETF,
    currency="USD",
)


def calendar_ref(**updates: object) -> CalendarArtifactRef:
    values: dict[str, object] = {
        "calendar_id": "XNYS",
        "calendar_version": "fixture-2026a",
        "timezone": "America/New_York",
        "session_label_policy": SessionLabelPolicy.CLOSE_LOCAL_DATE,
        "source_id": "fixture-calendar",
        "source_version": "1",
        "content_hash": "a" * 64,
    }
    values.update(updates)
    return CalendarArtifactRef.model_validate(values)


def interval(
    start: date = date(2020, 1, 2),
    end: date = date(2024, 12, 31),
    *,
    marker: str = "b",
    count: int = 1258,
    report_marker: str = "d",
    warnings: tuple[str, ...] = ("dqf_" + "2" * 24,),
) -> EligibleInterval:
    return EligibleInterval(
        start_session=start,
        end_session=end,
        session_count=count,
        expected_sessions_hash=marker * 64,
        quality_report_id="dqr_" + report_marker * 24,
        quality_report_content_hash=report_marker * 64,
        warning_finding_ids=warnings,
    )


def release(**updates: object) -> DatasetReleaseRef:
    values: dict[str, object] = {
        "asset": ASSET,
        "frequency": BarFrequency.DAY,
        "adjustment_mode": AdjustmentMode.RAW,
        "normalized_content_hash": "c" * 64,
        "normalized_schema_version": "normalized-bar-v1",
        "normalizer_id": "quantverify-normalizer",
        "normalizer_version": "1.0.0",
        "selected_evidence_id": "dqe_" + "d" * 24,
        "selected_normalized_input_id": "dqi_" + "e" * 24,
        "quality_suite_id": "quantverify-quality-suite",
        "quality_suite_version": "2",
        "quality_policy_id": "market-data-research-v2",
        "quality_policy_version": "1",
        "quality_policy_hash": "f" * 64,
        "calendar": calendar_ref(),
        "schedule_id": "session-schedule_" + "1" * 24,
        "schedule_content_hash": "1" * 64,
        "schedule_requested_start": date(2020, 1, 2),
        "schedule_requested_end": date(2024, 12, 31),
        "schedule_session_count": 1258,
        "eligible_intervals": (interval(),),
    }
    values.update(updates)
    return DatasetReleaseRef.model_validate(values)


def consumed_schedule(
    sessions: tuple[date, ...],
    *,
    calendar: CalendarArtifactRef | None = None,
) -> SessionSchedule:
    return SessionSchedule.create(
        requested_start=sessions[0],
        requested_end=sessions[-1],
        calendar=calendar or calendar_ref(),
        sessions=tuple(
            TradingSession(
                session=session,
                session_open_at=datetime(
                    session.year, session.month, session.day, 14, 30, tzinfo=UTC
                ),
                session_close_at=datetime(
                    session.year, session.month, session.day, 21, tzinfo=UTC
                ),
            )
            for session in sessions
        ),
    )


def experiment(dataset: DatasetReleaseRef) -> ExperimentConfig:
    return ExperimentConfig(
        strategy=StrategyVersion(
            strategy_id="daily_trend",
            version="1.0.0",
            code_hash="abc1234",
        ),
        universe_id=dataset.single_asset_universe_id,
        dataset=dataset,
        period=TimeRange(
            start=datetime(2020, 1, 2, tzinfo=UTC),
            end=datetime(2025, 1, 1, tzinfo=UTC),
        ),
        frequency=BarFrequency.DAY,
        benchmark_id="QQQ:buy_hold",
        cost_model=CostModel(commission_bps=Decimal("1")),
        engine=EngineVersion(engine_id="reference", version="1"),
    )


class EligibleIntervalTests(TestCase):
    def test_release_contracts_are_exported_from_the_public_package(self) -> None:
        self.assertIs(PublicDatasetReleaseRef, DatasetReleaseRef)
        self.assertIs(PublicEligibleInterval, EligibleInterval)

    def test_interval_is_inclusive_and_requires_ordered_bounds(self) -> None:
        candidate = interval()
        self.assertEqual(candidate.start_session, date(2020, 1, 2))
        self.assertEqual(candidate.end_session, date(2024, 12, 31))
        with self.assertRaisesRegex(ValidationError, "start must not follow"):
            interval(date(2024, 1, 2), date(2024, 1, 1))


class DatasetReleaseRefTests(TestCase):
    def test_release_identity_is_fixed_and_full_contract_sensitive(self) -> None:
        baseline = release()
        self.assertEqual(
            baseline.release_id,
            "drel_4310630a375d1f2d79eeb382",
        )
        changes = (
            {"normalized_content_hash": "3" * 64},
            {"normalizer_version": "1.0.1"},
            {"normalized_schema_version": "normalized-bar-v2"},
            {"selected_evidence_id": "dqe_" + "4" * 24},
            {"selected_normalized_input_id": "dqi_" + "5" * 24},
            {"quality_policy_hash": "6" * 64},
            {"schedule_content_hash": "7" * 64},
            {"schedule_id": "session-schedule_" + "7" * 24},
            {"calendar": calendar_ref(calendar_version="fixture-2026b")},
            {
                "eligible_intervals": (
                    interval(end=date(2024, 12, 30), count=1257),
                )
            },
            {
                "eligible_intervals": (
                    interval(report_marker="8", warnings=("dqf_" + "8" * 24,)),
                )
            },
        )
        for update in changes:
            with self.subTest(update=update):
                self.assertNotEqual(baseline.release_id, release(**update).release_id)

        replayed = DatasetReleaseRef.model_validate_json(baseline.model_dump_json())
        self.assertEqual(replayed, baseline)
        self.assertEqual(replayed.release_id, baseline.release_id)

    def test_one_interval_must_wholly_contain_consumed_schedule(self) -> None:
        candidate = release(
            eligible_intervals=(
                interval(date(2020, 1, 2), date(2020, 6, 30), count=124),
                interval(
                    date(2020, 7, 2),
                    date(2020, 12, 31),
                    marker="3",
                    count=127,
                    report_marker="e",
                ),
            ),
            schedule_requested_end=date(2020, 12, 31),
            schedule_session_count=251,
        )
        self.assertTrue(
            candidate.structurally_supports_consumed_schedule(
                consumed_schedule((date(2020, 1, 2), date(2020, 6, 30)))
            )
        )
        self.assertTrue(
            candidate.structurally_supports_consumed_schedule(
                consumed_schedule((date(2020, 7, 2),))
            )
        )
        self.assertFalse(
            candidate.structurally_supports_consumed_schedule(
                consumed_schedule((date(2020, 6, 30), date(2020, 7, 2)))
            )
        )
        self.assertFalse(
            candidate.structurally_supports_consumed_schedule(
                consumed_schedule((date(2019, 12, 31), date(2020, 1, 2)))
            )
        )
        self.assertFalse(
            candidate.structurally_supports_consumed_schedule(
                consumed_schedule(
                    (date(2020, 1, 2),),
                    calendar=calendar_ref(calendar_version="different"),
                )
            )
        )

    def test_intervals_and_exception_references_are_canonical(self) -> None:
        early = interval(date(2020, 1, 2), date(2020, 6, 30), count=124)
        late = interval(
            date(2020, 7, 2),
            date(2020, 12, 31),
            marker="3",
            count=127,
            report_marker="e",
        )
        with self.assertRaisesRegex(ValidationError, "sorted"):
            release(eligible_intervals=(late, early))
        with self.assertRaisesRegex(ValidationError, "must not overlap"):
            release(
                eligible_intervals=(
                    early,
                    interval(date(2020, 6, 30), count=127, report_marker="e"),
                )
            )
        with self.assertRaisesRegex(ValidationError, "must be unique"):
            interval(warnings=("dqf_" + "2" * 24, "dqf_" + "2" * 24))
        with self.assertRaisesRegex(ValidationError, "must be sorted"):
            interval(warnings=("dqf_" + "3" * 24, "dqf_" + "2" * 24))
        with self.assertRaisesRegex(ValidationError, "identity is invalid"):
            interval(warnings=("not-a-finding",))
        with self.assertRaisesRegex(ValidationError, "fit the pinned schedule"):
            release(
                eligible_intervals=(
                    interval(date(2019, 12, 31), date(2024, 12, 31), count=1259),
                )
            )
        with self.assertRaisesRegex(ValidationError, "distinct quality report"):
            release(
                eligible_intervals=(
                    interval(date(2020, 1, 2), date(2020, 6, 30), count=124),
                    interval(
                        date(2020, 7, 2),
                        date(2020, 12, 31),
                        marker="3",
                        count=127,
                    ),
                )
            )
        with self.assertRaisesRegex(ValidationError, "exceed the pinned schedule"):
            release(
                schedule_session_count=200,
                eligible_intervals=(interval(count=201),),
            )

    def test_v1_rejects_adjusted_release_until_typed_action_evidence_exists(self) -> None:
        for mode in (AdjustmentMode.SPLIT_ADJUSTED, AdjustmentMode.TOTAL_RETURN):
            with self.subTest(mode=mode), self.assertRaisesRegex(
                ValidationError, "requires RAW"
            ):
                release(adjustment_mode=mode)

    def test_v1_rejects_non_daily_or_unaccepted_quality_suite_claims(self) -> None:
        with self.assertRaisesRegex(ValidationError, "requires daily"):
            release(frequency=BarFrequency.WEEK)
        with self.assertRaisesRegex(ValidationError, "accepted A3 suite"):
            release(quality_suite_version="999")
        with self.assertRaises(ValidationError):
            release(source_resolution_policy_id="latest")
        with self.assertRaises(ValidationError):
            release(source_resolution_policy_version="2")

    def test_identity_and_preflight_revalidate_unsafe_model_copies(self) -> None:
        candidate = release()
        invalid_calendar = candidate.calendar.model_copy(update={"content_hash": "bad"})
        unsafe_values = (
            candidate.model_copy(update={"normalized_content_hash": "bad"}),
            candidate.model_copy(update={"calendar": invalid_calendar}),
            candidate.model_copy(update={"eligible_intervals": []}),
            candidate.model_copy(update={"eligible_intervals": ({"bad": "value"},)}),
            candidate.model_copy(
                update={
                    "eligible_intervals": [
                        candidate.eligible_intervals[0].model_copy(
                            update={"warning_finding_ids": []}
                        )
                    ]
                }
            ),
        )
        for unsafe in unsafe_values:
            with self.subTest(unsafe=unsafe), self.assertRaises((ValidationError, ValueError)):
                _ = unsafe.release_id
            with self.subTest(unsafe=unsafe), self.assertRaises(
                (ValidationError, ValueError)
            ):
                unsafe.structurally_supports_consumed_schedule(
                    consumed_schedule((date(2020, 1, 2), date(2020, 1, 3)))
                )

        unsafe_schedule = consumed_schedule((date(2020, 1, 2),)).model_copy(
            update={"content_hash": "bad"}
        )
        with self.assertRaisesRegex(ValueError, "failed integrity validation"):
            candidate.structurally_supports_consumed_schedule(unsafe_schedule)

    def test_series_descriptor_can_bind_release_identity_without_latest_alias(self) -> None:
        candidate = release()
        descriptor = SeriesDescriptor(
            asset=candidate.asset,
            frequency=candidate.frequency,
            adjustment_mode=candidate.adjustment_mode,
            source_kind=SeriesSourceKind.DATASET_RELEASE,
            source_id=candidate.release_id,
            source_content_hash=candidate.normalized_content_hash,
            source_schema_version=candidate.normalized_schema_version,
            producer_id=candidate.normalizer_id,
            producer_version=candidate.normalizer_version,
            calendar=candidate.calendar,
        )
        self.assertEqual(descriptor.source_id, candidate.release_id)
        self.assertNotIn("latest", descriptor.source_id)


class DatasetReleaseExperimentIdentityTests(TestCase):
    def test_experiment_identity_binds_complete_dataset_release(self) -> None:
        first = experiment(release())
        second = experiment(release(quality_policy_hash="3" * 64))
        self.assertNotEqual(first.experiment_id, second.experiment_id)

    def test_experiment_frequency_must_match_release(self) -> None:
        candidate = experiment(release())
        with self.assertRaisesRegex(ValidationError, "frequency must match"):
            ExperimentConfig.model_validate(
                {**candidate.model_dump(mode="python"), "frequency": BarFrequency.WEEK}
            )

    def test_release_backed_experiment_requires_canonical_single_asset_universe(self) -> None:
        candidate = experiment(release())
        self.assertEqual(candidate.universe_id, "single:XNAS:QQQ")
        for invalid in ("qqq", "QQQ+DIA", "us_index_etfs_v1"):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(
                ValidationError, "canonical single-asset universe"
            ):
                ExperimentConfig.model_validate(
                    {**candidate.model_dump(mode="python"), "universe_id": invalid}
                )

    def test_experiment_identity_revalidates_unsafe_release_copy(self) -> None:
        candidate = experiment(release())
        unsafe_release = candidate.dataset.model_copy(
            update={"selected_normalized_input_id": "bad"}
        )
        unsafe = candidate.model_copy(update={"dataset": unsafe_release})
        with self.assertRaises(ValidationError):
            _ = unsafe.experiment_id
