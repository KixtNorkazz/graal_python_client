"""Scheduling of GS2 coroutines: `Wait` (what waitfor() yields) and `GenRunner`, the object the task lists hold.
The runtimes (weapons.WeaponRunner, npcrt.NpcRuntime) keep `(due_time, gen)` tuples and call `next(gen)`; GenRunner makes that work for
generators that yield either a delay in seconds or a Wait: for a Wait it returns the timeout as the delay and registers itself with the GUI
event registry, so an event (a button click) can wake it early; the value sent back into the script is 1 (event) or 0 (timeout)."""

NO_TIMEOUT = 86400.0

class Wait:
    def __init__(self, target, event, timeout):
        self.target, self.event, self.timeout = target.lower(), event.lower(), timeout; self.fired = False; self.runner = None

class GenRunner:
    def __init__(self, gen, owner, session):
        self.gen, self.owner, self.s = gen, owner, session; self.waiting = None

    def __iter__(self): return self

    def __next__(self):
        send = None
        if self.waiting is not None:
            w = self.waiting; self.waiting = None; self.s.gui.unwait(w); send = 1.0 if w.fired else 0.0
        d = self.gen.send(send)
        if isinstance(d, Wait):
            self.waiting = d; d.runner = self; self.s.gui.waiters.append(d)
            return d.timeout if d.timeout and d.timeout > 0 else NO_TIMEOUT
        return d

    def wake(self):
        """An awaited event happened: run at the next tick instead of at the timeout."""
        o = self.owner
        o.tasks = [((0.0 if e[1] is self else e[0]), e[1]) for e in o.tasks]
