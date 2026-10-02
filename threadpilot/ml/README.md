# ML: order-delay model and feasibility tools (prototype)

Built by the team to estimate the probability that an in-progress order finishes late, plus risk,
discovery, tracing and feasibility helpers. It produces `in_progress_orders_forecast.csv`.

```bash
cd ml
python -m pip install -r requirements.txt
python run_demo.py
```

Status and known issues:

* **Not connected to the backend yet.** Nothing in `backend/` calls this package.
* The workshop features are derived from the product category alone, so they add no information; training
  measures the factory trend at the due date while prediction measures it today; only completed orders are
  used for training; 86 samples with one 22-row test split make the reported AUC noisy. Details and fixes:
  [docs/CODE_REVIEW.md](../docs/CODE_REVIEW.md), section 4.
* `models/delay_model.pkl` is a pickle. Only load pickle files you created yourself.
* `models/feasibility_tools.py` and `tools/feasibility_tools.py` differ; keep one.
