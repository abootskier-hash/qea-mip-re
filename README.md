# Quantum Evidence Accumulation (QEA) — Implementation

Implementation of the QEA protocol from:

> Boots, Anastasia. (2026). *Can a Quantum Computer Certify the Uncertifiable?
> Quantum Evidence Accumulation via MIP\* = RE.* arXiv preprint.

The protocol uses the MIP\* = RE result to let a **classical verifier** certify
outputs from a **single quantum device**, with no cryptographic assumptions.
Three interleaved round types (S, G, K) must all pass simultaneously for
the verifier to accept.

---

## Files

| File | Description |
|---|---|
| `qea_protocol.py` | Protocol implementation — circuits, verifier, runner |
| `qea_experiment.ipynb` | Notebook with 8 experiments and plots |
| `qea_results.png` | Dashboard figure produced by the notebook |

---

## Requirements

Python 3.11+ and the following packages:

```
qiskit>=2.0
qiskit-ibm-runtime>=0.50
numpy
scipy
matplotlib
jupyter
```

Install everything at once:

```bash
pip install qiskit qiskit-ibm-runtime numpy scipy matplotlib jupyter
```

---

## Run — command line

**Noiseless simulation (no account needed):**

```bash
python qea_protocol.py --secret 101 --rounds 300 --shots 2048
```

**With IBM device noise model (still runs locally):**

```bash
python qea_protocol.py --secret 101 --rounds 90 --shots 2048 --mode fake
```

**On real IBM Quantum hardware:**

```bash
python qea_protocol.py --secret 101 --rounds 90 --shots 1024 --mode real --ibm-token YOUR_TOKEN
```

### All flags

| Flag | Default | Description |
|---|---|---|
| `--secret` | `101` | Hidden bitstring for the BV game, e.g. `1011` |
| `--rounds` | `300` | Total rounds T, split equally across S / G / K |
| `--shots` | `1024` | Shots per circuit |
| `--mode` | `statevector` | `statevector` / `fake` / `real` |
| `--ibm-token` | — | IBM Quantum API token (required for `--mode real`) |

---

## Run — notebook

```bash
jupyter notebook qea_experiment.ipynb
```

Run all cells top to bottom. The final cell saves `qea_results.png`.

To use the fake noise model in the notebook, cell `0061` already calls
`get_sampler('fake')` — no changes needed.

---

## Run on IBM Quantum Cloud

### 1. Get a token

Create a free account at [quantum.ibm.com](https://quantum.ibm.com) and copy
your API token from the dashboard.

### 2. Save credentials (once)

```python
from qiskit_ibm_runtime import QiskitRuntimeService
QiskitRuntimeService.save_account(
    channel="ibm_quantum_platform",
    token="YOUR_TOKEN_HERE",
    overwrite=True,
)
```

### 3. Run

```bash
python qea_protocol.py --secret 101 --rounds 90 --shots 1024 --mode real --ibm-token YOUR_TOKEN
```

`get_sampler('real')` calls `service.least_busy()` to pick the IBM backend
with the shortest queue. Circuits are transpiled to that backend's native gate
set automatically before submission.

**Practical notes:**
- BV with a 3-bit secret needs 4 qubits; all IBM backends have ≥ 5.
- 90 rounds × 3 types = 270 circuit submissions; expect 5–15 min queue time.
- Off-peak hours (US evenings / weekends) have shorter queues.

---

## Protocol overview

```
Verifier (classical)                 Device (quantum)
      |                                     |
      |── T rounds, type unknown ──────────>|
      |                                     |
      |   Type S (1/3):  CHSH questions     |── Bell pair on probe qubits
      |   Type G (1/3):  game questions     |── BV circuit on algorithmic qubits
      |   Type K (1/3):  ASAC constraints   |── ZZ correlation check
      |                                     |
      |<── answers (a, b) ─────────────────|
      |                                     |
      └── Accept iff:
            S win rate  ≥ cos²(π/8) − δ_S   ≈ 0.845  (quantum > classical 0.75)
            G win rate  ≥ 1.0 − δ_G          ≈ 0.950  (BV solved correctly)
            K mean err  ≤ ε_K                 ≤ 0.100  (Bell pair coherent)
```

**Classical soundness** (unconditional): a classical device passes the
S-condition with probability < 10⁻⁴⁰⁸ for T_S = 52,100 self-test rounds.
Follows from Bell's theorem + Hoeffding concentration.

**Quantum soundness** (conditional): requires Conjecture 8 from the paper
(bounded single-device win-rate inflation). Open problem.

---

## Known limitations

- **Single-device gap.** MIP\* = RE requires two separated provers. This
  implementation uses one device as virtual P1 + P2, enforcing the
  Circuit Non-Signaling Condition (CNC) by circuit structure. CNC cannot
  be externally verified — the protocol assumes honest-but-untrusted hardware.
- **Game encoding.** The Type G round uses Bernstein–Vazirani as the BQP
  verification task. The full MIP\* = RE game construction for arbitrary
  circuits is not explicitly computable in closed form.
- **ASAC constraints.** Type K uses ZZ correlation on a Bell pair as a
  simplified stand-in. Full ASAC requires algebraic analysis of the target
  circuit's stabiliser structure.
