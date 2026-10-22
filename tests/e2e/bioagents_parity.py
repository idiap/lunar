# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: Apache-2.0
"""Frozen BioAgents compiler/provider parity expectations; test-only domain data."""

from typing import Any

EXPECTED_CALLS = {
    "drug-repurposing-coherence": 8,
    "her2-arm-proteogenomics": 7,
    "her2-biomarker-triage": 7,
    "liver-metastasis-ecosystem": 7,
    "lmdln-prioritization": 6,
    "melanoma-resistance": 5,
    "pharmaceutical-process-capture": 1,
    "pharmaceutical-process-clone": 1,
    "pharmaceutical-process-deviation": 1,
    "plasma-multiomics": 6,
    "resistance-circuits": 5,
    "serial-ctdna": 5,
    "serial-ctdna-causal": 7,
}


ACCEPTED_TERMINAL = {
    "drug-repurposing-coherence": "BoundedSupport",
    "her2-arm-proteogenomics": "Promotable",
    "her2-biomarker-triage": "Promotable",
    "liver-metastasis-ecosystem": "Promotable",
    "lmdln-prioritization": "Promotable",
    "melanoma-resistance": "Promotable",
    "plasma-multiomics": "Promotable",
    "resistance-circuits": "Promotable",
    "serial-ctdna": "Promotable",
    "serial-ctdna-causal": "Promotable",
}


def _schema_value(schema: dict[str, Any], *, terminal: str | None) -> Any:
    if "anyOf" in schema:
        selected = next(item for item in schema["anyOf"] if item.get("type") != "null")
        return _schema_value(selected, terminal=terminal)
    kind = schema.get("type")
    if kind == "object":
        return {
            name: _schema_value(field, terminal=terminal)
            for name, field in schema.get("properties", {}).items()
        }
    if kind == "array":
        return [_schema_value(schema["items"], terminal=None)]
    if kind == "boolean":
        return True
    if kind == "integer":
        return max(0, int(schema.get("minimum", 0)))
    if kind == "number":
        return 0.5
    return terminal or "schema-valid generated value"


def _record_fields(value: Any) -> Any:
    if isinstance(value, dict):
        if set(value) == {"type_name", "fields"}:
            return _record_fields(value["fields"])
        return {key: _record_fields(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_record_fields(item) for item in value]
    return value


REQUIRED_SOURCE_IDENTIFIERS = {
    "drug-repurposing-coherence": None,
    "her2-arm-proteogenomics": set(),
    "her2-biomarker-triage": set(),
    "liver-metastasis-ecosystem": {"GSE164522"},
    "lmdln-prioritization": set(),
    "melanoma-resistance": {"GSE120575", "GSE91061"},
    "pharmaceutical-process-capture": set(),
    "pharmaceutical-process-clone": set(),
    "pharmaceutical-process-deviation": set(),
    "plasma-multiomics": set(),
    "resistance-circuits": {"GSE111672", "GSE118828"},
    "serial-ctdna": set(),
    "serial-ctdna-causal": set(),
}


REQUIRED_INPUT_KEYS = {
    "drug-repurposing-coherence": {
        "staged_source_packet",
        "prepared_analysis_request",
    },
    "her2-arm-proteogenomics": {"staged_input_catalog", "prepared_analysis_request"},
    "her2-biomarker-triage": {"staged_input_catalog", "prepared_analysis_request"},
    "liver-metastasis-ecosystem": {
        "staged_review",
        "source_registry",
        "review_evidence",
        "review_evidence_table",
        "dataset_table",
        "prepared_analysis_request",
    },
    "lmdln-prioritization": {"staged_input_catalog", "prepared_analysis_request"},
    "melanoma-resistance": {"prepared_analysis_request"},
    "pharmaceutical-process-capture": {
        "trusted_json_envelope",
        "prepared_analysis_request",
    },
    "pharmaceutical-process-clone": {
        "trusted_json_envelope",
        "prepared_analysis_request",
    },
    "pharmaceutical-process-deviation": {
        "trusted_json_envelope",
        "prepared_analysis_request",
    },
    "plasma-multiomics": {"staged_input_catalog", "prepared_analysis_request"},
    "resistance-circuits": {"prepared_analysis_request"},
    "serial-ctdna": {"staged_input_catalog", "prepared_analysis_request"},
    "serial-ctdna-causal": {"staged_input_catalog", "prepared_analysis_request"},
}


# Frozen source conversion models cover private and process workflows absent from the old public bundle.
TOPOLOGY = {
    "drug-repurposing-coherence": [
        [
            "bounded_context",
            "materialization.e0_reasoning_agent",
            ["evidence-tier-grader"],
        ],
        [
            "drug_target_hypothesis",
            "materialization.a0_reasoning_agent",
            ["bounded-mechanism-explanation-ranker"],
        ],
        [
            "evidence_pattern",
            "materialization.i0_reasoning_agent",
            ["calibrated-belief-synthesizer"],
        ],
        [
            "context_transport",
            "materialization.t0_reasoning_agent",
            ["ordinary-transportability"],
        ],
        [
            "cohered_mechanism",
            "materialization.m0_reasoning_agent",
            [
                "biological-theory-framework-selector",
                "drug-combination-mechanism-bridge",
            ],
        ],
        [
            "lineage_contrast",
            "materialization.c0_reasoning_agent",
            ["contextual-contrast-interpreter"],
        ],
        [
            "adjudication_verdict",
            "materialization.r0_reasoning_agent",
            ["counterexample-miner", "defeater-constraint-reasoner"],
        ],
        [
            "claim_status",
            "materialization.e1_reasoning_agent",
            ["evidence-directness-claim-gater", "validation-blocker-gater"],
        ],
    ],
    "her2-arm-proteogenomics": [
        [
            "bounded_scope",
            "materialization.e0_reasoning_agent",
            ["evidence-tier-grader"],
        ],
        [
            "response_pattern",
            "materialization.i0_reasoning_agent",
            ["calibrated-belief-synthesizer"],
        ],
        [
            "mechanism_candidate",
            "materialization.a0_reasoning_agent",
            ["bounded-mechanism-explanation-ranker"],
        ],
        [
            "multilayer_model",
            "materialization.m0_reasoning_agent",
            ["biological-theory-framework-selector", "proteogenomic-layer-critic"],
        ],
        [
            "arm_contrast",
            "materialization.c0_reasoning_agent",
            ["contextual-contrast-interpreter"],
        ],
        [
            "pressure_verdict",
            "materialization.r0_reasoning_agent",
            ["counterexample-miner", "defeater-constraint-reasoner"],
        ],
        [
            "claim_status",
            "materialization.e1_reasoning_agent",
            ["evidence-directness-claim-gater", "validation-blocker-gater"],
        ],
    ],
    "her2-biomarker-triage": [
        [
            "bounded_scope",
            "materialization.e0_reasoning_agent",
            ["evidence-tier-grader"],
        ],
        [
            "response_pattern",
            "materialization.i0_reasoning_agent",
            ["calibrated-belief-synthesizer"],
        ],
        [
            "mechanism_candidate",
            "materialization.a0_reasoning_agent",
            ["bounded-mechanism-explanation-ranker"],
        ],
        [
            "arm_model",
            "materialization.m0_reasoning_agent",
            ["biological-theory-framework-selector", "proteogenomic-layer-critic"],
        ],
        [
            "arm_contrast",
            "materialization.c0_reasoning_agent",
            ["contextual-contrast-interpreter"],
        ],
        [
            "pressure_verdict",
            "materialization.r0_reasoning_agent",
            ["counterexample-miner", "defeater-constraint-reasoner"],
        ],
        [
            "claim_status",
            "materialization.e1_reasoning_agent",
            ["evidence-directness-claim-gater", "validation-blocker-gater"],
        ],
    ],
    "liver-metastasis-ecosystem": [
        [
            "bounded_scope",
            "materialization.e0_reasoning_agent",
            ["evidence-tier-grader"],
        ],
        [
            "ecosystem_candidate",
            "materialization.a0_reasoning_agent",
            ["bounded-mechanism-explanation-ranker"],
        ],
        [
            "cross_source_pattern",
            "materialization.i0_reasoning_agent",
            ["calibrated-belief-synthesizer"],
        ],
        [
            "causal_model",
            "materialization.m0_reasoning_agent",
            ["biological-theory-framework-selector", "coherence-repair-optimizer"],
        ],
        [
            "context_contrast",
            "materialization.c0_reasoning_agent",
            ["contextual-contrast-interpreter"],
        ],
        [
            "review_verdict",
            "materialization.r0_reasoning_agent",
            ["counterexample-miner", "defeater-constraint-reasoner"],
        ],
        [
            "claim_status",
            "materialization.e1_reasoning_agent",
            ["evidence-directness-claim-gater", "validation-blocker-gater"],
        ],
    ],
    "lmdln-prioritization": [
        [
            "bounded_scope",
            "materialization.e0_reasoning_agent",
            ["evidence-tier-grader"],
        ],
        [
            "multiomic_pattern",
            "materialization.i0_reasoning_agent",
            ["calibrated-belief-synthesizer"],
        ],
        [
            "adjusted_model",
            "materialization.m0_reasoning_agent",
            [
                "biological-theory-framework-selector",
                "matched-multiomic-state-vector-integrator",
            ],
        ],
        [
            "mechanism_candidate",
            "materialization.a0_reasoning_agent",
            ["bounded-mechanism-explanation-ranker"],
        ],
        [
            "critic_verdict",
            "materialization.r0_reasoning_agent",
            ["counterexample-miner", "defeater-constraint-reasoner"],
        ],
        [
            "claim_status",
            "materialization.e1_reasoning_agent",
            ["evidence-directness-claim-gater", "validation-blocker-gater"],
        ],
    ],
    "melanoma-resistance": [
        [
            "bounded_scope",
            "materialization.e0_reasoning_agent",
            ["evidence-tier-grader"],
        ],
        [
            "program_pattern",
            "materialization.i0_reasoning_agent",
            ["calibrated-belief-synthesizer"],
        ],
        [
            "ranked_model",
            "materialization.m0_reasoning_agent",
            [
                "biological-theory-framework-selector",
                "target-context-circuit-explainer",
            ],
        ],
        [
            "pressure_verdict",
            "materialization.r0_reasoning_agent",
            ["counterexample-miner", "defeater-constraint-reasoner"],
        ],
        [
            "claim_status",
            "materialization.e1_reasoning_agent",
            ["evidence-directness-claim-gater", "validation-blocker-gater"],
        ],
    ],
    "pharmaceutical-process-capture": [
        [
            "synthesize_pharmaceutical_process",
            "materialization.synthesize_pharmaceutical_process_agent",
            [
                "mab-clone-lead-selector",
                "protein-a-capture-optimizer",
                "pharmaceutical-deviation-root-cause-analyst",
            ],
        ]
    ],
    "pharmaceutical-process-clone": [
        [
            "synthesize_pharmaceutical_process",
            "materialization.synthesize_pharmaceutical_process_agent",
            [
                "mab-clone-lead-selector",
                "protein-a-capture-optimizer",
                "pharmaceutical-deviation-root-cause-analyst",
            ],
        ]
    ],
    "pharmaceutical-process-deviation": [
        [
            "synthesize_pharmaceutical_process",
            "materialization.synthesize_pharmaceutical_process_agent",
            [
                "mab-clone-lead-selector",
                "protein-a-capture-optimizer",
                "pharmaceutical-deviation-root-cause-analyst",
            ],
        ]
    ],
    "plasma-multiomics": [
        [
            "bounded_scope",
            "materialization.e0_reasoning_agent",
            ["plasma-proteomics-source-scout", "lipidomics-metabolomics-source-scout"],
        ],
        [
            "multiomic_pattern",
            "materialization.i0_reasoning_agent",
            ["matched-multiomic-state-vector-integrator"],
        ],
        [
            "adjusted_model",
            "materialization.m0_reasoning_agent",
            ["multiomic-framework-selector"],
        ],
        [
            "mechanism_candidate",
            "materialization.a0_reasoning_agent",
            [
                "bounded-mechanism-explanation-ranker",
                "prior-constrained-mechanism-graph",
            ],
        ],
        [
            "critic_verdict",
            "materialization.r0_reasoning_agent",
            ["proteogenomic-layer-critic", "counterexample-miner"],
        ],
        [
            "claim_status",
            "materialization.e1_reasoning_agent",
            ["evidence-directness-claim-gater", "validation-blocker-gater"],
        ],
    ],
    "resistance-circuits": [
        [
            "bounded_scope",
            "materialization.e0_reasoning_agent",
            ["evidence-tier-grader"],
        ],
        [
            "state_pattern",
            "materialization.i0_reasoning_agent",
            ["calibrated-belief-synthesizer"],
        ],
        [
            "circuit_model",
            "materialization.m0_reasoning_agent",
            [
                "biological-theory-framework-selector",
                "prior-constrained-mechanism-graph",
            ],
        ],
        [
            "pressure_verdict",
            "materialization.r0_reasoning_agent",
            ["counterexample-miner", "defeater-constraint-reasoner"],
        ],
        [
            "claim_status",
            "materialization.e1_reasoning_agent",
            ["evidence-directness-claim-gater", "validation-blocker-gater"],
        ],
    ],
    "serial-ctdna": [
        [
            "bounded_scope",
            "materialization.e0_reasoning_agent",
            ["evidence-tier-grader"],
        ],
        [
            "trajectory_pattern",
            "materialization.i0_reasoning_agent",
            ["calibrated-belief-synthesizer"],
        ],
        [
            "longitudinal_model",
            "materialization.m0_reasoning_agent",
            ["biological-theory-framework-selector", "temporal-discovery-router"],
        ],
        [
            "external_pressure_verdict",
            "materialization.r0_reasoning_agent",
            ["counterexample-miner", "defeater-constraint-reasoner"],
        ],
        [
            "claim_status",
            "materialization.e1_reasoning_agent",
            ["evidence-directness-claim-gater", "validation-blocker-gater"],
        ],
    ],
    "serial-ctdna-causal": [
        [
            "bounded_scope",
            "materialization.e0_reasoning_agent",
            ["evidence-tier-grader"],
        ],
        [
            "trajectory_pattern",
            "materialization.i0_reasoning_agent",
            ["calibrated-belief-synthesizer"],
        ],
        [
            "mechanism_candidate",
            "materialization.a0_reasoning_agent",
            ["bounded-mechanism-explanation-ranker"],
        ],
        [
            "immune_model",
            "materialization.m0_reasoning_agent",
            ["biological-theory-framework-selector", "contextual-causal-graph"],
        ],
        [
            "patient_contrast",
            "materialization.c0_reasoning_agent",
            ["contextual-contrast-interpreter"],
        ],
        [
            "review_verdict",
            "materialization.r0_reasoning_agent",
            ["counterexample-miner", "defeater-constraint-reasoner"],
        ],
        [
            "claim_status",
            "materialization.e1_reasoning_agent",
            ["evidence-directness-claim-gater", "validation-blocker-gater"],
        ],
    ],
}
