# Chain LLM Cloud — Consecutive (Chain) Invocation Across Two Cloud Providers

This project implements **consecutive invocations (chain invocation)** using **two LLM services** running in **Docker inside VMs**, deployed across **two different cloud providers**:

- **AWS** hosts **Service A** (API + Ollama model A)
- **GCP** hosts **Service B** behind a **Load Balancer + Managed Instance Group (MIG)** with autoscaling (API + Ollama model B)

Service A receives a request, runs a **local LLM step**, then forwards the request to Service B for the **remote LLM step**, and returns a combined response.

The project also includes a custom **workload generator** (`loadgen/loadgen.py`) to test throughput and latency for multiple RPS points.

---

## Requirements (Local Machine)

- Git
- Docker + Docker Compose
- Python 3.10+ (recommended)
- `pip install requests aiohttp` (only needed if you run loadgen locally)

---

## Architecture

### Service A (AWS)
- Exposes:
  - `GET /health`
  - `POST /chain`
- Runs:
  - `service-a-api` (FastAPI)
  - `ollama-a` (Ollama container)
- Behavior:
  1. Validates 1000+ char prompt
  2. Calls local Ollama (model A)
  3. Calls remote Service B `/invoke` via public LB URL
  4. Returns combined timing and outputs

### Service B (GCP + LB + MIG)
- Exposes:
  - `GET /health`
  - `POST /invoke`
- Runs per VM:
  - `service-b-api` (FastAPI)
  - `ollama-b` (Ollama container)
- Behind:
  - External HTTP Load Balancer (single IP)
  - MIG autoscaling
- Behavior:
  1. Validates 1000+ char prompt
  2. Calls Ollama (model B)
  3. Sleeps if needed to ensure minimum processing time (workload requirement)
  4. Returns result + timing + host identifier

---

## Endpoints

### Service A (AWS)
- `GET http://13.48.196.191:8001/health`
- `POST http://13.48.196.191:8001/chain`

### Service B (GCP)
- `GET http://34.89.191.57/health`
- `POST http://34.89.191.57/invoke`

> Note: Service B is exposed on port 80 via the load balancer. The MIG instances run the container on port 8002 internally.

---


## Quick Test Guide (Functional Tests)

### 1) Check Service B via Load Balancer
```bash
curl -s http://34.89.191.57/health
```
You should get JSON like:

```json
{"ok":true,"service":"b","host":"<container_id_or_host>"}
```

If you run it multiple times, host may change (that’s expected if the LB routes to different instances):

```bash
for i in {1..20}; do curl -s http://34.89.191.57/health; echo; done
```

### 2) Test Service B /invoke (1000+ char prompt)

Using Python (recommended, avoids shell JSON issues):

```bash
python - << 'PY'
import requests
prompt = "A"*1000 + "\nSay hi in 2 short sentences."
r = requests.post("http://34.89.191.57/invoke", json={"prompt": prompt}, timeout=300)
print(r.status_code)
print(r.text[:300])
PY
```

Expected: `200` and JSON containing `model`, `llm_text`, `timing`, and `host`.

### 3) Check Service A health (AWS)
```bash
curl -s http://13.48.196.191:8001/health
```

### 4) Test full chain (AWS -> GCP)
```bash
python - << 'PY'
import requests, time
aws = "13.48.196.191"
prompt = "A"*1000 + "\nExplain scalability vs elasticity in 2 short paragraphs."
t0 = time.perf_counter()
r = requests.post(f"http://{aws}:8001/chain", json={"prompt": prompt}, timeout=300)
print("status:", r.status_code)
print("body_head:", r.text[:300])
if r.status_code == 200:
    data = r.json()
    print("timing:", data["timing"])
    print("wall_seconds:", round(time.perf_counter() - t0, 3))
PY
```

Expected: `200` and a response containing:
- `model_a`
- `remote_b_url`
- `a_summary`
- `b_result.llm_text`
- `timing` with `a_local_seconds`, `b_remote_seconds`, `end_to_end_seconds`

## Workload Generator (Load Testing)

The workload generator runs a fixed-duration test per RPS point and writes CSV results into `results/`.

Example (run against AWS chain endpoint):

```bash
RUN_TAG=aws TARGET_URL="http://13.48.196.191:8001/chain" python loadgen/loadgen.py
```

Example (run against GCP Service B directly):

```bash
RUN_TAG=gcp TARGET_URL="http://34.89.191.57>/invoke" python loadgen/loadgen.py
```

RPS points required by the assignment:

```yaml
1, 10, 50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 1000
```


Generated CSV output files will look like:
- `results/aws_chain_rps100.csv`
- `results/gcp_invoke_rps500.csv`

---

## Scaling (GCP MIG)

Service B runs in a Managed Instance Group behind a load balancer. Autoscaling is configured via CPU or LB utilization, with limits:

- min replicas: 1
- max replicas: 3 (or whatever quota allows)

To confirm scaling and load balancing:
1. Run loadgen at high RPS
2. Watch MIG target size:

```bash
watch -n 5 "gcloud compute instance-groups managed describe llm-b-mig --zone europe-west3-c --format='get(targetSize)'"
```

3. Confirm multiple hosts returned by /health:

```bash
for i in {1..20}; do curl -s http://34.89.191.57/health; echo; done
```

---

## What This Project Demonstrates

- LLM microservices deployed inside VMs using Docker
- Chain invocation across two cloud providers
- Load generation across multiple RPS targets
- Measurement of latency, throughput, scaling behavior, and elasticity under load
- Logs + CSV results suitable for plotting and reporting