"""Fixed-N all-pairs reconstruction. See R3_FEATURES.md, not author architecture."""
# Contents: GCNBranch (two GCNConv layers), HopRegressor (a low branch, a high branch and a dense
# predictor; output [n, n]) and predict_hops (inference wrapper). n is fixed at construction: the
# last Linear layer has n outputs, so the weights are tied to the node count and to the node-ID order.
import numpy as np
import torch
from torch import nn
from torch_geometric.nn import GCNConv
from .config import integer
from .graph import branch_inputs, validate_adjacency


# Two GCNConv layers (input_width -> width -> width) with a ReLU after each, so the outputs are
# non-negative. The GCNConv options are the ones listed in `args`; forward takes edge_index only
# (no edge weights). There is no dropout layer.
class GCNBranch(nn.Module):
    def __init__(self, input_width, width, bias):
        super().__init__()
        args = dict(improved=False, cached=False, add_self_loops=True,
                    normalize=True, bias=bias)
        self.first = GCNConv(input_width, width, **args)
        self.second = GCNConv(width, width, **args)

    def forward(self, features, edge_index):
        hidden = torch.relu(self.first(features, edge_index))
        return torch.relu(self.second(hidden, edge_index))


class HopRegressor(nn.Module):
    """S[d,v] estimates remaining hops, NOT delay-weighted path cost.

    Default (paper-faithful topology-only, features=adjacency_spliced_two_hop, or
    its legacy alias topology_only_ablation): low=[A] (width N), high=[A|Q] (width
    2N). OPTIONAL delay extension (not in the paper): low=[A|D] (2N), high=[A|Q|D]
    (3N). All modes propagate on original binary A with A+I normalization.
    Unshared branches, node-shared weights, N ID-specific output coordinates.
    """
    def __init__(self, n, config):
        super().__init__()
        integer(n, "model n", 2)
        config.validate()
        self.n = n
        self.config = config
        # Widths: see the class docstring ([A] and [A|Q]; delay mode adds N more columns for D).
        self.low_width = (2 if config.uses_delay else 1) * n
        self.high_width = (3 if config.uses_delay else 2) * n
        w = config.gcn_width
        self.low = GCNBranch(self.low_width, w, config.gcn_bias)
        self.high = GCNBranch(self.high_width, w, config.gcn_bias)
        self.predictor = nn.Sequential(
            nn.Linear(2 * w, config.dense_width, bias=config.dense_bias),
            nn.ReLU(),
            nn.Linear(config.dense_width, n, bias=config.dense_bias),
        )

    def forward(self, low, high, edge_index):
        """Return a float tensor of shape [n, n].

        Row i is computed from the embedding of node i and column j is output coordinate j.
        predict_hops describes its scores as [destination, candidate], so row = destination
        and column = candidate.

        Needs low of shape [n, low_width], high of shape [n, high_width] (both finite) and
        edge_index of dtype int64 and shape [2, E]; otherwise ValueError is raised.
        """
        if low.shape != (self.n, self.low_width) or high.shape != (self.n, self.high_width):
            raise ValueError("fixed-N branch feature shape mismatch")
        if not bool(torch.isfinite(low).all()) or not bool(torch.isfinite(high).all()):
            raise ValueError("branch features must be finite")
        if edge_index.ndim != 2 or edge_index.shape[0] != 2 or edge_index.dtype != torch.long:
            raise ValueError("edge_index must be int64 [2,E]")
        joined = torch.cat((self.low(low, edge_index), self.high(high, edge_index)), dim=1)
        return self.predictor(joined)


# Switches the model to eval mode for the call and restores the previous mode afterwards (in the
# finally block). Runs on the device of the first model parameter and returns a CPU NumPy copy.
@torch.no_grad()
def predict_hops(model, adjacency, ranges_km=None):
    """Finite [destination,candidate] scores.

    ranges_km (km) is REQUIRED only for the optional delay-extension mode; the
    paper-faithful topology-only modes ignore it (None is the intended call).
    Diagonal is exactly zero for inference only. No reachability oracle,
    neighbor/visited mask, symmetry constraint or clipping is applied.
    """
    array = validate_adjacency(adjacency)
    if array.shape != (model.n, model.n):
        raise ValueError("checkpoint requires the trained N and node ID ordering")
    was_training = model.training
    model.eval()
    try:
        device = next(model.parameters()).device
        inputs = branch_inputs(array, device, ranges_km=ranges_km, model_config=model.config)
        scores = model(*inputs).detach().cpu().numpy().copy()
        if not np.isfinite(scores).all():
            raise ValueError("non-finite inference scores")
        np.fill_diagonal(scores, 0.0)
        return scores
    finally:
        model.train(was_training)
