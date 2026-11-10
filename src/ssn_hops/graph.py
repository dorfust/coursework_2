"""Undirected binary graphs, exact labels and explicit feature reconstruction."""
from collections import deque
import numpy as np
import torch
from .config import ModelConfig
from .features import delay_features, validate_adjacency


def shortest_hops(adjacency, mask_diagonal=True):
    """Exact unweighted BFS from every node. -1 denotes unreachable, diagonal=0.

    Axes are [destination, candidate]; undirected labels are symmetric. The mask
    is finite/reachable pairs with diagonal optionally excluded, never sentinel loss.
    """
    array = validate_adjacency(adjacency)
    n = array.shape[0]
    result = np.full((n, n), -1, dtype=np.int32)
    neighbors = [np.flatnonzero(row).tolist() for row in array]
    for destination in range(n):
        result[destination, destination] = 0
        queue = deque([destination])
        while queue:
            node = queue.popleft()
            for neighbor in neighbors[node]:
                if result[destination, neighbor] == -1:
                    result[destination, neighbor] = result[destination, node] + 1
                    queue.append(neighbor)
    mask = result >= 0
    if mask_diagonal:
        np.fill_diagonal(mask, False)
    return result, mask


def exclusive_two_hop_mask(adjacency):
    """Boolean [N,N] mask of pairs that are two-hop-only: reachable through a common
    neighbour, NOT one-hop neighbours, diagonal False. Contains no 1/0.5 values."""
    array = validate_adjacency(adjacency)
    two_hop = (array.astype(np.int64) @ array.astype(np.int64)) > 0
    two_hop &= ~array
    np.fill_diagonal(two_hop, False)
    return two_hop


def preprocessed_structure(adjacency):
    """Paper Sec. III-B preprocessed input Q (reconstruction of its N x N layout).

    Returns float32 [N,N]: 1.0 for one-hop neighbours, 0.5 for two-hop-ONLY pairs,
    0.0 otherwise (incl. non-neighbours) and an exactly zero diagonal. A node that is
    both one-hop and two-hop keeps 1.0. Used as feature columns only; GCN propagation
    stays on the original binary A. (Formerly named exclusive_two_hop, which wrongly
    suggested a mask: see audit T021 F003.)
    """
    array = validate_adjacency(adjacency)
    two_hop = exclusive_two_hop_mask(array)
    return array.astype(np.float32) + 0.5 * two_hop.astype(np.float32)


# Thin backward-compatible alias. Despite its legacy name it returns the COMBINED
# structure Q (values 1/0.5/0), identical to preprocessed_structure; use
# exclusive_two_hop_mask for the actual boolean mask. Remove after tests migrate.
exclusive_two_hop = preprocessed_structure


def branch_inputs(adjacency, device="cpu", *, ranges_km=None, model_config=None):
    """Branch inputs by feature mode (default = paper-faithful topology-only).

    topology-only (default / legacy alias): low=[A] (N x N), high=[A|Q] (N x 2N);
    ranges_km is not used. delay extension (optional, not in the paper):
    low=[A|D], high=[A|Q|D] and ranges_km in km is REQUIRED.
    """
    config = model_config if model_config is not None else ModelConfig()
    config.validate()
    array = validate_adjacency(adjacency)
    a = torch.tensor(array.astype(np.float32), device=device)
    q = torch.tensor(preprocessed_structure(array), device=device)
    if config.uses_delay:
        if ranges_km is None:
            raise ValueError("delay mode requires ranges_km in km")
        d = torch.tensor(delay_features(array, ranges_km, config), device=device)
        low = torch.cat((a, d), dim=1)
        high = torch.cat((a, q, d), dim=1)
    else:
        low, high = a, torch.cat((a, q), dim=1)
    # Both directions of ORIGINAL binary A; no delay/two-hop propagation weights.
    edges = torch.tensor(np.stack(np.nonzero(array)), dtype=torch.long, device=device)
    return low, high, edges
