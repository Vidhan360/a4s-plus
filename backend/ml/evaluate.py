"""Evaluation metrics computed from actual model predictions.

Every number produced here comes from running the model on a held-out split.
Nothing is estimated, assumed or hard-coded.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ml.features import ELEVATED_CLASSES, RISK_CLASSES


def confusion_matrix(y_true: np.ndarray, y_pred: np.ndarray, n_classes: int) -> np.ndarray:
    cm = np.zeros((n_classes, n_classes), dtype=np.int64)
    for t, p in zip(y_true, y_pred, strict=True):
        cm[int(t), int(p)] += 1
    return cm


def classification_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    y_proba: np.ndarray | None = None,
    classes: tuple[str, ...] = RISK_CLASSES,
) -> dict[str, Any]:
    """Accuracy plus per-class and macro/weighted precision, recall and F1."""
    n = len(classes)
    if y_true.size == 0:
        return {"n_samples": 0, "note": "empty split"}
    cm = confusion_matrix(y_true, y_pred, n)
    support = cm.sum(axis=1)
    predicted = cm.sum(axis=0)
    tp = np.diag(cm).astype(float)

    precision = np.divide(tp, predicted, out=np.zeros(n), where=predicted > 0)
    recall = np.divide(tp, support, out=np.zeros(n), where=support > 0)
    denom = precision + recall
    f1 = np.divide(2 * precision * recall, denom, out=np.zeros(n), where=denom > 0)

    present = support > 0
    total = float(support.sum())
    metrics: dict[str, Any] = {
        "n_samples": int(total),
        "accuracy": round(float(tp.sum() / total), 4),
        "macro_precision": round(float(precision[present].mean()) if present.any() else 0.0, 4),
        "macro_recall": round(float(recall[present].mean()) if present.any() else 0.0, 4),
        "macro_f1": round(float(f1[present].mean()) if present.any() else 0.0, 4),
        "weighted_f1": round(float((f1 * support).sum() / total), 4),
        "per_class": {
            classes[i]: {
                "precision": round(float(precision[i]), 4),
                "recall": round(float(recall[i]), 4),
                "f1": round(float(f1[i]), 4),
                "support": int(support[i]),
            }
            for i in range(n)
        },
        "confusion_matrix": cm.tolist(),
        "confusion_matrix_labels": list(classes),
    }

    # Binary view: elevated (HIGH/CRITICAL) vs not. This is the decision the
    # alerting pipeline actually consumes, so it is reported explicitly.
    true_elev = np.isin(y_true, ELEVATED_CLASSES)
    pred_elev = np.isin(y_pred, ELEVATED_CLASSES)
    tp_e = int((true_elev & pred_elev).sum())
    fp_e = int((~true_elev & pred_elev).sum())
    fn_e = int((true_elev & ~pred_elev).sum())
    tn_e = int((~true_elev & ~pred_elev).sum())
    prec_e = tp_e / (tp_e + fp_e) if (tp_e + fp_e) else 0.0
    rec_e = tp_e / (tp_e + fn_e) if (tp_e + fn_e) else 0.0
    f1_e = 2 * prec_e * rec_e / (prec_e + rec_e) if (prec_e + rec_e) else 0.0
    metrics["elevated_risk_binary"] = {
        "definition": "HIGH or CRITICAL versus LOW or MODERATE",
        "precision": round(prec_e, 4),
        "recall": round(rec_e, 4),
        "f1": round(f1_e, 4),
        "true_positive": tp_e,
        "false_positive": fp_e,
        "false_negative": fn_e,
        "true_negative": tn_e,
    }

    if y_proba is not None and y_proba.size:
        elevated_score = y_proba[:, list(ELEVATED_CLASSES)].sum(axis=1)
        metrics["elevated_risk_binary"]["roc_auc"] = round(
            roc_auc(true_elev.astype(int), elevated_score), 4
        )
        metrics["brier_score_elevated"] = round(
            float(np.mean((elevated_score - true_elev.astype(float)) ** 2)), 4
        )
    return metrics


def roc_auc(y_true: np.ndarray, scores: np.ndarray) -> float:
    """ROC AUC via the rank-sum (Mann-Whitney U) identity, ties averaged."""
    pos = int(y_true.sum())
    neg = int(len(y_true) - pos)
    if pos == 0 or neg == 0:
        return float("nan")
    order = np.argsort(scores, kind="mergesort")
    ranks = np.empty(len(scores), dtype=float)
    sorted_scores = scores[order]
    i = 0
    while i < len(sorted_scores):
        j = i
        while j + 1 < len(sorted_scores) and sorted_scores[j + 1] == sorted_scores[i]:
            j += 1
        average_rank = (i + j) / 2.0 + 1.0
        ranks[order[i : j + 1]] = average_rank
        i = j + 1
    return float((ranks[y_true == 1].sum() - pos * (pos + 1) / 2.0) / (pos * neg))


def format_confusion(cm: list[list[int]], classes: tuple[str, ...] = RISK_CLASSES) -> str:
    width = max(9, max(len(c) for c in classes) + 1)
    header = "true\\pred".ljust(width) + "".join(c[:8].rjust(9) for c in classes)
    lines = [header]
    for i, row in enumerate(cm):
        lines.append(classes[i].ljust(width) + "".join(str(v).rjust(9) for v in row))
    return "\n".join(lines)
