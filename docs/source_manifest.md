# Source manifest

- Workforce records: generated locally by `generator/generate_data.py`.
- Generator: Python `random.Random` and Faker, fixed default seed `20261022`.
- External workforce data: none.
- Personal or confidential data: none; names and organizations are synthetic.
- Demand: synthetic weekly planned demand; no observed production actuals were provided.
- Anomaly truth: separate `AnomalyGroundTruth` data exported under `ground_truth/`; detector and forecasting features do not read these labels.
- Source code: project-owned implementation in this repository; dependencies are declared in `requirements.txt`.
