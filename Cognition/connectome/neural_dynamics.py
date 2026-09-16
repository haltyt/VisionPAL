"""A small connectome-inspired leaky-integrate-and-fire circuit.

This is an interface-compatible prototype, not a claim to reproduce the full
Drosophila connectome.  Population wiring is explicit so it can later be
replaced by FlyWire/MaleCNS-derived edges without changing VisionPAL.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping

import numpy as np


@dataclass
class NeuralConfig:
    neurons_per_population: int = 96
    membrane_tau: float = 0.08
    synapse_tau: float = 0.12
    threshold: float = 1.0
    reset_voltage: float = 0.0
    refractory_sec: float = 0.012
    input_gain: float = 3.2
    noise_std: float = 0.015
    seed: int = 7
    motion_reflex_threshold: float = 0.28
    looming_reflex_threshold: float = 0.24
    looming_escape_threshold: float = 0.72


class LIFConnectome:
    """Six-population LIF network for looming escape and lateral avoidance."""

    POPULATIONS = (
        "visual_left",
        "visual_right",
        "looming",
        "escape",
        "turn_left",
        "turn_right",
        "forward",
    )

    def __init__(self, config: NeuralConfig | None = None):
        self.config = config or NeuralConfig()
        self.n = max(8, int(self.config.neurons_per_population))
        self.rng = np.random.default_rng(self.config.seed)
        self.voltage = {name: np.zeros(self.n, dtype=np.float32) for name in self.POPULATIONS}
        self.refractory = {name: np.zeros(self.n, dtype=np.float32) for name in self.POPULATIONS}
        self.synaptic = {name: 0.0 for name in self.POPULATIONS}
        self.rates = {name: 0.0 for name in self.POPULATIONS}

    def reset(self) -> None:
        for name in self.POPULATIONS:
            self.voltage[name].fill(0.0)
            self.refractory[name].fill(0.0)
            self.synaptic[name] = 0.0
            self.rates[name] = 0.0

    def _population_step(self, name: str, current: float, dt: float) -> float:
        cfg = self.config
        voltage = self.voltage[name]
        refractory = self.refractory[name]
        active = refractory <= 0.0
        noise = self.rng.normal(0.0, cfg.noise_std, self.n).astype(np.float32)
        voltage[active] += (dt / cfg.membrane_tau) * (-voltage[active] + current + noise[active])
        refractory[:] = np.maximum(refractory - dt, 0.0)
        spikes = active & (voltage >= cfg.threshold)
        voltage[spikes] = cfg.reset_voltage
        refractory[spikes] = cfg.refractory_sec
        # Normalized activity approximates a population firing rate over one step.
        rate = float(np.mean(spikes))
        self.rates[name] = 0.75 * self.rates[name] + 0.25 * rate
        return self.rates[name]

    def step(
        self,
        sensory: Mapping[str, Any],
        body: Mapping[str, Any] | None = None,
        modulation: Mapping[str, Any] | None = None,
        dt: float = 0.02,
    ) -> Dict[str, Any]:
        dt = float(np.clip(dt, 0.001, 0.1))
        body = body or {}
        modulation = modulation or {}
        gain = self.config.input_gain

        left = float(np.clip(sensory.get("motion_left", 0.0), 0.0, 1.0))
        right = float(np.clip(sensory.get("motion_right", 0.0), 0.0, 1.0))
        looming = float(np.clip(sensory.get("looming", 0.0), 0.0, 1.0))
        collision = 1.0 if body.get("collision", False) else 0.0
        threat = float(np.clip(modulation.get("threat", 0.0), -1.0, 1.0))
        exploration = float(np.clip(modulation.get("exploration", 0.0), -1.0, 1.0))

        sensory_rates = {
            "visual_left": self._population_step("visual_left", gain * left, dt),
            "visual_right": self._population_step("visual_right", gain * right, dt),
            "looming": self._population_step(
                "looming", gain * np.clip(looming + 0.55 * collision + 0.2 * threat, 0.0, 1.5), dt
            ),
        }

        # Synaptic low-pass makes responses persist beyond a single video frame.
        decay = float(np.exp(-dt / self.config.synapse_tau))
        for name, rate in sensory_rates.items():
            self.synaptic[name] = decay * self.synaptic[name] + (1.0 - decay) * rate

        visual_l = max(left, self.synaptic["visual_left"] * 5.0)
        visual_r = max(right, self.synaptic["visual_right"] * 5.0)
        loom_drive = max(looming, self.synaptic["looming"] * 5.0)
        escape = self._population_step("escape", gain * np.clip(1.35 * loom_drive + collision, 0.0, 2.0), dt)
        turn_left = self._population_step(
            "turn_left", gain * np.clip(visual_r + 0.45 * loom_drive - 0.35 * visual_l, 0.0, 1.5), dt
        )
        turn_right = self._population_step(
            "turn_right", gain * np.clip(visual_l + 0.45 * loom_drive - 0.35 * visual_r, 0.0, 1.5), dt
        )
        forward_drive = np.clip(0.30 + 0.25 * exploration - 0.8 * loom_drive - 0.6 * collision, 0.0, 1.0)
        forward = self._population_step("forward", gain * float(forward_drive), dt)

        return {
            "populations": {name: round(float(rate), 6) for name, rate in self.rates.items()},
            "motor": {
                "escape": round(max(escape, loom_drive), 6),
                "turn_left": round(max(turn_left, visual_r), 6),
                "turn_right": round(max(turn_right, visual_l), 6),
                "forward": round(max(forward, float(forward_drive)), 6),
            },
            "neuron_count": self.n * len(self.POPULATIONS),
        }
