# Retikon Developer Console UI Guide

Status: Draft
Owner: Product + Eng
Date: 2026-01-26

This guide describes every feature in the proposed Retikon developer console,
what it does, how it interacts with other parts of the UI, and layman-friendly
explanations so a designer can create a modern, friendly front-end.

## 1) Purpose and Audience
The console is the primary UI for developers and operators to:
- Connect data sources and devices.
- Monitor ingest and processing.
- Search, explore, and export results.
- Manage billing, access, and policy.

Layman summary: "This is the control panel for your data. You can connect
sources, see what is happening, search results, and manage who can access it."

## 2) Global Layout and Navigation

### Global Shell
- Left navigation: primary modules (Dashboard, Data Explorer, Graph Explorer,
  Ingestion, Streams & Devices, Pipelines, Data Factory, Workflows, Alerts,
  Billing, Admin).
- Top bar: global search, project switcher, environment switcher, status pill,
  user menu.

Layman summary: "A simple menu on the left, search and project switching on
 the top, and everything else in the main area."

### Primary Navigation Structure
- Dashboard
- Data Explorer
- Graph Explorer
- Ingestion
- Streams & Devices
- Pipelines
- Data Factory
- Workflows
- Alerts
- Billing
- Admin / Settings

## 3) Dashboard

Purpose:
- One-screen summary of system health, ingest volume, and alerts.

Key UI elements:
- System health tiles (green/yellow/red).
- Ingest rate chart by modality.
- Backlog queue size.
- Recent alerts and failures.

Interactions:
- Clicking a tile opens the relevant module (e.g., backlog opens Ingestion).

Layman summary: "The home screen showing if everything is healthy and how much
 data is flowing." 

## 4) Data Explorer (Search & Results)

Purpose:
- Search across text, images, audio, and metadata.

Key UI elements:
- Query bar with text and optional image/audio input.
- Filters (time range, device, tags, confidence).
- Results grid with thumbnails and timestamps.
- Result detail panel with transcript/snippets.

Interactions:
- Clicking a result opens Media Preview.
- Save query to "Saved Searches."

Layman summary: "Search like Google, but across video, audio, and documents."

## 5) Graph Explorer

Purpose:
- Visualize relationships between assets, transcripts, and events.

Key UI elements:
- Graph canvas with nodes and edges.
- Node/edge type filters.
- Inspector panel showing properties.
- Expand neighbors / path exploration tools.

Interactions:
- Selecting a node highlights related assets.
- Open related assets in Data Explorer or Media Preview.

Layman summary: "A relationship map showing how clips, transcripts, and events
 connect." 

## 6) Ingestion

Purpose:
- Manage uploads, sources, and ingestion history.

Key UI elements:
- Upload panel (drag-drop or URL).
- Source registry (buckets, endpoints).
- Ingest status list.
- Error details with retry buttons.

Interactions:
- Upload triggers ingest pipeline.
- Clicking a failed ingest opens error logs.

Layman summary: "Where you send data into Retikon and check if it worked." 

## 7) Streams & Devices (Fleet)

Purpose:
- Manage live streams and edge devices.

Key UI elements:
- Device list with health status.
- Stream list with live indicators.
- Device detail (config, firmware, logs).
- Edge buffer policy controls.

Interactions:
- Start/stop stream.
- Push config updates (Pro).

Layman summary: "The place to manage cameras and devices." 

## 8) Pipelines

Purpose:
- Configure how data is processed (sampling, chunking, models).

Key UI elements:
- Pipeline registry (video/audio/image/document).
- Settings editor per pipeline.
- Model selection and versioning.
- Performance metrics.

Interactions:
- Changes apply to future ingests.
- Metrics link to Observability.

Layman summary: "Controls for how Retikon analyzes data." 

## 9) Data Factory

Purpose:
- Turn raw data into labeled datasets and trained models.

Key UI elements:
- Annotation workspace.
- Dataset manager with train/val/test split.
- Model registry with versions.
- Evaluation reports.

Interactions:
- Export labeled data to training.
- Promote a model to production.

Layman summary: "Tools to label data and improve AI models." 

## 10) Workflows

Purpose:
- Create automation pipelines and scheduled jobs.

Key UI elements:
- Workflow builder (DAG editor).
- Job schedules and run history.
- Retry and alert settings.

Interactions:
- Trigger workflows from events.
- View job results and logs.

Layman summary: "Automation for tasks like nightly analysis or compaction." 

## 11) Alerts & Webhooks

Purpose:
- Define alerts and notify external systems.

Key UI elements:
- Alert rule builder (conditions, time windows).
- Destination list (Slack, email, webhook).
- Delivery logs with retry/replay.

Interactions:
- Test webhook delivery.
- Pause/resume alerts.

Layman summary: "Set rules to get notified when something happens." 

## 12) Billing & Usage

Purpose:
- Monitor usage, costs, and invoices (Pro).

Key UI elements:
- Usage charts by project/stream.
- Cost breakdown by modality.
- Invoices and payment methods.
- Plan limits and overage alerts.

Interactions:
- Export usage to CSV.
- Configure budget alerts.

Layman summary: "See what you are using and what it costs." 

## 13) Admin / Settings

Purpose:
- Manage users, API keys, and policies.

Key UI elements:
- User list and roles.
- API key management with scopes.
- Audit log viewer.
- Privacy policies (Pro).

Interactions:
- Invite users.
- Rotate API keys.

Layman summary: "Manage who can access what." 

## 14) Observability

Purpose:
- System health, logs, and performance.

Key UI elements:
- Ingest throughput charts.
- Query latency charts.
- DLQ backlog and errors.
- Log viewer with correlation IDs.

Interactions:
- Drill into errors to see affected assets.

Layman summary: "See if the system is healthy and find issues fast." 

## 15) Integrations

Purpose:
- Connect to external systems (Kafka, Snowflake, etc.).

Key UI elements:
- Connector setup wizard.
- Connection status.
- Export/test buttons.

Interactions:
- Send test event.

Layman summary: "Connect Retikon to other tools you already use." 

## 16) Cross-Module Interactions
- Data Explorer results link to Graph Explorer and Media Preview.
- Alerts link to the underlying events in Data Explorer.
- Devices link to streams and ingestion logs.
- Workflows can trigger exports or compaction jobs.
- Billing links to high-usage projects or streams.

## 17) UX and Design Notes (for Designers)
- Favor fast scanning: cards, small charts, bold KPIs.
- Provide “empty state” guidance (e.g., upload your first file).
- Use strong status colors (green/yellow/red) with clear text labels.
- Keep actions consistent: “View details,” “Retry,” “Export,” “Save.”

## 18) Core vs Pro UI Split
Core UI includes:
- Dashboard, Data Explorer, Graph Explorer, Ingestion, Pipelines, basic Alerts.

Pro UI adds:
- Billing, Data Factory, Workflows, Fleet Ops, Advanced Alerts, Audit Logs.

## 19) Suggested Wireframe Order
1. Global shell + Dashboard
2. Data Explorer
3. Graph Explorer
4. Ingestion
5. Streams & Devices
6. Alerts
7. Billing
8. Admin / Settings
