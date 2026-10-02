"""
训练 predict_order_delay 用的 Logistic Regression 模型。

为什么用 Logistic Regression 而不是 Random Forest：
    - 训练样本很小（几十到一百多条），Random Forest 容易过拟合
    - Logistic Regression 输出天然就是概率，容易解释
    - coef_ 可以直接看每个特征的方向和权重，方便写进 JSON 给 LLM/人复核
    - 更符合"可审查 / 可追溯"（inspectable）的项目要求

运行方式：
    python -m models.train_delay_model

会在 models/ 目录下产出：
    delay_model.pkl        —— sklearn Pipeline（含预处理 + 模型）
    training_report.json   —— 训练报告（样本量、类别分布、指标、系数）
"""
from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    brier_score_loss,
    classification_report,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from models.feature_engineering import (
    CATEGORICAL_FEATURES,
    NUMERIC_FEATURES,
    build_training_table,
)

MODELS_DIR = Path(__file__).parent
MODEL_PATH = MODELS_DIR / "delay_model.pkl"
REPORT_PATH = MODELS_DIR / "training_report.json"

MIN_SAMPLES_PER_CLASS = 10  # 少于这个数量，不建议训练 ML 模型，应该退回规则法


def build_pipeline() -> Pipeline:
    preprocessor = ColumnTransformer(
        transformers=[
            ("num", StandardScaler(), NUMERIC_FEATURES),
            ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_FEATURES),
        ]
    )
    model = LogisticRegression(max_iter=1000, class_weight="balanced")
    return Pipeline(steps=[("preprocess", preprocessor), ("model", model)])


def get_feature_names(pipeline: Pipeline) -> list[str]:
    preprocessor = pipeline.named_steps["preprocess"]
    return list(preprocessor.get_feature_names_out())


def train() -> dict:
    table = build_training_table()
    class_counts = table["delayed"].value_counts().to_dict()

    # --- 数据量检查：这是文档里第 20 节强调的关键一步 ---
    if len(table) < 30 or min(class_counts.values(), default=0) < MIN_SAMPLES_PER_CLASS:
        report = {
            "trained": False,
            "reason": (
                f"Insufficient samples for a reliable model "
                f"(total={len(table)}, class_counts={class_counts}, "
                f"min required per class={MIN_SAMPLES_PER_CLASS}). "
                "Recommendation: use the rule-based risk score "
                "(get_at_risk_orders) instead of predict_order_delay "
                "until more COMPLETE orders accumulate."
            ),
            "total_samples": len(table),
            "class_counts": class_counts,
        }
        REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False))
        print(report["reason"])
        return report

    X = table[NUMERIC_FEATURES + CATEGORICAL_FEATURES]
    y = table["delayed"]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, random_state=42, stratify=y
    )

    pipeline = build_pipeline()
    pipeline.fit(X_train, y_train)

    y_pred = pipeline.predict(X_test)
    y_proba = pipeline.predict_proba(X_test)[:, 1]

    metrics = {
        "accuracy": round(float(accuracy_score(y_test, y_pred)), 3),
        "roc_auc": round(float(roc_auc_score(y_test, y_proba)), 3) if len(set(y_test)) > 1 else None,
        "brier_score": round(float(brier_score_loss(y_test, y_proba)), 3),
    }
    report_text = classification_report(y_test, y_pred, zero_division=0)

    # 用全量数据 refit 最终上线模型（评估已经在 test set 做过了）
    final_pipeline = build_pipeline()
    final_pipeline.fit(X, y)

    feature_names = get_feature_names(final_pipeline)
    coefs = final_pipeline.named_steps["model"].coef_[0]
    coefficients = {
        name: round(float(coef), 4) for name, coef in zip(feature_names, coefs)
    }

    joblib.dump(final_pipeline, MODEL_PATH)

    report = {
        "trained": True,
        "model_name": "LogisticRegression",
        "model_version": "v1",
        "total_samples": len(table),
        "class_counts": class_counts,
        "train_size": len(X_train),
        "test_size": len(X_test),
        "test_metrics": metrics,
        "classification_report": report_text,
        "feature_coefficients": coefficients,
        "features_used": NUMERIC_FEATURES + CATEGORICAL_FEATURES,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False))

    print(f"Model trained on {len(table)} samples ({class_counts}).")
    print(f"Test metrics: {metrics}")
    print(f"Saved model to {MODEL_PATH}")
    print(f"Saved report to {REPORT_PATH}")

    return report


if __name__ == "__main__":
    train()
