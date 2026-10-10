import os

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    "YOUR_TELEGRAM_BOT_TOKEN"
)

OPENAI_BASE_URL = os.getenv(
    "OPENAI_BASE_URL",
    "https://integrate.api.nvidia.com/v1"
)

OPENAI_API_KEY = os.getenv(
    "OPENAI_API_KEY",
    "YOUR_NVIDIA_API_KEY"
)

MODEL_NAME = os.getenv(
    "MODEL_NAME",
    "nvidia/nemotron-3-super-120b-a12b"
)

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BIN_DIR = os.path.join(PROJECT_ROOT, "bin")

AX_BIN = os.path.join(BIN_DIR, "ax") if os.path.exists(os.path.join(BIN_DIR, "ax")) else "ax"
KUBECTL_ATE_BIN = os.path.join(BIN_DIR, "kubectl-ate") if os.path.exists(os.path.join(BIN_DIR, "kubectl-ate")) else "kubectl-ate"

SYNC_INTERVAL = int(os.getenv("SYNC_INTERVAL", "15"))
AGENT_LIBRARY_PATH = os.path.join(PROJECT_ROOT, "openclaw", "agent_library.json")
LOG_FILE = os.path.join(PROJECT_ROOT, "logs", "openclaw.log")
EGRESS_POLICY_PATH = os.path.join(PROJECT_ROOT, "manifests", "egress", "allow-all.yaml")
