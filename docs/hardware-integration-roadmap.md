# A4S+ — Hardware integration roadmap

> A4S+ today is a software prototype with **no hardware attached**. This
> document is a plan, not a description of something that exists. Nothing below
> has been built, wired, calibrated or tested against a device.

## 1. The claim this document supports

The prototype was built so that hardware can be added **without redesigning
anything**. That claim is only worth making if it can be pointed at, so here is
exactly where the seam is and exactly what changes.

## 2. Where the seam is

`backend/app/datasources/base.py` defines the only way telemetry enters the
system:

```python
class DataSource(ABC):
    kind: DataSourceKind = DataSourceKind.SIMULATION   # provenance stamp

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    async def snapshot(self) -> list[VitalSample]: ...

    @abstractmethod
    def stream(self) -> AsyncIterator[list[VitalSample]]: ...
```

Everything downstream — `IngestionService`, `RiskEngine`, `AlertEngine`,
`TwinService`, `PredictionService`, the dashboard, the WebSocket fan-out — is
written against `VitalSample` and `EnvironmentSample`. None of it knows or
cares where a sample came from.

`VitalSample.source` is **mandatory**, so provenance travels with the data into
the database column `vital_readings.source` and out to the UI. That is the
mechanism that will keep a mixed simulated/real deployment honest.

## 3. What is already declared and deliberately unimplemented

| Class | Intended role | Behaviour today |
|---|---|---|
| `WearableDataSource` | BLE/LoRa wearable vitals gateway | Constructor raises `NotImplementedError` |
| `UAVDataSource` | UAV telemetry and relayed personnel beacons | Constructor raises `NotImplementedError` |
| `EdgeDataSource` | On-site aggregator with store-and-forward | Constructor raises `NotImplementedError` |

They raise rather than return plausible values, on purpose: a stub that
returned invented numbers would let fabricated data reach the UI wearing a real
provenance stamp. They are surfaced honestly at
`GET /api/v1/simulation/data-source` and on the admin **System** page under
"Declared but not implemented".

## 4. What changes, per tier

| Tier | Change required | Change *not* required |
|---|---|---|
| Ingestion | New `DataSource` subclass; bind it instead of `SimulationDataSource` | — |
| Risk engine | none | already storage- and origin-agnostic (`VitalSnapshot`) |
| ML features | none | `ml/features.py` consumes rows, not devices |
| ML models | **retraining on real data** (see §7) | architecture, registry, serving path |
| Database | migration to add device identity, calibration and quality columns | all 23 existing tables |
| API | none for reads; new device-management endpoints | response shapes |
| Frontend | provenance badges switch from "simulated" to per-signal status | every page |

## 5. Staged plan

### Stage 0 — today
Simulation only. One `DataSource`. Every screen labelled SIMULATED DATA.

### Stage 1 — one real signal, side by side
Add a single wearable adapter for **SpO₂ and heart rate only**, running
*alongside* the simulator. Both write to `vital_readings` with different
`source` values, and the UI shows both series. This is the cheapest way to find
out how wrong the simulator is.

New requirements that appear immediately, and which the current schema does not
have:

- **Device identity** — `device_id`, firmware version, battery.
- **Signal quality** — most optical sensors report a confidence or perfusion
  index. A reading with poor quality must be *usable but discounted*, not
  silently averaged in.
- **Calibration** — per-device offsets, with the calibration record stored so a
  historical reading can be re-derived.
- **Clock discipline** — devices drift and buffer. `recorded_at` must come from
  the device, `created_at` from the server, and the gap must be visible.
- **Gaps and dropouts** — real streams stop. The pipeline must distinguish
  "no data" from "normal", which is exactly why the prediction path already
  refuses to run on fewer than 24 readings instead of padding.

### Stage 2 — full personnel telemetry
All eight physiological channels plus GNSS position. Adds:

- **Sensor fusion** when two devices disagree.
- **Outlier rejection** — a motion artefact reading SpO₂ 62 % must not fire a
  critical alert. This needs a plausibility filter that does not exist today.
- **Per-person baselines learned from data** rather than seeded constants.
- **Consent, retention and data-protection controls**, which are a legal
  prerequisite, not a feature.

### Stage 3 — environment
Replace the synthetic environment model with a weather feed and local stations,
and replace procedural terrain with a real **DEM** (e.g. SRTM/Copernicus)
plus an avalanche-forecast source. `terrain_maps.is_synthetic` becomes `false`
for those maps and the honest disclaimer on the terrain page changes with it.

Note the asymmetry: real terrain changes route planning from "plausible" to
"defensible", and it is by far the cheapest stage. It is also the one that most
improves the product, which is why it should probably come before Stage 2.

### Stage 4 — UAV link
A MAVLink/MAVSDK adapter for real telemetry. **Read-only first**, for a long
time. Command uplink requires airworthiness review, a failsafe hierarchy,
airspace authorisation, link-loss behaviour, and a human always in the loop.
The current API's habit of returning **422** when the simulation is not running
is the right shape for this: it already refuses to pretend a command had an
effect.

### Stage 5 — edge deployment
An on-site aggregator that buffers during connectivity loss and forwards later,
with conflict resolution for out-of-order arrival, and optional local
inference so alerts survive a link outage.

## 6. Sequencing, honestly

The cheapest high-value stages are **3 (real terrain)** and **1 (one real
signal)**. The most expensive and least valuable to rush is **4 (UAV command
uplink)**. A team with limited time should do terrain first, then one wearable
signal, and should not touch UAV command at all.

## 7. What hardware would do to the ML

This is the part most easily glossed over, so it is stated plainly.

**The current models would need to be retrained from scratch and their metrics
discarded.** The numbers in [`ml.md`](ml.md) describe how well the models
learned *this simulator*. Real sensors bring dropouts, artefacts, irregular
sampling, inter-device variation and genuine physiological diversity — none of
which the training distribution contains.

Also, and more fundamentally: **the labels would have to change.** Today the
target is the rule engine's own future output, which caps how much the model can
add. Real value requires labels from clinical outcomes — a diagnosis, an
evacuation decision, a validated AMS score — which requires ethics approval,
clinician involvement and a study design. That is a research programme, not a
sprint.

Realistically, the sequence model is the one that stands to gain: irregular,
noisy, long-memory real data is where an LSTM should beat the tabular
summarisation that currently outperforms it.

## 8. What must not be claimed at any stage

- That the system is clinically validated, unless a clinical study says so.
- That any prediction is a diagnosis.
- That the UAV link is safe for command-and-control, without an airworthiness
  case.
- That data is encrypted at rest, until it is.
- That the crypto demonstration protects anything.

Each of those claims is currently blocked from re-entering the codebase by
`scripts/honesty-scan.sh`, which fails the build on unqualified overclaiming
language. That check should stay in place as hardware is added — it is more
useful then, not less.
