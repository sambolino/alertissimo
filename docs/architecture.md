# 🧠 Alertissimo Architecture

## Overview

**Alertissimo** is a modular orchestration framework for astronomical alert streams. It allows scientists to define filtering, classification, and action logic using natural language, a domain-specific language (DSL), or visual interfaces — all unified into a common intermediate representation (IR). This IR is then translated and executed across multiple broker backends like AMPEL, Fink, and Lasair.

## Flow Summary

The system processes user intent through a layered architecture, transforming human-readable requests into executable logic, and capturing structured broker responses for further reasoning and action.


[ Natural Language ] [ DSL Script ] [ Visual Blocks ]
↓ ↓ ↓
[ NLP Interpreter ] [ DSL Parser ] [ GUI Serializer ]
\ / \ /
→→→→ Canonical Intermediate Representation (IR) ←←←←
|
↓
┌────────────────────────────────────┐
│ 🚦 Orchestrator │
│────────────────────────────────────│
│ ✓ Validate and normalize IR │
│ ✓ Translate IR → broker API │
│ ✓ Translate IR → export format │
│ ↪ to_sql(), to_yaml(), to_csv() │
│ ✓ Choose execution targets │
└────────────────────────────────────┘
↓
┌──────────────────────────────┐
│ Execution Layer │
│ (run on brokers or systems) │
└──────────────────────────────┘
↓ ↓
┌────────────────────────────┐ ┌─────────────────────────┐
│ to_ampel(), to_fink(), ...│ │ Airflow DAG (optional) │
│ (direct or via API) │ │ (handle retries, timing)│
└────────────────────────────┘ └─────────────────────────┘
↓
[ Responses from Brokers (results, metadata) ]
↓
┌──────────────────────────────────────────┐
│ Response Orchestration Layer │
│──────────────────────────────────────────│
│ ✓ Merge/compare broker outputs │
│ ✓ Run optional post-hooks │
│ ✓ Apply scoring/follow-up rules │
│ ✓ Format for user actions │
└──────────────────────────────────────────┘
↓
[ Notify | Store | Display | Trigger | Publish ]

## Key Components

### 🧾 Canonical Intermediate Representation (IR)
- Defined via `pydantic`
- Broker-agnostic format representing the logic of a user's intent
- Translated into broker-specific tasks and configurations

### 🧠 Orchestrator
- Validates and normalizes the IR
- Translates to:
  - Executable workflows (for brokers)
  - Exportable formats (`to_sql`, `to_yaml`, etc.)
- Chooses appropriate execution targets and handles formatting

### 🛰 Execution Layer
- Sends workflows to brokers (e.g. AMPEL, Fink, Lasair)
- Optionally wrapped in **Airflow DAGs** to handle:
  - Task scheduling
  - Retry logic
  - Conditional execution
- Supports both synchronous and async execution models

### 📥 Response Orchestration Layer
- Receives and combines outputs from multiple brokers
- Applies post-processing logic:
  - Aggregation, scoring, classification merging
  - Follow-up triggers (e.g., send email, alert observer)
- Prepares results for user interaction or further automation

### 📤 Exporters
- Translate IR or broker output into static formats:
  - SQL queries for simulation
  - YAML for review or reuse
  - CSVs for tabular export
- Useful for previewing workflows or publishing results

---

## Extensibility

Alertissimo is designed to be broker-agnostic. New brokers can be added by:

- Defining adapter modules (`to_<broker>()`)
- Describing their capabilities in metadata
- Mapping IR stages to the broker’s API or internal language

---

## Optional Airflow Support

Airflow integration is non-mandatory but useful for:
- Production-scale orchestration
- Managing retries, schedules, dependencies
- Running Alertissimo workflows as DAG tasks across brokers

The system can export DAG definitions or run tasks via an Airflow operator when needed.

---

## Summary

Alertissimo acts as the **translator, conductor, and orchestrator** for real-time time-domain astronomy. It transforms heterogeneous broker ecosystems into a coherent, customizable platform for discovery.


