import torch
import triton

print("torch", torch.__version__)
print("triton", triton.__version__)
print("cuda_available", torch.cuda.is_available())
print("cuda_count", torch.cuda.device_count() if torch.cuda.is_available() else 0)
if torch.cuda.is_available():
    print("cuda_name", torch.cuda.get_device_name(0))
