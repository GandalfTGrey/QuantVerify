from __future__ import annotations

import decimal
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from quantverify.application import (
    ConsumedSessionRange,
    DailyTrendParameters,
    FixtureMetricPolicy,
    FixtureRunSpec,
    ReferenceExecutionSpec,
)
from quantverify.core.enums import BarFrequency
from quantverify.core.models import (
    CostModel,
    ExecutionAssumptions,
    ExperimentConfig,
    RuntimeContext,
    TimeRange,
)
from quantverify.fixtures import BUILTIN_FIXTURE_ID, FixtureRegistry
from quantverify.implementation_registry import builtin_implementation_registry
from quantverify.metrics import (
    AnnualizationPolicy,
    ReturnBasis,
    RiskFreePolicy,
    RiskFreeRateKind,
)
from quantverify.replay import (
    Binary64ValueV1,
    FixtureReplayIntegrityError,
    FixtureRunEvidenceV2,
    FixtureRunSpecEvidenceProjectionV1,
    build_fixture_run_evidence_v2,
    canonical_fixture_run_evidence_v2_bytes,
    load_fixture_run_evidence_v2,
    replay_fixture_run_evidence_v2,
)


def fixture_spec() -> FixtureRunSpec:
    loaded = FixtureRegistry.builtin().resolve(BUILTIN_FIXTURE_ID)
    registry = builtin_implementation_registry()
    schedule = loaded.schedule
    experiment = ExperimentConfig(
        strategy=registry.strategy_version(),
        universe_id="QQQ",
        dataset=loaded.snapshot,
        period=TimeRange(
            start=datetime(2026, 1, 2, tzinfo=UTC),
            end=datetime(2026, 1, 15, tzinfo=UTC),
        ),
        frequency=BarFrequency.DAY,
        parameters={"window": 3},
        benchmark_id="QQQ:buy_hold",
        cost_model=CostModel(
            commission_bps=Decimal("2.5"),
            slippage_bps=Decimal("3"),
        ),
        execution=ExecutionAssumptions(),
        engine=registry.engine_version(),
        base_currency="USD",
        random_seed=0,
    )
    return FixtureRunSpec(
        fixture_id=BUILTIN_FIXTURE_ID,
        experiment=experiment,
        strategy_parameters=DailyTrendParameters(window=3),
        consumed_sessions=ConsumedSessionRange(
            start_session=schedule.sessions[0].session,
            end_session=schedule.sessions[-1].session,
            session_count=len(schedule.sessions),
            schedule_id=schedule.schedule_id,
            schedule_content_hash=schedule.content_hash,
        ),
        execution=ReferenceExecutionSpec(initial_cash=Decimal("10000")),
        metrics=FixtureMetricPolicy(
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
        ),
    )


def runtime() -> RuntimeContext:
    return RuntimeContext(
        source_commit="0a9552caff08153279f3b43f334d35e85116d2b8",
        environment_lock_hash="0" * 64,
        worker_id="core06b2-v1",
    )


def evidence() -> FixtureRunEvidenceV2:
    fixture = FixtureRegistry.builtin().resolve(BUILTIN_FIXTURE_ID)
    return build_fixture_run_evidence_v2(
        spec=fixture_spec(),
        runtime=runtime(),
        fixture_manifest=fixture.manifest,
    ).evidence


def test_projection_is_lossless_and_binary64_exact() -> None:
    spec = fixture_spec()
    projected = FixtureRunSpecEvidenceProjectionV1.from_domain(spec)
    rebuilt = projected.to_domain()

    assert projected.experiment.validation.train_fraction.bits == "3fe3333333333333"
    assert projected.experiment.validation.validation_fraction.bits == "3fc999999999999a"
    assert projected.experiment.validation.test_fraction.bits == "3fc999999999999a"
    assert rebuilt == spec
    assert rebuilt.experiment.experiment_id == spec.experiment.experiment_id
    assert rebuilt.fixture_run_spec_id == spec.fixture_run_spec_id
    with pytest.raises(ValueError):
        Binary64ValueV1(bits="8000000000000000").to_float()

    ulp = projected.model_copy(
        update={
            "experiment": projected.experiment.model_copy(
                update={
                    "validation": projected.experiment.validation.model_copy(
                        update={
                            "train_fraction": Binary64ValueV1(
                                bits="3fe3333333333334"
                            )
                        }
                    )
                }
            )
        }
    )
    assert ulp.to_domain().experiment.experiment_id != spec.experiment.experiment_id


def test_complete_fixture_replay_matches_exact_oracle_and_round_trips() -> None:
    result = evidence()
    assert result.experiment_id == "exp_79aa06bf2846fb63c06e2d71"
    assert result.fixture_run_spec_id == "fixture-run-spec_190420a246f89755b42f0768"
    assert result.run_id == "run_77415976380c3273e13ced77"
    assert result.targets_content_hash == (
        "e535495c8ff557eb2d1bc9e11b802d903ca5d5567423a99eee524b72fd9261f0"
    )
    assert result.metric_input_content_hash == (
        "f9bde3d661584f041d6a2face71514a4246a52a20271d0fff8f6605292e98e8c"
    )
    expected_set_hash = {
        "2.5.1": "21621da53ee981fbd028c0879938e58a56c0b61290858a2f54910e81ad07c889",
        "4.0.0": "cd99e98d9ce5e7fc97077ef94f634e66f29b0dfb28b26804e53eb577b2be707c",
    }
    expected_evidence_hash = {
        "2.5.1": "3636ab5adec96e2ca26005bf274945e54368daee5764096a6989147cadc76be6",
        "4.0.0": "361dcf5c9059c0aa2f563e14d8443b7df9aa2ca9c5f0d62dd953a848c31214fc",
    }
    assert result.metric_set_content_hash == expected_set_hash[decimal.__libmpdec_version__]
    assert result.evidence_content_hash == expected_evidence_hash[decimal.__libmpdec_version__]
    assert tuple(str(point.equity) for point in result.reference_result.points) == (
        "10000",
        "10000",
        "10000",
        "10091.53627682330312056508138",
        "10188.57027948506565057051485",
        "9606.366263514490470537914002",
        "9504.102841309178504119783203",
        "9504.102841309178504119783203",
        "9592.926040649142471669924748",
    )
    document = canonical_fixture_run_evidence_v2_bytes(result)
    expected_golden_file = (
        Path(__file__).parent
        / f"fixture_run_evidence_{decimal.__libmpdec_version__.replace('.', '_')}_golden.json"
    )
    expected_golden = expected_golden_file.read_bytes()
    if expected_golden.endswith(b"\n"):
        pytest.fail("fixture evidence golden must not contain a trailing newline")
    assert document == expected_golden
    loaded = load_fixture_run_evidence_v2(document)
    assert loaded == result
    assert canonical_fixture_run_evidence_v2_bytes(loaded) == document
    assert replay_fixture_run_evidence_v2(loaded, runtime=runtime()).evidence == result


@pytest.mark.parametrize("field", ["run_id", "targets", "reference_result", "metric_set"])
def test_self_consistent_or_detached_tampering_cannot_pass_replay(field: str) -> None:
    original = evidence()
    if field == "run_id":
        forged = original.model_copy(update={"run_id": "run_" + "f" * 24})
    elif field == "targets":
        forged = original.model_copy(update={"targets": original.targets[:-1]})
    elif field == "reference_result":
        forged = original.model_copy(
            update={
                "reference_result": original.reference_result.model_copy(
                    update={"total_commission": Decimal("999")}
                )
            }
        )
    else:
        forged = original.model_copy(
            update={
                "metric_set": original.metric_set.model_copy(
                    update={
                        "metric_input_content_hash": "f" * 64,
                    }
                )
            }
        )
    with pytest.raises(FixtureReplayIntegrityError, match="integrity validation"):
        replay_fixture_run_evidence_v2(forged, runtime=runtime())


def test_registry_and_nested_manifest_unsafe_copies_fail_closed() -> None:
    original = evidence()
    bad_strategy = original.strategy.model_copy(update={"code_hash": "f" * 64})
    bad_manifest = original.fixture_manifest.model_copy(
        update={
            "bundle": original.fixture_manifest.bundle.model_copy(
                update={
                    "schedule": original.fixture_manifest.bundle.schedule.model_copy(
                        update={"content_hash": "f" * 64}
                    )
                }
            )
        }
    )
    for forged in (
        original.model_copy(update={"strategy": bad_strategy}),
        original.model_copy(update={"fixture_manifest": bad_manifest}),
    ):
        with pytest.raises(FixtureReplayIntegrityError, match="integrity validation"):
            replay_fixture_run_evidence_v2(forged, runtime=runtime())


def test_runtime_and_full_bundle_contract_fail_closed() -> None:
    original = evidence()
    other_runtime = runtime().model_copy(update={"worker_id": "other"})
    with pytest.raises(FixtureReplayIntegrityError, match="integrity validation"):
        replay_fixture_run_evidence_v2(original, runtime=other_runtime)

    spec = fixture_spec().model_copy(
        update={
            "consumed_sessions": fixture_spec().consumed_sessions.model_copy(
                update={"session_count": 8}
            )
        }
    )
    fixture = FixtureRegistry.builtin().resolve(BUILTIN_FIXTURE_ID)
    with pytest.raises(FixtureReplayIntegrityError, match="integrity validation"):
        build_fixture_run_evidence_v2(
            spec=spec,
            runtime=runtime(),
            fixture_manifest=fixture.manifest,
        )


def test_noncanonical_or_hostile_documents_are_fixed_typed_failures() -> None:
    document = canonical_fixture_run_evidence_v2_bytes(evidence())
    cases = (
        document + b"\n",
        document.replace(b'"schema_version":', b'"schema_version":"x","schema_version":', 1),
        (b"[" * 33) + b"0" + (b"]" * 33),
    )
    for case in cases:
        with pytest.raises(
            FixtureReplayIntegrityError,
            match=r"^fixture evidence canonical document failed integrity validation$",
        ) as captured:
            load_fixture_run_evidence_v2(case)
        assert captured.value.__cause__ is None
        assert captured.value.__context__ is None


def test_public_build_and_replay_errors_do_not_expose_nested_input() -> None:
    bad = fixture_spec().model_copy(
        update={
            "fixture_id": "SUPERSECRET",
        }
    )
    fixture = FixtureRegistry.builtin().resolve(BUILTIN_FIXTURE_ID)
    with pytest.raises(
        FixtureReplayIntegrityError,
        match=r"^fixture evidence build failed integrity validation$",
    ) as captured:
        build_fixture_run_evidence_v2(
            spec=bad,
            runtime=runtime(),
            fixture_manifest=fixture.manifest,
        )
    error = captured.value
    assert "SUPERSECRET" not in str(error)
    assert error.__cause__ is None
    assert error.__context__ is None
