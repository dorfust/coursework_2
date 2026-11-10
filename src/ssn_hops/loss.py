"""Masked MSE + beta * unsquared Euclidean norm of all trainable parameters."""
import math
import torch


def masked_mse(prediction, target, mask):
    if prediction.shape != target.shape or prediction.shape != mask.shape:
        raise ValueError("prediction, target and mask must have identical shapes")
    if mask.dtype != torch.bool:
        raise ValueError("mask must be boolean")
    if not bool(mask.any()):
        raise ValueError("no reachable supervised pairs in this batch")
    # Index BEFORE subtraction: invalid target values cannot leak via inf * 0.
    selected_prediction, selected_target = prediction[mask], target[mask]
    if not bool(torch.isfinite(selected_prediction).all() and torch.isfinite(selected_target).all()):
        raise ValueError("supervised values must be finite")
    return (selected_prediction - selected_target).square().mean()


def parameter_l2(model):
    parts = [parameter.reshape(-1) for parameter in model.parameters() if parameter.requires_grad]
    if not parts:
        raise ValueError("regularization requires trainable parameters")
    return torch.linalg.vector_norm(torch.cat(parts), ord=2)


def hop_loss(prediction, target, mask, model, beta):
    if not math.isfinite(beta) or beta < 0:
        raise ValueError("beta must be finite and nonnegative")
    return masked_mse(prediction, target, mask) + beta * parameter_l2(model)
