# YottaFlex Workforce Intelligence – User Guide

## 1. Introduction

YottaFlex Workforce Intelligence is a workforce planning application designed to help organizations analyze employee capacity, project demand, workforce utilization, skill coverage, and resource allocation.

The application provides dashboards, forecasting, anomaly detection, and explainable workforce recommendations to support better workforce planning decisions.

## 2. Getting Started

### Prerequisites

- Python installed on your system.
- Project dependencies installed.
- Project files downloaded or cloned.

### Running the Application

1. Open the project folder in VS Code.
2. Open the integrated terminal.
3. Activate the virtual environment:

```bash
.venv\Scripts\Activate.ps1
```

4. Run the application:

```bash
python app.py
```

5. Open your browser and navigate to:

```text
http://127.0.0.1:5000
```

The application dashboard will appear.

## 3. Application Modules

### 3.1 Overview Dashboard

The Overview page provides a summary of the workforce situation.

It displays:

- Planned project demand.
- Available employee capacity.
- Average workforce utilization.
- Open skill gaps.
- Hiring shortfall.
- Project demand visualizations.
- Priority projects.
- Workforce utilization distribution.

Users can understand the overall workforce situation from a single dashboard.

### 3.2 Employees

The Employees section provides information about the workforce.

Users can explore employee information, available capacity, skills, and workforce allocation to understand the organization's available resources.

### 3.3 Projects & Demand

This section provides information about projects and their workforce requirements.

Users can examine project demand, required skills, resource requirements, and project priorities to understand future workforce needs.

### 3.4 Forecast

The Forecast module helps analyze future workforce demand and capacity.

Users can explore forecast results to identify potential differences between future project requirements and available employee capacity.

### 3.5 Utilization

The Utilization module helps analyze how effectively employee capacity is being used.

Users can examine utilization levels and identify potential underutilization or overutilization.

### 3.6 Skill Gaps & Actions

This module identifies differences between the skills required by projects and the skills available in the workforce.

It provides explainable workforce recommendations to help address skill shortages and improve resource planning.

### 3.7 Anomaly Monitor

The Anomaly Monitor helps identify unusual workforce patterns and potential inconsistencies in workforce planning data.

Users can review detected anomalies and investigate potential issues.

## 4. Understanding Workforce Metrics

| Metric | Meaning |
|---|---|
| Planned Demand | Total workforce hours required by projects. |
| Available Capacity | Total working hours available from employees. |
| Utilization | Percentage of available capacity being used. |
| Skill Gaps | Missing skills required to meet project demand. |
| Hiring Shortfall | Estimated additional workforce required. |
| Forecast | Estimated future workforce demand and capacity. |
| Anomaly | An unusual pattern or inconsistency in the data. |

## 5. Recommended Workflow

Follow this workflow to use the application:

1. Start the application.
2. Open the Overview dashboard.
3. Explore employee information.
4. Review projects and workforce demand.
5. Analyze future demand using Forecast.
6. Examine workforce utilization.
7. Identify skill shortages and review recommendations.
8. Monitor unusual patterns through Anomaly Monitor.

## 6. Dataset

The application supports reproducible synthetic workforce data for demonstration and analysis.

The generated data helps demonstrate:

- Employee capacity planning.
- Project demand analysis.
- Workforce utilization.
- Skill coverage analysis.
- Forecasting.
- Anomaly detection.
- Workforce recommendations.

## 7. Expected Outcome

By using YottaFlex Workforce Intelligence, users can:

- Understand workforce availability.
- Identify resource shortages.
- Analyze project demand.
- Monitor employee utilization.
- Detect skill gaps.
- Examine future workforce requirements.
- Make informed workforce planning decisions.

## 8. Conclusion

YottaFlex Workforce Intelligence provides an integrated approach to workforce planning by combining workforce analytics, forecasting, anomaly detection, and explainable recommendations in one application.