import torch
import torch.nn as nn
import numpy as np

from envs import VecNormalize


# Get a render function
def get_render_func(venv):
    if hasattr(venv, 'envs'):
        return venv.envs[0].render
    elif hasattr(venv, 'venv'):
        return get_render_func(venv.venv)
    elif hasattr(venv, 'env'):
        return get_render_func(venv.env)

    return None


def get_vec_normalize(venv):
    if isinstance(venv, VecNormalize):
        return venv
    elif hasattr(venv, 'venv'):
        return get_vec_normalize(venv.venv)

    return None


# Necessary for my KFAC implementation.
class AddBias(nn.Module):
    def __init__(self, bias):
        super(AddBias, self).__init__()
        self._bias = nn.Parameter(bias.unsqueeze(1))

    def forward(self, x):
        if x.dim() == 2:
            bias = self._bias.t().view(1, -1)
        else:
            bias = self._bias.t().view(1, -1, 1, 1)

        return x + bias


def init(module, weight_init, bias_init, gain=1):
    weight_init(module.weight.data, gain=gain)
    bias_init(module.bias.data)
    return module


# https://github.com/openai/baselines/blob/master/baselines/common/tf_util.py#L87
def init_normc_(weight, gain=1):
    weight.normal_(0, 1)
    weight *= gain / torch.sqrt(weight.pow(2).sum(1, keepdim=True))

def tanh_g(x,g):
    x = x/g
    return torch.tanh(x)

def sigmoid(x):
    return 1.0/(1+np.exp(-x))

def update_mode(evaluations, masks, reward, value, next_value, tonic_g, phasic_g, g, threshold, sigmoid_g, sigmoid_range, natural_value):
    value = value.cpu()
    next_value = next_value.cpu()
    pd_error = reward-value+next_value
    evaluations = 0.75*evaluations + 0.25*pd_error
    evaluations = evaluations*masks
    if sigmoid_g:
        if not natural_value:
            evaluations_mode = (abs(evaluations)-threshold)*(sigmoid_range/threshold)
        else:
            evaluations_mode = (evaluations - threshold)*(sigmoid_range/threshold)
        evaluations_mode = sigmoid(evaluations_mode)
        g = tonic_g+evaluations_mode*(phasic_g-tonic_g)
    else:
        for i in range(g.shape[0]):
            if not natural_value:
                g[i][0] = phasic_g if abs(evaluations[i][0]) > threshold else tonic_g
            else:
                g[i][0] = phasic_g if evaluations[i][0] > threshold else tonic_g
    return evaluations, g, pd_error

# def update_mode_entropy(device, evaluations, masks, dist_entropy, tonic_g, phasic_g, g, threshold, sigmoid_g, sigmoid_range, natural_value):
#     evaluations = 0.75*evaluations + 0.25*dist_entropy
#     evaluations = evaluations*masks
#     if sigmoid_g:
#         evaluations_mode = (evaluations - threshold)*(sigmoid_range/threshold)
#         g = 2*(phasic_g-1)*sigmoid(evaluations_mode)-(phasic_g-2)
#         mask = (g < 1).to(torch.device('cpu'), dtype=torch.float32)
#         g = g*(1-mask) + 1/(1-g*mask)
#         g = torch.clamp(g, tonic_g, phasic_g)
#         # g = tonic_g+evaluations_mode*(phasic_g-tonic_g)
#     else:
#         for i in range(g.shape[0]):
#             g[i][0] = phasic_g if evaluations[i][0] > threshold else tonic_g
#     return evaluations, g

# def get_g_entropy(device, dist_entropy, threshold, min_g, max_g, phasic_g, sigmoid_g, sigmoid_range, flip_g, g):
#     if sigmoid_g:
#         threshold = threshold.to(device)
#         evaluations_mode = (dist_entropy - threshold)*(sigmoid_range/threshold)
#         g = (2*(phasic_g-1)*sigmoid(evaluations_mode)-(phasic_g-2)).to(device)
#         mask = (g < 1).to(torch.device(device), dtype=torch.float32)
#         g = g*(1-mask) + 1/(2-g*mask)
#         if flip_g:
#             g = 1.0/g
#         g = torch.clamp(g, min=min_g, max=max_g).unsqueeze(1)
#     else:
#         for i in range(g.shape[0]):
#             if flip_g:
#                 g[i][0] = phasic_g if dist_entropy[i][0] < threshold else max(1/phasic_g, min_g)
#             else:
#                 g[i][0] = phasic_g if dist_entropy[i][0] > threshold else max(1/phasic_g, min_g)
#     return  g

def get_g_entropy(dist_entropy, g):
    num_processes = dist_entropy.shape[0]
    exp_entropy =torch.exp(dist_entropy)
    g = (torch.exp(torch.sum(dist_entropy)/num_processes))/exp_entropy
    return g.unsqueeze(1)


def neuro_activity(obs, g, mid = 128):
    assert(obs.shape[0] == g.shape[0])
    for i in range(obs.shape[0]):
        obs[i] = (torch.tanh((obs[i]-mid)/g[i])+1)/2
    return obs

def obs_representation(obs, modulation, g_device, input_neuro):
    if modulation == 0:  # no modulation
        if input_neuro:
            obs = neuro_activity(obs, g_device)
        else:
            obs = obs/255
    elif modulation == 1:  # input modulation
        if input_neuro:
            obs = neuro_activity(obs, g_device)
        else:
            obs = obs/255
            obs = obs/g_device
    else:  # f1 modulation
        obs = obs/255
    return obs
