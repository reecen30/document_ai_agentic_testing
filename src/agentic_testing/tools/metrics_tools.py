"""
Metrics tools — compare baseline vs truth and candidate vs truth.
Computes classification accuracy, extraction field metrics, and anomaly detection.
"""
import json
from collections import defaultdict
from typing import Any, Dict, List, Optional, Type
from crewai.tools import BaseTool
from pydantic import BaseModel, Field


def _safe_str(v) -> str:
    """Normalise a value to a stripped lower-case string for comparison."""
    if v is None:
        return ""
    return str(v).strip().lower()


def _f1(tp: int, fp: int, fn: int) -> float:
    """Macro F1 from raw counts."""
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    if precision + recall == 0:
        return 0.0
    return round(2 * precision * recall / (precision + recall), 4)


# ---------------------------------------------------------------------------
# CompareBaselineToTruthTool
# ---------------------------------------------------------------------------

class CompareBaselineToTruthInput(BaseModel):
    case_bundle: Dict[str, Any] = Field(
        ...,
        description="A single case bundle as produced by BuildCaseBundleTool.",
    )


class CompareBaselineToTruthTool(BaseTool):
    name: str = "compare_baseline_to_truth"
    description: str = (
        "Compare baseline predictions to validated truth for a single transaction. "
        "Returns classification_correct, exact_match_rate, missing_field_rate, "
        "and confidence_vs_correctness analysis. Returns JSON."
    )
    args_schema: Type[BaseModel] = CompareBaselineToTruthInput

    def _run(self, case_bundle: Dict[str, Any]) -> str:
        try:
            tid = case_bundle.get("transaction_id")

            # --- Classification ---
            baseline_cls = _safe_str(case_bundle.get("doc_type_baseline"))
            truth_cls = _safe_str(case_bundle.get("doc_type_truth"))
            classification_correct = (baseline_cls == truth_cls) if (baseline_cls and truth_cls) else None

            # --- Extraction ---
            fields_baseline = case_bundle.get("fields_baseline") or []
            fields_truth = case_bundle.get("fields_truth") or []

            truth_map = {_safe_str(f.get("field")): f for f in fields_truth}
            baseline_map = {_safe_str(f.get("field")): f for f in fields_baseline}
            all_fields = set(truth_map.keys()) | set(baseline_map.keys())
            all_fields.discard("")

            matches = 0
            mismatches = 0
            missing_in_baseline = 0
            field_results = []

            for field_key in all_fields:
                b_row = baseline_map.get(field_key)
                t_row = truth_map.get(field_key)
                b_val = _safe_str(b_row.get("value") if b_row else None)
                t_val = _safe_str(t_row.get("value") if t_row else None)
                b_missing = int(b_row.get("is_missing", 0)) if b_row else 0
                t_missing = int(t_row.get("is_missing", 0)) if t_row else 0

                is_match = (b_val == t_val) and not b_missing
                if is_match:
                    matches += 1
                else:
                    mismatches += 1
                if b_missing and not t_missing:
                    missing_in_baseline += 1

                field_results.append({
                    "field": field_key,
                    "baseline_value": b_val,
                    "truth_value": t_val,
                    "match": is_match,
                    "baseline_missing": bool(b_missing),
                    "truth_missing": bool(t_missing),
                })

            total_fields = len(all_fields)
            exact_match_rate = round(matches / total_fields, 4) if total_fields > 0 else None
            missing_field_rate = round(missing_in_baseline / total_fields, 4) if total_fields > 0 else None

            # --- Confidence vs Correctness ---
            conf = case_bundle.get("classification_confidence_baseline")
            try:
                conf_float = float(conf) if conf not in (None, "") else None
            except (TypeError, ValueError):
                conf_float = None

            confidence_vs_correctness = {
                "confidence": conf_float,
                "classification_correct": classification_correct,
                "high_confidence_wrong": (
                    conf_float is not None
                    and conf_float > 0.85
                    and classification_correct is False
                ),
            }

            return json.dumps({
                "transaction_id": tid,
                "classification_correct": classification_correct,
                "doc_type_baseline": baseline_cls,
                "doc_type_truth": truth_cls,
                "exact_match_rate": exact_match_rate,
                "missing_field_rate": missing_field_rate,
                "field_match_count": matches,
                "field_mismatch_count": mismatches,
                "total_fields_evaluated": total_fields,
                "confidence_vs_correctness": confidence_vs_correctness,
                "field_results": field_results,
            })
        except Exception as e:
            return json.dumps({"error": str(e), "tool": "compare_baseline_to_truth"})


# ---------------------------------------------------------------------------
# CompareCandidateToTruthTool
# ---------------------------------------------------------------------------

class CompareCandidateToTruthInput(BaseModel):
    case_bundle: Dict[str, Any] = Field(
        ...,
        description="A single case bundle as produced by BuildCaseBundleTool.",
    )


class CompareCandidateToTruthTool(BaseTool):
    name: str = "compare_candidate_to_truth"
    description: str = (
        "Compare candidate predictions to validated truth for a single transaction. "
        "Returns classification_correct, exact_match_rate, missing_field_rate, "
        "and confidence_vs_correctness analysis. Returns JSON."
    )
    args_schema: Type[BaseModel] = CompareCandidateToTruthInput

    def _run(self, case_bundle: Dict[str, Any]) -> str:
        try:
            tid = case_bundle.get("transaction_id")

            # --- Classification ---
            candidate_cls = _safe_str(case_bundle.get("doc_type_candidate"))
            truth_cls = _safe_str(case_bundle.get("doc_type_truth"))
            classification_correct = (candidate_cls == truth_cls) if (candidate_cls and truth_cls) else None

            # --- Extraction ---
            fields_candidate = case_bundle.get("fields_candidate") or []
            fields_truth = case_bundle.get("fields_truth") or []

            truth_map = {_safe_str(f.get("field")): f for f in fields_truth}
            candidate_map = {_safe_str(f.get("field")): f for f in fields_candidate}
            all_fields = set(truth_map.keys()) | set(candidate_map.keys())
            all_fields.discard("")

            matches = 0
            mismatches = 0
            missing_in_candidate = 0
            field_results = []

            for field_key in all_fields:
                c_row = candidate_map.get(field_key)
                t_row = truth_map.get(field_key)
                c_val = _safe_str(c_row.get("value") if c_row else None)
                t_val = _safe_str(t_row.get("value") if t_row else None)
                c_missing = int(c_row.get("is_missing", 0)) if c_row else 0
                t_missing = int(t_row.get("is_missing", 0)) if t_row else 0

                is_match = (c_val == t_val) and not c_missing
                if is_match:
                    matches += 1
                else:
                    mismatches += 1
                if c_missing and not t_missing:
                    missing_in_candidate += 1

                field_results.append({
                    "field": field_key,
                    "candidate_value": c_val,
                    "truth_value": t_val,
                    "match": is_match,
                    "candidate_missing": bool(c_missing),
                    "truth_missing": bool(t_missing),
                })

            total_fields = len(all_fields)
            exact_match_rate = round(matches / total_fields, 4) if total_fields > 0 else None
            missing_field_rate = round(missing_in_candidate / total_fields, 4) if total_fields > 0 else None

            # --- Confidence vs Correctness ---
            conf = case_bundle.get("classification_confidence_candidate")
            try:
                conf_float = float(conf) if conf not in (None, "") else None
            except (TypeError, ValueError):
                conf_float = None

            confidence_vs_correctness = {
                "confidence": conf_float,
                "classification_correct": classification_correct,
                "high_confidence_wrong": (
                    conf_float is not None
                    and conf_float > 0.85
                    and classification_correct is False
                ),
            }

            return json.dumps({
                "transaction_id": tid,
                "classification_correct": classification_correct,
                "doc_type_candidate": candidate_cls,
                "doc_type_truth": truth_cls,
                "exact_match_rate": exact_match_rate,
                "missing_field_rate": missing_field_rate,
                "field_match_count": matches,
                "field_mismatch_count": mismatches,
                "total_fields_evaluated": total_fields,
                "confidence_vs_correctness": confidence_vs_correctness,
                "field_results": field_results,
            })
        except Exception as e:
            return json.dumps({"error": str(e), "tool": "compare_candidate_to_truth"})


# ---------------------------------------------------------------------------
# CalculateDocTypeMetricsTool
# ---------------------------------------------------------------------------

class CalculateDocTypeMetricsInput(BaseModel):
    case_bundles: List[Dict[str, Any]] = Field(
        ...,
        description="List of case bundles as produced by BuildCaseBundleTool.",
    )


class CalculateDocTypeMetricsTool(BaseTool):
    name: str = "calculate_doc_type_metrics"
    description: str = (
        "Aggregate classification metrics by document type across all case bundles. "
        "Computes baseline_accuracy, candidate_accuracy, baseline_f1, candidate_f1, "
        "and delta (candidate - baseline) per document type. Returns JSON."
    )
    args_schema: Type[BaseModel] = CalculateDocTypeMetricsInput

    def _run(self, case_bundles: List[Dict[str, Any]]) -> str:
        try:
            # Counters: {doc_type: {tp_b, fp_b, fn_b, tp_c, fp_c, fn_c, total}}
            stats: Dict[str, Dict[str, int]] = defaultdict(
                lambda: {"tp_b": 0, "fp_b": 0, "fn_b": 0, "tp_c": 0, "fp_c": 0, "fn_c": 0, "total": 0}
            )

            for bundle in case_bundles:
                truth = _safe_str(bundle.get("doc_type_truth"))
                baseline = _safe_str(bundle.get("doc_type_baseline"))
                candidate = _safe_str(bundle.get("doc_type_candidate"))

                if not truth:
                    continue

                s = stats[truth]
                s["total"] += 1

                # Baseline classification counts
                if baseline == truth:
                    s["tp_b"] += 1
                else:
                    s["fn_b"] += 1
                    if baseline:
                        stats[baseline]["fp_b"] += 1

                # Candidate classification counts
                if candidate == truth:
                    s["tp_c"] += 1
                else:
                    s["fn_c"] += 1
                    if candidate:
                        stats[candidate]["fp_c"] += 1

            results = []
            for doc_type, s in sorted(stats.items()):
                b_acc = round(s["tp_b"] / s["total"], 4) if s["total"] > 0 else None
                c_acc = round(s["tp_c"] / s["total"], 4) if s["total"] > 0 else None
                b_f1 = _f1(s["tp_b"], s["fp_b"], s["fn_b"])
                c_f1 = _f1(s["tp_c"], s["fp_c"], s["fn_c"])
                delta_acc = round(c_acc - b_acc, 4) if (c_acc is not None and b_acc is not None) else None
                delta_f1 = round(c_f1 - b_f1, 4)
                results.append({
                    "doc_type": doc_type,
                    "total_transactions": s["total"],
                    "baseline_accuracy": b_acc,
                    "candidate_accuracy": c_acc,
                    "baseline_f1": b_f1,
                    "candidate_f1": c_f1,
                    "delta_accuracy": delta_acc,
                    "delta_f1": delta_f1,
                    "direction": (
                        "IMPROVEMENT" if (delta_f1 or 0) > 0
                        else "REGRESSION" if (delta_f1 or 0) < 0
                        else "NEUTRAL"
                    ),
                })

            return json.dumps({"doc_type_metrics": results, "total_doc_types": len(results)})
        except Exception as e:
            return json.dumps({"error": str(e), "tool": "calculate_doc_type_metrics"})


# ---------------------------------------------------------------------------
# CalculateFieldMetricsTool
# ---------------------------------------------------------------------------

class CalculateFieldMetricsInput(BaseModel):
    case_bundles: List[Dict[str, Any]] = Field(
        ...,
        description="List of case bundles as produced by BuildCaseBundleTool.",
    )


class CalculateFieldMetricsTool(BaseTool):
    name: str = "calculate_field_metrics"
    description: str = (
        "Compute per-field extraction metrics across all case bundles. "
        "Returns baseline_match_rate, candidate_match_rate, baseline_missing_rate, "
        "candidate_missing_rate, and delta for each field. Returns JSON."
    )
    args_schema: Type[BaseModel] = CalculateFieldMetricsInput

    def _run(self, case_bundles: List[Dict[str, Any]]) -> str:
        try:
            # {field: {b_match, b_miss, c_match, c_miss, total}}
            field_stats: Dict[str, Dict[str, int]] = defaultdict(
                lambda: {"b_match": 0, "b_miss": 0, "c_match": 0, "c_miss": 0, "total": 0}
            )

            for bundle in case_bundles:
                fields_truth = {_safe_str(f.get("field")): f for f in (bundle.get("fields_truth") or [])}
                fields_baseline = {_safe_str(f.get("field")): f for f in (bundle.get("fields_baseline") or [])}
                fields_candidate = {_safe_str(f.get("field")): f for f in (bundle.get("fields_candidate") or [])}

                all_fields = set(fields_truth.keys()) | set(fields_baseline.keys()) | set(fields_candidate.keys())
                all_fields.discard("")

                for field_key in all_fields:
                    s = field_stats[field_key]
                    s["total"] += 1

                    t_row = fields_truth.get(field_key)
                    b_row = fields_baseline.get(field_key)
                    c_row = fields_candidate.get(field_key)

                    t_val = _safe_str(t_row.get("value") if t_row else None)
                    b_val = _safe_str(b_row.get("value") if b_row else None)
                    c_val = _safe_str(c_row.get("value") if c_row else None)

                    b_missing = int(b_row.get("is_missing", 0)) if b_row else 1
                    c_missing = int(c_row.get("is_missing", 0)) if c_row else 1
                    t_missing = int(t_row.get("is_missing", 0)) if t_row else 0

                    if not b_missing and b_val == t_val:
                        s["b_match"] += 1
                    if b_missing and not t_missing:
                        s["b_miss"] += 1

                    if not c_missing and c_val == t_val:
                        s["c_match"] += 1
                    if c_missing and not t_missing:
                        s["c_miss"] += 1

            results = []
            for field_key, s in sorted(field_stats.items()):
                total = s["total"]
                b_match_rate = round(s["b_match"] / total, 4) if total > 0 else None
                c_match_rate = round(s["c_match"] / total, 4) if total > 0 else None
                b_miss_rate = round(s["b_miss"] / total, 4) if total > 0 else None
                c_miss_rate = round(s["c_miss"] / total, 4) if total > 0 else None
                delta_match = (
                    round(c_match_rate - b_match_rate, 4)
                    if (c_match_rate is not None and b_match_rate is not None)
                    else None
                )
                delta_miss = (
                    round(c_miss_rate - b_miss_rate, 4)
                    if (c_miss_rate is not None and b_miss_rate is not None)
                    else None
                )
                results.append({
                    "field": field_key,
                    "total_evaluated": total,
                    "baseline_match_rate": b_match_rate,
                    "candidate_match_rate": c_match_rate,
                    "baseline_missing_rate": b_miss_rate,
                    "candidate_missing_rate": c_miss_rate,
                    "delta_match_rate": delta_match,
                    "delta_missing_rate": delta_miss,
                    "direction": (
                        "IMPROVEMENT" if (delta_match or 0) > 0
                        else "REGRESSION" if (delta_match or 0) < 0
                        else "NEUTRAL"
                    ),
                })

            return json.dumps({"field_metrics": results, "total_fields": len(results)})
        except Exception as e:
            return json.dumps({"error": str(e), "tool": "calculate_field_metrics"})


# ---------------------------------------------------------------------------
# DetectMissingFieldSpikesTool
# ---------------------------------------------------------------------------

class DetectMissingFieldSpikesInput(BaseModel):
    field_metrics: List[Dict[str, Any]] = Field(
        ...,
        description="List of per-field metric dicts as returned by CalculateFieldMetricsTool.",
    )
    spike_threshold: float = Field(
        default=0.05,
        description="Minimum increase in missing rate (absolute) to flag as a spike.",
    )


class DetectMissingFieldSpikesTool(BaseTool):
    name: str = "detect_missing_field_spikes"
    description: str = (
        "Find fields where the missing rate increased between baseline and candidate "
        "by more than spike_threshold. Returns a list of flagged fields with details. "
        "Returns JSON."
    )
    args_schema: Type[BaseModel] = DetectMissingFieldSpikesInput

    def _run(self, field_metrics: List[Dict[str, Any]], spike_threshold: float = 0.05) -> str:
        try:
            spikes = []
            for fm in field_metrics:
                b_miss = fm.get("baseline_missing_rate")
                c_miss = fm.get("candidate_missing_rate")
                if b_miss is None or c_miss is None:
                    continue
                delta = c_miss - b_miss
                if delta >= spike_threshold:
                    spikes.append({
                        "field": fm.get("field"),
                        "baseline_missing_rate": b_miss,
                        "candidate_missing_rate": c_miss,
                        "delta_missing_rate": round(delta, 4),
                        "severity": "HIGH" if delta >= 0.2 else "MEDIUM" if delta >= 0.1 else "LOW",
                    })

            spikes.sort(key=lambda x: x["delta_missing_rate"], reverse=True)
            return json.dumps({
                "missing_field_spikes": spikes,
                "spike_count": len(spikes),
                "spike_threshold_used": spike_threshold,
            })
        except Exception as e:
            return json.dumps({"error": str(e), "tool": "detect_missing_field_spikes"})


# ---------------------------------------------------------------------------
# DetectConfidenceMismatchTool
# ---------------------------------------------------------------------------

class DetectConfidenceMismatchInput(BaseModel):
    case_bundles: List[Dict[str, Any]] = Field(
        ...,
        description="List of case bundles as produced by BuildCaseBundleTool.",
    )
    confidence_threshold: float = Field(
        default=0.85,
        description="Confidence level above which a wrong prediction is flagged.",
    )
    mode: str = Field(
        default="candidate",
        description="Which predictions to check: 'baseline' or 'candidate'.",
    )


class DetectConfidenceMismatchTool(BaseTool):
    name: str = "detect_confidence_mismatch"
    description: str = (
        "Find transactions where the model has high confidence (above threshold) "
        "but the classification prediction is wrong. Supports 'baseline' or 'candidate' mode. "
        "Returns JSON with flagged transactions and summary statistics."
    )
    args_schema: Type[BaseModel] = DetectConfidenceMismatchInput

    def _run(
        self,
        case_bundles: List[Dict[str, Any]],
        confidence_threshold: float = 0.85,
        mode: str = "candidate",
    ) -> str:
        try:
            flagged = []
            checked = 0

            for bundle in case_bundles:
                truth = _safe_str(bundle.get("doc_type_truth"))
                if not truth:
                    continue

                if mode == "candidate":
                    prediction = _safe_str(bundle.get("doc_type_candidate"))
                    conf_raw = bundle.get("classification_confidence_candidate")
                else:
                    prediction = _safe_str(bundle.get("doc_type_baseline"))
                    conf_raw = bundle.get("classification_confidence_baseline")

                try:
                    conf = float(conf_raw) if conf_raw not in (None, "") else None
                except (TypeError, ValueError):
                    conf = None

                if conf is None or prediction == "":
                    continue

                checked += 1
                is_correct = prediction == truth
                if conf >= confidence_threshold and not is_correct:
                    flagged.append({
                        "transaction_id": bundle.get("transaction_id"),
                        "mode": mode,
                        "confidence": conf,
                        "predicted_doc_type": prediction,
                        "truth_doc_type": truth,
                        "confidence_threshold": confidence_threshold,
                    })

            flagged.sort(key=lambda x: x["confidence"], reverse=True)
            return json.dumps({
                "confidence_mismatch_transactions": flagged,
                "flagged_count": len(flagged),
                "transactions_checked": checked,
                "mode": mode,
                "confidence_threshold": confidence_threshold,
                "mismatch_rate": round(len(flagged) / checked, 4) if checked > 0 else None,
            })
        except Exception as e:
            return json.dumps({"error": str(e), "tool": "detect_confidence_mismatch"})


# ---------------------------------------------------------------------------
# Convenience instances
# ---------------------------------------------------------------------------
compare_baseline_to_truth = CompareBaselineToTruthTool()
compare_candidate_to_truth = CompareCandidateToTruthTool()
calculate_doc_type_metrics = CalculateDocTypeMetricsTool()
calculate_field_metrics = CalculateFieldMetricsTool()
detect_missing_field_spikes = DetectMissingFieldSpikesTool()
detect_confidence_mismatch = DetectConfidenceMismatchTool()
