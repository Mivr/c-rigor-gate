"""Call-graph logic for `rigor structure`: cycles and reachability on plain dicts of key -> set of keys."""


def strongly_connected(graph):
    """Tarjan's algorithm, iterative (a deep chain of calls must not exhaust Python's stack).
    Returns the components, each a sorted list of keys, ordered by their first key."""
    index, low, on_stack, stack, result = {}, {}, set(), [], []
    counter = 0
    for root in sorted(graph):
        if root in index:
            continue
        work = [(root, iter(sorted(graph.get(root, ()))))]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)
        while work:
            node, neighbours = work[-1]
            advanced = False
            for nxt in neighbours:
                if nxt not in graph:
                    continue
                if nxt not in index:
                    index[nxt] = low[nxt] = counter
                    counter += 1
                    stack.append(nxt)
                    on_stack.add(nxt)
                    work.append((nxt, iter(sorted(graph.get(nxt, ())))))
                    advanced = True
                    break
                if nxt in on_stack:
                    low[node] = min(low[node], index[nxt])
            if advanced:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[node])
            if low[node] == index[node]:
                component = []
                while True:
                    top = stack.pop()
                    on_stack.discard(top)
                    component.append(top)
                    if top == node:
                        break
                result.append(sorted(component))
    return sorted(result)


def cycles(graph):
    """Components that really are cycles: more than one function, or one that calls itself."""
    return [c for c in strongly_connected(graph) if len(c) > 1 or c[0] in graph.get(c[0], ())]


def cycle_path(graph, members):
    """One concrete cycle through the smallest member, as a list that starts and ends with it."""
    inside = set(members)
    start = members[0]
    previous = {start: None}
    queue = [start]
    while queue:
        node = queue.pop(0)
        for nxt in sorted(graph.get(node, ())):
            if nxt not in inside:
                continue
            if nxt == start:
                return _assemble(previous, node, start)
            if nxt not in previous:
                previous[nxt] = node
                queue.append(nxt)
    return members + [members[0]]


def _assemble(previous, last, start):
    path = [last]
    while previous[path[-1]] is not None:
        path.append(previous[path[-1]])
    path.reverse()           # start ... last
    return path + [start]


def reaches(graph, source):
    """Every key reachable from `source` by direct calls, `source` included."""
    seen = {source}
    work = [source]
    while work:
        node = work.pop()
        for nxt in graph.get(node, ()):
            if nxt not in seen:
                seen.add(nxt)
                work.append(nxt)
    return seen
