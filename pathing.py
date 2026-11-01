"""Path finding for server-commanded walking: A* on the 8-pixel lattice the client walks on (one step = 8 px = one 50 ms tick, axis moves only,
exactly what Session.step does), with the player's real collision test supplied by the caller."""
import heapq

STEP = 8

def find_path(blocked, start, goal, limit=40000, margin=640, cost=None, tcost=None):
    """start / goal: (x, y) px, multiples of 8, in one common frame. `blocked(x, y)` is the player's wall / NPC-shape test at that position.
    `cost(x, y)` (optional) is an extra price for stepping onto a position: a soft obstacle (another player) that is avoided when a reasonable
    detour exists but can still be crossed. Returns the list of positions after `start` up to and including `goal`, [] if already there,
    or None (goal blocked / unreachable / too far).
    `tcost(x, y, steps)` is the same idea with time: `steps` is how many steps it takes to get to (x, y) along the path being built, so a
    moving obstacle can be priced where it will be by then (the walker takes one step per 50 ms). Time is not part of the search state, so
    this is a heuristic, not an optimal space-time plan."""
    if start == goal: return []
    if blocked(*goal): return None
    x0, x1 = min(start[0], goal[0]) - margin, max(start[0], goal[0]) + margin
    y0, y1 = min(start[1], goal[1]) - margin, max(start[1], goal[1]) + margin
    h = lambda p: abs(p[0] - goal[0]) + abs(p[1] - goal[1])
    open_ = [(h(start), 0, start)]; g = {start: 0}; came = {}; tick = 0; seen = 0; st = {start: 0}
    while open_:
        _, _, cur = heapq.heappop(open_)
        if cur == goal:
            path = [cur]
            while path[-1] in came: path.append(came[path[-1]])
            path.pop(); path.reverse(); return path
        seen += 1
        if seen > limit: return None
        base = g[cur] + STEP
        for dx, dy in ((STEP, 0), (-STEP, 0), (0, STEP), (0, -STEP)):
            n = (cur[0] + dx, cur[1] + dy)
            if not (x0 <= n[0] <= x1 and y0 <= n[1] <= y1): continue
            k = st[cur] + 1; gc = base + (cost(*n) if cost else 0) + (tcost(n[0], n[1], k) if tcost else 0)
            if g.get(n, 1 << 60) <= gc or blocked(*n): continue
            g[n] = gc; st[n] = k; came[n] = cur; tick += 1; heapq.heappush(open_, (gc + h(n), tick, n))
    return None

def direction(a, b):
    """Walking key (U/D/L/R) for one lattice step from a to b."""
    if b[0] > a[0]: return "R"
    if b[0] < a[0]: return "L"
    return "D" if b[1] > a[1] else "U"

def nearest_free(blocked, pos, radius=48):
    """The closest free lattice position to `pos` (ring search, up to `radius` px), or None."""
    if not blocked(*pos): return pos
    for r in range(STEP, radius + 1, STEP):
        ring = [(pos[0] + dx, pos[1] + dy) for dx in range(-r, r + 1, STEP) for dy in (-r, r)] + [(pos[0] + dx, pos[1] + dy) for dy in range(-r + STEP, r, STEP) for dx in (-r, r)]
        for p in sorted(ring, key=lambda q: abs(q[0] - pos[0]) + abs(q[1] - pos[1])):
            if not blocked(*p): return p
    return None
