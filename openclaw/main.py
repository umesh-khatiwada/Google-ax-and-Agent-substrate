import os
import sys
import time
import signal
import logging
import threading
from openclaw import config
from openclaw.ax_client import AXClient
from openclaw.agent_library import AgentLibrary
from openclaw.agent_spawner import AgentSpawner
from openclaw.telegram_bot import TelegramBot

# Setup logging
os.makedirs(os.path.dirname(config.LOG_FILE), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(config.LOG_FILE)
    ]
)
logger = logging.getLogger("openclaw.main")

def main():
    logger.info("==================================================================")
    logger.info(" Starting OpenClaw Orchestrator for Google AX & Agent Substrate")
    logger.info("==================================================================")
    logger.info("Telegram Bot Token: %s...%s", config.TELEGRAM_BOT_TOKEN[:8], config.TELEGRAM_BOT_TOKEN[-6:])
    logger.info("AX Server: %s", os.environ.get("AX_SERVER", "auto-detect"))
    logger.info("Model Engine: %s", config.MODEL_NAME)
    logger.info("Sync Interval: %ds", config.SYNC_INTERVAL)

    # Initialize components
    ax_client = AXClient(
        ax_bin=config.AX_BIN,
        kubectl_ate_bin=config.KUBECTL_ATE_BIN,
        egress_policy_path=config.EGRESS_POLICY_PATH,
        ax_server_url=os.environ.get("AX_SERVER")
    )

    library = AgentLibrary(
        ax_client=ax_client,
        library_file=config.AGENT_LIBRARY_PATH,
        openai_base_url=config.OPENAI_BASE_URL,
        openai_api_key=config.OPENAI_API_KEY,
        model_name=config.MODEL_NAME
    )

    spawner = AgentSpawner(
        ax_client=ax_client,
        agent_library=library
    )

    bot = TelegramBot(
        bot_token=config.TELEGRAM_BOT_TOKEN,
        library=library,
        spawner=spawner,
        ax_client=ax_client
    )

    # Initial sync
    logger.info("Performing initial Agent Library sync from Google AX cluster...")
    init_changes = library.sync()
    logger.info("Initial sync complete. Registered agents: %d", len(library.list_agents()))

    running = True

    def stop_signal(signum, frame):
        nonlocal running
        logger.info("Received termination signal (%s). Shutting down OpenClaw gracefully...", signum)
        running = False

    signal.signal(signal.SIGINT, stop_signal)
    signal.signal(signal.SIGTERM, stop_signal)

    # Background Discovery & Library Sync Loop
    def sync_worker():
        while running:
            try:
                time.sleep(config.SYNC_INTERVAL)
                if not running:
                    break
                changes = library.sync()
                if changes["added"] or changes["updated"] or changes["removed"]:
                    logger.info("[Background Sync] Dynamic changes detected: %s", changes)
            except Exception as e:
                logger.error("Error in background sync worker: %s", e)

    sync_thread = threading.Thread(target=sync_worker, daemon=True, name="AX-Sync-Worker")
    sync_thread.start()
    logger.info("Started dynamic agent library sync thread (interval: %ds).", config.SYNC_INTERVAL)

    # Telegram Polling Loop
    logger.info("Connecting to Telegram Bot API (@openclawaxxbot)...")
    while running:
        try:
            bot.handle_updates()
        except Exception as e:
            logger.error("Error in Telegram polling loop: %s", e)
            time.sleep(2)

    logger.info("OpenClaw Orchestrator shutdown complete.")

if __name__ == "__main__":
    main()
