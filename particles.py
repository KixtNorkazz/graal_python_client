"""GS2 particle emitters (`findimg(n)` -> `emitter.*`): a software particle system.

Semantics follow the RP server scripts (442 addlocalmodifier calls) and are partly inferred, see README:
  emitter.delaymin/delaymax  seconds between emissions, emitter.nrofparticles per emission, emitter.maxparticles alive limit,
  emitter.emissionoffset {x,y,z}, emitter.emit() = emit one batch now, emitter.isfrozen = stop, emitter.particle.* = new-particle defaults
  (image, lifetime, speed, angle, spin, zoom, red/green/blue/alpha, mode, rotation, stretchy).
  Modifiers: addlocalmodifier(type, start, end, attr, op, v1, v2): "once" = applied at birth with a random value in [v1,v2];
  "range" = between `start`..`end` seconds of the particle's age, value goes v1 -> v2 (replace: set it, add: per second, multiply: per second);
  addglobalmodifier("impulse", ...) = every random(start,end) seconds applied to all live particles; addemitmodifier = like "once" at emission.
  Motion: x += cos(angle)*speed*dt, y -= sin(angle)*speed*dt (speed in px/s: inferred from the scripts), rotation += spin*dt.
  Unverified guesses: units of speed and x/y modifiers, particle mode 0 = additive / 1 = normal alpha (the scripts comment "mode = 1 // alpha transparent")."""
import math, random

MAX_PARTICLES = 300
REAL = [False]

def _rand(a, b): return random.uniform(a, b) if REAL[0] else (a + b) / 2

class Mod:
    def __init__(self, kind, start, end, attr, op, v1, v2):
        self.kind, self.start, self.end, self.attr, self.op, self.v1, self.v2 = kind, start, end, attr.lower(), op.lower(), v1, v2
        self.next = None

    def apply(self, p, value, dt=1.0):
        cur = p.get(self.attr, 0.0)
        if self.op == "replace": p[self.attr] = value
        elif self.op == "add": p[self.attr] = cur + value
        elif self.op == "multiply": p[self.attr] = cur * value

class Emitter:
    PROPS = {"delaymin": 0.1, "delaymax": 0.1, "nrofparticles": 1.0, "maxparticles": 100.0, "attachposition": 0.0, "cliptoscreen": 0.0,
             "autorotation": 0.0, "isfrozen": 0.0, "firstinfront": 1.0, "emissionoffset": [0.0, 0.0, 0.0]}
    PDEFAULT = {"image": "", "lifetime": 1.0, "speed": 0.0, "angle": 0.0, "spin": 0.0, "zoom": 1.0, "red": 1.0, "green": 1.0, "blue": 1.0,
                "alpha": 1.0, "mode": 0.0, "rotation": 0.0, "stretchy": 0.0}

    def __init__(self):
        self.cfg = dict(self.PROPS); self.cfg["emissionoffset"] = [0.0, 0.0, 0.0]; self.pdef = dict(self.PDEFAULT)
        self.locals, self.globals, self.emits = [], [], []; self.particles = []; self.timer = 0.0; self.t = 0.0; self.origin = (0.0, 0.0)

    def running(self): return bool(self.pdef["image"]) and not self.cfg["isfrozen"]

    def add_modifier(self, scope, kind, start, end, attr, op, v1, v2):
        m = Mod(kind.lower(), float(start), float(end), attr, op, float(v1), float(v2))
        (self.globals if scope == "global" else self.emits if scope == "emit" else self.locals).append(m)

    def emit(self):
        n = int(self.cfg["nrofparticles"]); off = self.cfg["emissionoffset"] if isinstance(self.cfg["emissionoffset"], list) else [0, 0, 0]
        for _ in range(max(1, n)):
            if len(self.particles) >= min(MAX_PARTICLES, int(self.cfg["maxparticles"] or MAX_PARTICLES)): break
            p = dict(self.pdef); p.update(x=self.origin[0] + float(off[0] if len(off) > 0 else 0), y=self.origin[1] + float(off[1] if len(off) > 1 else 0), age=0.0)
            for m in self.locals:
                if m.kind == "once": m.apply(p, _rand(m.v1, m.v2))
            for m in self.emits: m.apply(p, _rand(m.v1, m.v2))
            self.particles.append(p)

    def update(self, dt, origin):
        dt = min(dt, 0.25); self.t += dt; self.origin = origin
        if self.running():
            self.timer -= dt
            while self.timer <= 0:
                self.emit(); self.timer += max(0.02, _rand(self.cfg["delaymin"], self.cfg["delaymax"]))
        for m in self.globals:
            if m.kind == "impulse":
                m.next = (m.next if m.next is not None else self.t + _rand(m.start, m.end))
                if self.t >= m.next:
                    for p in self.particles: m.apply(p, _rand(m.v1, m.v2))
                    m.next = self.t + max(0.02, _rand(m.start, m.end))
        keep = []
        for p in self.particles:
            p["age"] += dt
            if p["age"] >= p["lifetime"]: continue
            for m in self.locals:
                if m.kind == "range" and m.start <= p["age"] <= m.end:
                    f = (p["age"] - m.start) / (m.end - m.start) if m.end > m.start else 1.0
                    v = m.v1 + (m.v2 - m.v1) * f
                    if m.op == "replace": p[m.attr] = v
                    elif m.op == "add": p[m.attr] = p.get(m.attr, 0.0) + v * dt
                    elif m.op == "multiply": p[m.attr] = p.get(m.attr, 0.0) * (v ** dt if v > 0 else 0.0)
            p["rotation"] += p["spin"] * dt
            if self.cfg["autorotation"]: p["rotation"] = -p["angle"]
            p["x"] += math.cos(p["angle"]) * p["speed"] * dt; p["y"] -= math.sin(p["angle"]) * p["speed"] * dt
            keep.append(p)
        self.particles = keep
