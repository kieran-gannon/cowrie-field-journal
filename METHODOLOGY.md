# Methodology and reproducibility

Cowrie Field Journal is an experiment in AI-assisted threat intelligence. It publishes daily aggregate observations from one SSH honeypot. The model selects findings from those aggregates. Readers can inspect the same inputs and decide whether those selections were useful.

## Sensor setup

We run Cowrie in high-interaction SSH proxy mode. Cowrie receives incoming SSH connections and records authentication attempts. When it accepts a decoy login, Cowrie proxies the session to a disposable Linux virtual machine. Commands in that session interact with the guest's Linux environment.

The guest runs under QEMU/KVM on an isolated network with outbound internet access blocked. The backend periodically recreates the writable guest disk from a clean base image. Resets and backend errors can interrupt sessions. A recorded close establishes when the connection ended.

Cowrie records session activity. Some uploaded files are captured and SHA-256 verified on the host. A separate watcher observes filesystem changes inside the shared guest. Guest-reported changes have weaker provenance and may have no reliable link to a session. A recorded command establishes input. A verified capture establishes which bytes arrived. The public report makes no claim about process execution unless the evidence independently supports it.

## Daily measurements

The exporter reads SQLite in a read-only transaction. Each UTC window starts at midnight and ends at the next midnight, exclusive. Validation sessions and explicit validation markers are excluded. A session with recorded activity on multiple dates can contribute to the corresponding activity counts on each date.

| Field | Definition |
| --- | --- |
| Connections | Count of Cowrie connection events in the window |
| Unique source IPs | Distinct nonempty source IPs across those connection events |
| Sessions with accepted login | Distinct sessions with an accepted decoy login event in the window |
| Failed login attempts | Count of failed Cowrie authentication events |
| Sessions with commands | Distinct sessions with recorded shell input in the window |
| Shell commands | Count of recorded shell input events |
| Host-verified captures | Count of host-verified file observations with a valid SHA-256 |
| Unique host-verified samples | Count of distinct verified SHA-256 values |
| Backend errors | Count of Cowrie proxy backend connection error events |

Coverage is unverified. We count hourly bins containing at least one retained non-test Cowrie event. That measures observed activity. A bin with no events could reflect quiet traffic, a collection gap, or a date outside retention. Days with neither Cowrie events nor verified captures have null metrics and appear as gaps.

## Recurrence and privacy

The daily model input contains the selected day and 30 prior UTC days. Its seven-day baseline is the per-metric median for prior days with Cowrie events in that seven-day window. The model may select a comparison only when at least three days qualify. Differences can reflect coverage as well as changes in activity.

The exporter groups verified bytes privately by SHA-256. Samples recurring on two or more UTC days may receive a stable public alias derived using a private key. The alias allows published days to be compared without revealing the original hash. The export contains at most 12 recurring samples, prioritizing captures on the report day. A count of sessions with both a capture and an inferred download attempt requires both observations in the same session on the same UTC day. It establishes co-occurrence. The path by which the file arrived remains unverified.

The public files contain aggregate counts and derived sample aliases. Raw IPs, session IDs, credentials, command text, file paths, original hashes, recordings, and binary contents remain private. This version has no source-geography breakdown.

## Model and validation

We use `deepseek/deepseek-v4.1-flash` through OpenRouter. The [versioned prompt](scripts/brief_prompt.txt), [response schema and validator](scripts/generate_brief.py), and [context exporter](scripts/export_context.py) are public. Each daily page links to its report JSON and exact public model input.

DeepSeek selects and orders up to three findings. It returns evidence IDs and finding types. The validator accepts only eligible references and computes the published wording directly from source values. Prior model reports are never used as telemetry. An invalid response, timeout, or missing API key yields a stats-only report. The page names the model and prompt version. The same inputs can yield different selections on a rerun.

A daily report reflects one sensor's observations and exposure. Source infrastructure, shared operators, campaign identity, intent, and absence of activity beyond our sensor require independent evidence.

## Local verification

Run `python -m unittest discover -s tests -v` to exercise UTC boundaries, privacy exclusions, recurrence, session linkage, and brief validation against synthetic fixtures. Run `python -m http.server --directory site` to preview the public files. Raw telemetry is required to reproduce the original collection and extraction. The published aggregate input is sufficient to verify the values and evidence references used in the brief.
