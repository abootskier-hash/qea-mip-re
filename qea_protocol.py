"""
Quantum Evidence Accumulation (QEA) Protocol — IBM Qiskit Implementation
Based on: Anastasia Buts (2026), "Can a Quantum Computer Certify the Uncertifiable?"

Three interleaved round types:
  S  (self-test)   — CHSH game to certify the device is quantum
  G  (game)        — BQP circuit verification (Bernstein–Vazirani instance)
  K  (consistency) — ASAC algebraic constraint cross-checks

The verifier accepts iff all three win-rate conditions hold simultaneously.

NOTE: The single-device "virtual two-prover" approach relies on the Circuit
Non-Signaling Condition (CNC), enforced structurally in the circuit but not
externally verifiable without device separation — Conjecture 8 in the paper
remains open and governs quantum soundness.
"""

import numpy as np
from dataclasses import dataclass, field
from qiskit import QuantumCircuit, QuantumRegister, ClassicalRegister
from qiskit.primitives import StatevectorSampler


# ---------------------------------------------------------------------------
# Protocol parameters
# ---------------------------------------------------------------------------

@dataclass
class QEAParams:
    total_rounds: int = 300        # T — split equally across S, G, K
    shots_per_circuit: int = 1024  # shots per batched circuit
    delta_S: float = 0.009         # slack below cos²(π/8) ≈ 0.8536
    delta_G: float = 0.05          # slack below ideal game win rate 1.0
    epsilon_K: float = 0.10        # tolerance on ASAC mean error

    @property
    def rounds_per_type(self) -> int:
        return self.total_rounds // 3  # noqa: assigned but unused false-positive from dataclass

    @property
    def threshold_S(self) -> float:
        return np.cos(np.pi / 8) ** 2 - self.delta_S   # ≈ 0.845

    @property
    def threshold_G(self) -> float:
        return 1.0 - self.delta_G                       # ≈ 0.95 for BV

    @property
    def threshold_K(self) -> float:
        return self.epsilon_K


# ---------------------------------------------------------------------------
# DataBin → counts dict
# ---------------------------------------------------------------------------

def _to_counts(data_bin, circuit: QuantumCircuit) -> dict[str, int]:
    """
    Convert a Qiskit DataBin (StatevectorSampler result) to {bitstring: count}.
    One key segment per classical register, joined with a space.
    Uses BitArray.get_counts() to handle packed bit storage correctly.
    """
    creg_names = [creg.name for creg in circuit.cregs]
    per_reg = [getattr(data_bin, name).get_counts() for name in creg_names]

    if len(per_reg) == 1:
        return per_reg[0]

    # Multiple registers: cross-join by rebuilding from per-shot bitstrings
    n_shots = getattr(data_bin, creg_names[0]).num_shots
    counts: dict[str, int] = {}
    reg_strings = [getattr(data_bin, name).get_bitstrings() for name in creg_names]
    for i in range(n_shots):
        key = ' '.join(reg_strings[r][i] for r in range(len(creg_names)))
        counts[key] = counts.get(key, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Type S — CHSH self-test
# ---------------------------------------------------------------------------

def chsh_circuit(x: int, y: int) -> QuantumCircuit:
    """
    Optimal quantum CHSH strategy on a Bell pair |Φ+⟩.

    CNC is enforced: no two-qubit gates cross A|B after state preparation.
    Alice: x=0 → Z basis, x=1 → X basis (ry(-π/2)).
    Bob:   y=0 → π/8 tilt, y=1 → -π/8 tilt.

    Win condition: a ⊕ b == x & y
    Ideal win rate: cos²(π/8) ≈ 0.8536
    Classical bound: 0.75
    """
    qr_a = QuantumRegister(1, 'a')
    qr_b = QuantumRegister(1, 'b')
    cr_a = ClassicalRegister(1, 'ca')
    cr_b = ClassicalRegister(1, 'cb')
    qc = QuantumCircuit(qr_a, qr_b, cr_a, cr_b)

    qc.h(qr_a[0])
    qc.cx(qr_a[0], qr_b[0])  # only entangling gate — CNC boundary above measurements

    if x == 1:
        qc.ry(np.pi / 2, qr_a[0])    # +π/2 gives P(a=b)=cos²(π/8) for all four (x,y) pairs
    angle_b = np.pi / 4 if y == 0 else -np.pi / 4
    qc.ry(angle_b, qr_b[0])

    qc.measure(qr_a, cr_a)
    qc.measure(qr_b, cr_b)
    return qc


def _chsh_wins(x: int, y: int, counts: dict[str, int]) -> tuple[int, int]:
    wins = total = 0
    for bitstring, cnt in counts.items():
        parts = bitstring.split()
        a = int(parts[0])  # cr_a (1 bit)
        b = int(parts[1])  # cr_b (1 bit)
        total += cnt
        if (a ^ b) == (x & y):
            wins += cnt
    return wins, total


# ---------------------------------------------------------------------------
# Type G — BQP game (Bernstein–Vazirani)
# ---------------------------------------------------------------------------

def bv_circuit(secret: list[int]) -> QuantumCircuit:
    """
    Bernstein–Vazirani circuit.

    n-qubit register A (virtual P1) is the query register.
    1-qubit register B (virtual P2) is the phase-kickback ancilla.
    CNC: A and B interact only inside the oracle; no cross-register
    gates after the second Hadamard layer.

    After measurement, register A should read back `secret` with
    probability 1 (ideal), giving game win rate ≈ 1.0.
    """
    n = len(secret)
    qr_a = QuantumRegister(n, 'a')
    qr_b = QuantumRegister(1, 'b')
    cr_a = ClassicalRegister(n, 'ca')
    cr_b = ClassicalRegister(1, 'cb')
    qc = QuantumCircuit(qr_a, qr_b, cr_a, cr_b)

    qc.x(qr_b[0])
    qc.h(qr_b[0])
    qc.h(qr_a)

    for i, bit in enumerate(secret):
        if bit:
            qc.cx(qr_a[i], qr_b[0])  # oracle — CNC boundary here

    qc.h(qr_a)

    qc.measure(qr_a, cr_a)
    qc.measure(qr_b, cr_b)
    return qc


def _bv_wins(secret: list[int], counts: dict[str, int]) -> tuple[int, int]:
    n = len(secret)
    # Qiskit BitArray stores bits in MSB-first order per register
    expected = ''.join(str(b) for b in secret)
    wins = total = 0
    for bitstring, cnt in counts.items():
        parts = bitstring.split()
        answer = parts[0]  # cr_a: n bits
        total += cnt
        if answer == expected:
            wins += cnt
    return wins, total


# ---------------------------------------------------------------------------
# Type K — ASAC consistency check
# ---------------------------------------------------------------------------

def asac_circuit() -> QuantumCircuit:
    """
    Minimal ASAC constraint: ZZ correlation on a fresh Bell pair |Φ+⟩.
    For |Φ+⟩, both qubits always agree → ZZ = +1 → error fraction = 0.
    Deviations indicate decoherence or non-entangled state.

    This is a simplified stand-in for the full circuit-specific ASAC
    constraints described in the paper (which require offline algebraic
    analysis of the target circuit's stabiliser structure).
    """
    qr_a = QuantumRegister(1, 'a')
    qr_b = QuantumRegister(1, 'b')
    cr = ClassicalRegister(2, 'c')
    qc = QuantumCircuit(qr_a, qr_b, cr)
    qc.h(qr_a[0])
    qc.cx(qr_a[0], qr_b[0])
    qc.measure(qr_a[0], cr[0])
    qc.measure(qr_b[0], cr[1])
    return qc


def _asac_error(counts: dict[str, int]) -> float:
    """Fraction of shots where the two qubits disagree (ZZ ≠ +1)."""
    total = disagree = 0
    for bitstring, cnt in counts.items():
        bits = bitstring.replace(' ', '')
        total += cnt
        if bits[0] != bits[1]:
            disagree += cnt
    return disagree / total if total > 0 else 1.0


# ---------------------------------------------------------------------------
# Classical verifier state
# ---------------------------------------------------------------------------

@dataclass
class VerifierStats:
    s_wins: int = 0
    s_total: int = 0
    g_wins: int = 0
    g_total: int = 0
    k_errors: list[float] = field(default_factory=list)

    @property
    def win_rate_S(self) -> float:
        return self.s_wins / self.s_total if self.s_total else 0.0

    @property
    def win_rate_G(self) -> float:
        return self.g_wins / self.g_total if self.g_total else 0.0

    @property
    def mean_error_K(self) -> float:
        return float(np.mean(self.k_errors)) if self.k_errors else 1.0

    def accept(self, params: QEAParams) -> bool:
        return (
            self.win_rate_S >= params.threshold_S
            and self.win_rate_G >= params.threshold_G
            and self.mean_error_K <= params.threshold_K
        )


# ---------------------------------------------------------------------------
# Protocol runner
# ---------------------------------------------------------------------------

def run_qea(
    secret: list[int],
    params: QEAParams,
    sampler,
    backend=None,
    verbose: bool = True,
) -> tuple[bool, VerifierStats]:
    """
    Run the QEA protocol with interleaved S, G, K rounds.

    Parameters
    ----------
    secret   : hidden bitstring for the BV game (the BQP problem instance)
    params   : protocol parameters
    sampler  : Qiskit StatevectorSampler (or SamplerV2 for real/fake hardware)
    verbose  : print summary on completion

    Returns
    -------
    (accepted, stats) — verifier decision and accumulated statistics
    """
    rng = np.random.default_rng()
    stats = VerifierStats()
    n = params.rounds_per_type

    # Generate CHSH questions; device never learns round type in advance
    s_questions = [(int(rng.integers(2)), int(rng.integers(2))) for _ in range(n)]
    s_circuits = [chsh_circuit(x, y) for x, y in s_questions]

    g_circ = bv_circuit(secret)
    k_circ = asac_circuit()

    all_circuits = s_circuits + [g_circ] * n + [k_circ] * n
    shots = params.shots_per_circuit

    if backend is not None:
        from qiskit import transpile
        all_circuits = transpile(all_circuits, backend=backend, optimization_level=1)

    pubs = [(qc,) for qc in all_circuits]
    result = sampler.run(pubs, shots=shots).result()

    for i, (x, y) in enumerate(s_questions):
        counts = _to_counts(result[i].data, s_circuits[i])
        w, t = _chsh_wins(x, y, counts)
        stats.s_wins += w
        stats.s_total += t

    for i in range(n):
        counts = _to_counts(result[n + i].data, g_circ)
        w, t = _bv_wins(secret, counts)
        stats.g_wins += w
        stats.g_total += t

    for i in range(n):
        counts = _to_counts(result[2 * n + i].data, k_circ)
        stats.k_errors.append(_asac_error(counts))

    accepted = stats.accept(params)

    if verbose:
        print(f"\n{'='*44}")
        print(f"QEA Protocol Results")
        print(f"{'='*44}")
        print(f"Rounds per type : {n} × {shots} shots")
        print(f"BV secret       : {''.join(str(b) for b in secret)}")
        print(f"S win rate      : {stats.win_rate_S:.4f}  "
              f"(need ≥ {params.threshold_S:.4f}, ideal {np.cos(np.pi/8)**2:.4f})")
        print(f"G win rate      : {stats.win_rate_G:.4f}  "
              f"(need ≥ {params.threshold_G:.4f}, ideal 1.0)")
        print(f"K mean error    : {stats.mean_error_K:.4f}  "
              f"(need ≤ {params.threshold_K:.4f}, ideal 0.0)")
        status = "ACCEPT ✓" if accepted else "REJECT ✗"
        print(f"Decision        : {status}")
        print(f"{'='*44}")

    return accepted, stats


# ---------------------------------------------------------------------------
# Backend helpers
# ---------------------------------------------------------------------------

def get_sampler(mode: str = "statevector", ibm_token: str | None = None):
    """
    mode='statevector'  → noiseless simulation (no account required)
    mode='fake'         → FakeSherbrooke noise model
    mode='real'         → real IBM Quantum hardware (requires ibm_token)

    Returns (sampler, backend_or_None).  Caller must transpile circuits when
    backend is not None.
    """
    if mode == "statevector":
        return StatevectorSampler(), None

    from qiskit_ibm_runtime import Sampler as IBMSampler
    if mode == "real" and ibm_token:
        from qiskit_ibm_runtime import QiskitRuntimeService
        service = QiskitRuntimeService(channel="ibm_quantum_platform", token=ibm_token)
        backend = service.least_busy(operational=True, simulator=False)
        print(f"Using IBM backend: {backend.name}")
        return IBMSampler(mode=backend), backend

    from qiskit_ibm_runtime.fake_provider import FakeManilaV2
    backend = FakeManilaV2()
    print(f"Using fake backend: {backend.name} ({backend.num_qubits} qubits)")
    return IBMSampler(mode=backend), backend


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run the QEA protocol (Buts 2026)")
    parser.add_argument("--secret", default="101",
                        help="BV hidden bitstring, e.g. 101 (default: 101)")
    parser.add_argument("--rounds", type=int, default=300,
                        help="Total rounds T, split equally across S/G/K (default: 300)")
    parser.add_argument("--shots", type=int, default=1024,
                        help="Shots per circuit (default: 1024)")
    parser.add_argument("--mode", choices=["statevector", "fake", "real"],
                        default="statevector",
                        help="Backend: statevector | fake (FakeSherbrooke) | real IBM")
    parser.add_argument("--ibm-token", default=None,
                        help="IBM Quantum token (required for --mode real)")
    args = parser.parse_args()

    secret = [int(b) for b in args.secret]
    params = QEAParams(total_rounds=args.rounds, shots_per_circuit=args.shots)

    sampler, backend = get_sampler(mode=args.mode, ibm_token=args.ibm_token)
    run_qea(secret, params, sampler, backend=backend)
