import argparse
import requests
from bs4 import BeautifulSoup
import psutil
import subprocess
import platform
import os
import math

# Quantization bpw values
QUANTIZATION_BPWS = {
    "fp8": 8.0,
    "q6_k_s": 6.6,
    "q5_k_s": 5.5,
    "q4_k_m": 4.8,
    "IQ4_XS": 4.3,
    "q3_k_m": 3.9,
    "IQ3_XS": 3.3,
    "IQ2_XS": 2.4
}

def get_memory_bandwidth():
    """Retrieves system RAM speed in GB/s."""
    try:
        if platform.system() == "Darwin":  # macOS
            # Use system_profiler to detect Apple Silicon model
            cmd = ["system_profiler", "SPHardwareDataType"]
            output = subprocess.check_output(cmd).decode().lower()
            
            # M4 series
            if 'm4 max' in output: return 546
            elif 'm4 pro' in output: return 273
            elif 'm4' in output: return 120
                
            # M3 series
            elif 'm3 max' in output: return 400
            elif 'm3 pro' in output: return 150
            elif 'm3' in output: return 100
                
            # M2 series
            elif 'm2 max' in output: return 400
            elif 'm2 pro' in output: return 200
            elif 'm2' in output: return 100
                
            # M1 series
            elif 'm1 ultra' in output: return 800
            elif 'm1 max' in output: return 400
            elif 'm1 pro' in output: return 200
            elif 'm1' in output: return 68.25
                
            return 48  # Default fallback for unknown models

        elif platform.system() == "Windows":
            cmd = ["powershell", "-Command", "Get-CimInstance Win32_PhysicalMemory | Select-Object -ExpandProperty Speed"]
            output = subprocess.check_output(cmd).decode().strip().split("\n")
            speeds = [int(s) for s in output if s.isdigit()]
            if speeds:
                max_speed = max(speeds)
                return max_speed * 8 * 2 / 1000  # Assuming DDR
            return 48 
            
        elif platform.system() == "Linux":
            try:
                cmd = ["sudo", "dmidecode", "-t", "memory"]
                output = subprocess.check_output(cmd).decode().split("\n")
                speeds = [int(line.split(":")[-1].strip().split(" ")[0]) 
                         for line in output if "Speed:" in line and "Unknown" not in line]
                if speeds:
                    max_speed = max(speeds)
                    return max_speed * 8 * 2 / 1000
            except:
                # Fallback to /proc/meminfo for basic detection
                with open('/proc/meminfo', 'r') as f:
                    mem_info = f.read()
                    if 'MemTotal' in mem_info:
                        total_gb = int(mem_info.split('MemTotal:')[1].split('kB')[0].strip()) / (1024 * 1024)
                        if total_gb >= 32:
                            return 64  # Assume decent RAM for 32GB+ systems
                        return 48  # Conservative estimate for smaller RAM
            return 48 
            
    except Exception as e:
        print(f"Error retrieving RAM speed: {e}")
        return 48 

def get_model_params(model_id):
    """Scrapes Hugging Face model page to extract model size in params."""
    url = f"https://huggingface.co/{model_id}"
    response = requests.get(url)
    if response.status_code != 200:
        print("Failed to fetch model page.")
        return None

    soup = BeautifulSoup(response.text, 'html.parser')
    param_divs = soup.find_all('div', class_='inline-flex h-6 shrink-0 items-center overflow-hidden rounded-lg border')

    for div in param_divs:
        if 'Model size' in div.text:
            size_text = div.find_all('div')[1].text.strip()
            return size_text

    return None

def convert_params_to_b(size_text):
    size_text = size_text.lower().replace('params', '').strip()
    if 'b' in size_text:
        return float(size_text.replace('b', '')) * 1e9  # Convert B to actual count
    elif 'm' in size_text:
        return float(size_text.replace('m', '')) * 1e6  # Convert M to actual count
    return None

def get_ram_specs():
    """Retrieves total RAM in GB."""
    return psutil.virtual_memory().total / 1e9  # Convert to GB

def get_vram_specs():
    """Retrieves VRAM size (GB) and bandwidth (GB/s)."""
    vram = None
    bandwidth = None
    
    if platform.system() == "Darwin":  # macOS
        try:
            cmd = ["system_profiler", "SPDisplaysDataType"]
            output = subprocess.check_output(cmd).decode().lower()
            
            # Check for Metal-capable GPU and estimate VRAM
            if 'metal' in output:
                total_ram = get_ram_specs()
                
                # M4 series detection
                if 'm4 max' in output:
                    vram = min(total_ram * 0.5, 128)  # Up to 128GB unified memory
                    bandwidth = 546
                elif 'm4 pro' in output:
                    vram = min(total_ram * 0.4, 72)
                    bandwidth = 273
                elif 'm4' in output:
                    vram = min(total_ram * 0.3, 24)
                    bandwidth = 120
                    
                # M3 series detection
                elif 'm3 max' in output:
                    vram = min(total_ram * 0.5, 128)
                    bandwidth = 400
                elif 'm3 pro' in output:
                    vram = min(total_ram * 0.4, 72)
                    bandwidth = 150
                elif 'm3' in output:
                    vram = min(total_ram * 0.3, 24)
                    bandwidth = 100
                    
                # M1/M2 series detection
                elif 'm2 max' in output or 'm1 max' in output:
                    vram = min(total_ram * 0.5, 96)
                    bandwidth = 800
                elif 'm2 pro' in output or 'm1 pro' in output:
                    vram = min(total_ram * 0.4, 32)
                    bandwidth = 400
                elif 'm2' in output or 'm1' in output:
                    vram = min(total_ram * 0.3, 24)
                    bandwidth = 200
                    
                # Legacy Mac GPUs
                elif 'radeon' in output or 'vega' in output:
                    vram = 8
                    bandwidth = 300
                elif 'intel' in output:
                    vram = 4
                    bandwidth = 100
            else:
                vram = 0
                bandwidth = 0
                
        except Exception as e:
            print(f"Error finding VRAM amount: {e}")
            vram = 0
            bandwidth = 0
            
    elif platform.system() == "Windows":
        try:
            # Check for NVIDIA GPU
            try:
                cmd = ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"]
                vram = float(subprocess.check_output(cmd).decode().strip()) / 1024
            except:
                pass
                    
            # Check for AMD GPU using PowerShell
            if not vram:
                cmd = ["powershell", "-Command", "Get-WmiObject Win32_VideoController | Select-Object AdapterRAM"]
                output = subprocess.check_output(cmd).decode().strip()
                for line in output.split('\n'):
                    if line.strip().isdigit():
                        vram = int(line.strip()) / (1024**3)
                        break
                            
            # Check for Intel GPU
            if not vram:
                cmd = ["powershell", "-Command", "Get-WmiObject Win32_VideoController | Select-Object Description"]
                output = subprocess.check_output(cmd).decode().lower()
                if 'intel' in output and 'arc' in output:
                    if 'a770' in output: vram = 16
                    elif 'b580' in output: vram = 12
                    elif 'b570' in output: vram = 10
                    elif 'a750' in output: vram = 8
                    elif 'a380' in output: vram = 6
                    elif 'a310' in output: vram = 4
        except:
            print("Error find VRAM amount")
            vram = 0
                        
    elif platform.system() == "Linux":
        try:
            try:
                cmd = ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"]
                vram = float(subprocess.check_output(cmd).decode().strip()) / 1024
            except:
                pass
                    
            if not vram:
                amd_vram_paths = [
                    "/sys/class/drm/card0/device/mem_info_vram_total",
                    "/sys/class/gpu/card0/device/mem_info_vram_total"
                ]
                for path in amd_vram_paths:
                    if os.path.exists(path):
                        with open(path, 'r') as f:
                            vram = int(f.read().strip()) / 1e9 
                            break
                                
            if not vram:
                cmd = ["lspci", "-v"]
                output = subprocess.check_output(cmd).decode().lower()
                if 'intel' in output and 'arc' in output:
                    if 'a770' in output: vram = 16
                    elif 'b580' in output: vram = 12
                    elif 'b570' in output: vram = 10
                    elif 'a750' in output: vram = 8
                    elif 'a380' in output: vram = 6
                    elif 'a310' in output: vram = 4
        except:
            print("Error find VRAM amount")
            vram = 0
    
    if vram:
        if vram >= 49: bandwidth = 1500
        elif vram >= 25: bandwidth = 1790
        elif vram >= 17: bandwidth = 950 
        elif vram >= 13: bandwidth = 550 
        elif vram >= 9: bandwidth = 400
        elif vram >= 7: bandwidth = 300
        elif vram >= 5: bandwidth = 240
        else: bandwidth = 200   
            
    return vram, bandwidth

def estimate_tks(ram_bandwidth, required_mem):
    """Estimates tk/s for a full RAM offload."""
    if platform.system() == "Darwin":
        return (ram_bandwidth / required_mem) * 0.3 # More accurate real-world performance for macOS
    else:
        return (ram_bandwidth / required_mem) * 0.9

def calculate_tks(base_tks, offload_ratio):
    if platform.system() == "Darwin":
        new_tks = base_tks * (0.02 * math.exp(3.0 * (100-offload_ratio)/100) + 0.3) # More accurate real-world performance for macOS
    else:
        new_tks = base_tks * (0.052 * math.exp(4.55 * (100-(offload_ratio))/100) + 1.06)
    return new_tks

def analyze_quantization(params_b, vram_gb, bandwidth, ram_gb, quant, bpw, ram_bandwidth):
    required_base = 1.0 + params_b * 0.05 / 1e9  # Overhead in GB
    required_mem = required_base + (params_b * bpw / 8 / 1e9)

    if required_mem <= vram_gb:
        if platform.system() == "Darwin":
            base_tks = (bandwidth / required_mem) * 0.3
        else:
            base_tks = (bandwidth / required_mem)
        return "All in VRAM", required_mem, 0, base_tks
    elif required_mem <= vram_gb + 1:
        if platform.system() == "Darwin":
            base_tks = (bandwidth / required_mem) * 0.2
        else:
            base_tks = (bandwidth / required_mem) * 0.9
        return "KV cache offload", required_mem, 0, base_tks
    elif vram_gb > 1 and required_mem <= (ram_gb + vram_gb):
        offload_ratio = (required_mem - vram_gb) / required_mem * 100
        base_tks = estimate_tks(ram_bandwidth, required_mem)
        return "Partial offload", required_mem, offload_ratio, calculate_tks(base_tks, offload_ratio)
    elif required_mem <= ram_gb:
        base_tks = estimate_tks(ram_bandwidth, required_mem)
        return "All in System RAM", required_mem, 100, base_tks
    else:
        return "Won't run", required_mem, 0, None

def analyze_all_quantizations(params_b, vram_gb, bandwidth, ram_gb, ram_bandwidth):
    results = {}
    for quant, bpw in QUANTIZATION_BPWS.items():
        run_type, mem_usage, offload_ratio, tks = analyze_quantization(params_b, vram_gb, bandwidth, ram_gb, quant, bpw, ram_bandwidth)
        results[quant] = {
            "run_type": run_type,
            "memory_required": mem_usage,
            "offload_percentage": offload_ratio,
            "tk/s": tks
        }
    return results

def parse_args():
    parser = argparse.ArgumentParser(description="Analyze Hugging Face model with quantization.")
    parser.add_argument("-b", "--bandwidth", type=float, help="Override bandwidth in GB/s.")
    parser.add_argument("-n", "--num-gpus", type=int, default=1, help="Number of GPUs.")
    parser.add_argument("-v", "--vram", type=int, help="Amount of VRAM in GB")
    return parser.parse_args()

if __name__ == "__main__":
    args = parse_args()

    model_id = input("Enter Hugging Face model ID (e.g., microsoft/phi-4): ")
    params_text = get_model_params(model_id)

    if params_text:
        params_b = convert_params_to_b(params_text)
        print(f"Model Parameters: {params_text} ({params_b / 1e9:.2f}B params)")
    else:
        print("Could not determine model parameters.")
        exit()

    total_ram = get_ram_specs()
    print(f"Total RAM: {total_ram:.2f} GB")

    vram, bandwidth = get_vram_specs()

    if args.vram:
        vram = args.vram

    if args.bandwidth:
        bandwidth = args.bandwidth

    if args.num_gpus > 1:
        vram *= args.num_gpus
        bandwidth = (bandwidth*args.num_gpus) * 0.42

    print(f"VRAM: {vram:.2f} GB, ~{bandwidth}GB/s")

    ram_bandwidth = get_memory_bandwidth()
    print(f"Estimated RAM Bandwidth: {ram_bandwidth:.2f} GB/s")

    print("\nAnalysis for each quantization level:")
    results = analyze_all_quantizations(params_b, vram, bandwidth, total_ram, ram_bandwidth)

    for quant, data in results.items():
        print(f"\n{quant.upper()}:")
        print(f"Run Type: {data['run_type']}")
        print(f"Memory Required: {data['memory_required']:.2f} GB")
        if data['offload_percentage'] > 0:
            print(f"GPU Offload Percentage: {100-data['offload_percentage']:.1f}%")
        if data['tk/s']:
            print(f"Estimated tk/s: {data['tk/s']:.2f}")
