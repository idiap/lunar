# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0

"""Quality criteria must not promote facts from a candidate artifact.

This module protects expected behavior for the corresponding workflow, script, or repository surface. Key concepts: regression coverage, interface stability, and output integrity.
"""

from catalog.workflows.public.dependencies.planner.staged_routing import (
    quality_review_promotes_untrusted_candidate,
)
from scripts.evaluation.run_melanoma_sequential_quality_benchmark import (
    redacted_quality_review_evidence,
)


def test_fabricated_current_endpoint_is_rejected_as_positive_evidence() -> None:
    """Verify fabricated current endpoint is rejected as positive evidence."""
    current = {"endpoint": {"overall_survival": "median 12.4 months"}}
    released = {"endpoint": {"overall_survival": "unavailable"}}
    reviewed = {"positive_example": "Overall survival: median 12.4 months."}
    assert quality_review_promotes_untrusted_candidate(reviewed, current, released) == [
        "/endpoint/overall_survival"
    ]


def test_changed_candidate_may_appear_in_negative_but_not_positive_example() -> None:
    """Verify changed candidate may appear in negative but not positive example."""
    current = {"endpoint": {"overall_survival": "median 12.4 months"}}
    released = {"endpoint": {"overall_survival": "unavailable"}}
    reviewed = {
        "positive_example": "Overall survival: unavailable unless an authorized source is supplied.",
        "negative_example": "Overall survival: median 12.4 months.",
    }
    assert (
        quality_review_promotes_untrusted_candidate(reviewed, current, released) == []
    )


def test_negated_candidate_status_in_positive_example_is_not_promotion() -> None:
    """Verify negated candidate status in positive example is not promotion."""
    current = {"join": {"status": "performed"}}
    released = {"join": {"status": "blocked pending same-lesion keys and access"}}
    reviewed = {
        "positive_example": "The readiness panel states that the patient-level join has not been performed."
    }
    assert (
        quality_review_promotes_untrusted_candidate(reviewed, current, released) == []
    )


def test_affirmative_candidate_status_in_positive_example_is_promotion() -> None:
    """Verify affirmative candidate status in positive example is promotion."""
    current = {"join": {"status": "performed"}}
    released = {"join": {"status": "blocked pending same-lesion keys and access"}}
    reviewed = {
        "positive_example": "The readiness panel states that the patient-level join was performed."
    }
    assert quality_review_promotes_untrusted_candidate(reviewed, current, released) == [
        "/join/status"
    ]


def test_quality_review_packet_redacts_fabricated_os_candidate_value() -> None:
    """Verify quality review packet redacts fabricated os candidate value."""
    evidence = redacted_quality_review_evidence(
        {"endpoint": {"overall_survival": "median 12.4 months"}},
        {"endpoint": {"overall_survival": "unavailable"}},
    )
    serialized = str(evidence)
    assert "median 12.4 months" not in serialized
    assert evidence["authoritative_fact_allowlist"] == [
        {
            "path": "/endpoint/overall_survival",
            "authorized_value": "unavailable",
            "authority": "last_released_evidence_state",
        }
    ]


def test_quality_review_packet_redacts_performed_join_candidate_value() -> None:
    """Verify quality review packet redacts performed join candidate value."""
    evidence = redacted_quality_review_evidence(
        {"join": {"status": "performed"}},
        {"join": {"status": "blocked pending same-lesion keys and access"}},
    )
    serialized = str(evidence)
    assert "'performed'" not in serialized
    assert evidence["authoritative_fact_allowlist"] == [
        {
            "path": "/join/status",
            "authorized_value": "blocked pending same-lesion keys and access",
            "authority": "last_released_evidence_state",
        }
    ]
