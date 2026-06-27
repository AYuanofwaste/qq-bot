import sys
import os

import torch
from transformers import ClapModel, ClapProcessor

from config import config

_EMOTIONAL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "emotional", "clap-htsat-fused")
models = dict()
processor = ClapProcessor.from_pretrained(_EMOTIONAL_DIR, local_files_only=True)


def get_clap_audio_feature(audio_data, device=config.bert_gen_config.device):
    if (
        sys.platform == "darwin"
        and torch.backends.mps.is_available()
        and device == "cpu"
    ):
        device = "mps"
    if not device:
        device = "cuda"
    if device not in models.keys():
        models[device] = ClapModel.from_pretrained(_EMOTIONAL_DIR, local_files_only=True).to(
            device
        )
    with torch.no_grad():
        inputs = processor(
            audios=audio_data, return_tensors="pt", sampling_rate=48000
        ).to(device)
        emb = models[device].get_audio_features(**inputs)
    return emb.T


def get_clap_text_feature(text, device=config.bert_gen_config.device):
    if (
        sys.platform == "darwin"
        and torch.backends.mps.is_available()
        and device == "cpu"
    ):
        device = "mps"
    if not device:
        device = "cuda"
    if device not in models.keys():
        models[device] = ClapModel.from_pretrained(_EMOTIONAL_DIR, local_files_only=True).to(
            device
        )
    with torch.no_grad():
        inputs = processor(text=text, return_tensors="pt").to(device)
        emb = models[device].get_text_features(**inputs)
    return emb.T
