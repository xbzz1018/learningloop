# LearningLoop Resume Metrics V1

Generated from the frozen `learningloop-resume-metrics-v1` suite using the local Provider profile.

## Results

- Routing cases: 10
- Flash / Pro cases: 8 / 2
- Flash call share: 80.00%
- Progressive Skill loading input-token reduction: 74.28% (`762 -> 196`)
- Bounded-history input-token reduction: 57.82% (`2034 -> 858`)
- Structured-summary input-token reduction: 95.34% (`1245 -> 58`)
- Mixed-route local price-table estimate: `$0.00369006`
- Counterfactual Pro-only local price-table estimate: `$0.00551298`
- Estimated routing cost reduction: 33.07%

## Measurement Boundary

- Input-token reductions use provider-reported token usage for fixed prompt pairs.
- Routing cases verify deterministic policy selection and valid JSON completion, not answer quality.
- Pro-only cost is a counterfactual estimate using the same observed token counts repriced with the versioned local Pro rates.
- These values are not the provider's actual bill and are not production-load metrics.
- Full machine-readable results and the frozen benchmark SHA-256 are in `resume-metrics-v1.json`.
