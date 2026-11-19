# -*- coding: utf-8 -*-
"""
Detection de la VRAM GPU via nvidia-smi (disponible sur tout Windows avec pilote NVIDIA).
Pas de dependance externe necessaire.
"""
import subprocess
import re


def get_gpu_info():
    """Retourne (vram_total_mb, gpu_name) ou (0, '') si non detecte."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total,name", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
        if result.returncode == 0 and result.stdout.strip():
            line = result.stdout.strip().split("\n")[0]
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 2:
                vram = int(parts[0])
                name = parts[1]
                return vram, name
    except Exception:
        pass
    return 0, ""


def vram_gb():
    vram, _ = get_gpu_info()
    return round(vram / 1024, 1) if vram else 0
