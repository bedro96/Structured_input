"""
Console application demonstrating the full structured-input → MCP → Agent flow.

This script shows end-to-end usage:
  1. Creates an Azure AI Foundry agent backed by the local MCP server.
  2. Creates a conversation (thread).
  3. Sends two example structured-input payloads and prints the agent responses.
  4. Cleans up by deleting the agent version.

Prerequisites:
  - The MCP HTTP Streamable server must be running:
      uv run mcp-server
  - A valid .env file with Azure credentials (copy from .env.example).

Run:
    uv run console-app
  or
    uv run python -m src.console_app
"""

from __future__ import annotations

import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Verbose logging — always on, regardless of development stage
# ---------------------------------------------------------------------------
LOG_LEVEL = os.environ.get("LOG_LEVEL", "DEBUG").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    force=True,
)
logger = logging.getLogger(__name__)


def main() -> int:
    """Run the console demo and return an exit code."""
    logger.info("=" * 60)
    logger.info("Structured Input → MCP → Azure AI Foundry Agent Demo")
    logger.info("=" * 60)

    from src.agent.client import FoundryAgentClient  # noqa: PLC0415

    try:
        with FoundryAgentClient() as client:
            # ----------------------------------------------------------
            # Step 1 – Create agent
            # ----------------------------------------------------------
            logger.info("--- Step 1: Create agent ---")
            agent_meta = client.create_agent()
            logger.info("Agent ready: %s", agent_meta)

            # ----------------------------------------------------------
            # Step 2 – Create conversation
            # ----------------------------------------------------------
            logger.info("--- Step 2: Create conversation ---")
            conversation_id = client.create_conversation()

            # ----------------------------------------------------------
            # Step 3 – Send a customer-inquiry structured input
            # ----------------------------------------------------------
            logger.info("--- Step 3a: Customer inquiry ---")
            customer_inquiry = {
                "type": "customer_inquiry",
                "customer_id": "CUST-001",
                "inquiry_type": "billing",
                "message": "I was charged twice for my subscription this month.",
                "priority": "high",
                "metadata": {
                    "account_tier": "premium",
                    "region": "us-east-1",
                },
            }

            response1 = client.send_structured_input(conversation_id, customer_inquiry)
            print("\n" + "=" * 60)
            print("Agent Response (Customer Inquiry):")
            print("=" * 60)
            print(response1)
            print("=" * 60 + "\n")

            # ----------------------------------------------------------
            # Step 4 – Send a data-analysis structured input (multi-turn)
            # ----------------------------------------------------------
            logger.info("--- Step 3b: Data analysis ---")
            data_analysis = {
                "type": "data_analysis",
                "dataset_id": "DS-SALES-Q1-2026",
                "analysis_type": "trend",
                "parameters": {
                    "start_date": "2026-01-01",
                    "end_date": "2026-03-31",
                    "columns": "revenue,units_sold,region",
                },
            }

            response2 = client.send_structured_input(conversation_id, data_analysis)
            print("=" * 60)
            print("Agent Response (Data Analysis):")
            print("=" * 60)
            print(response2)
            print("=" * 60 + "\n")

            # ----------------------------------------------------------
            # Step 5 – Clean up
            # ----------------------------------------------------------
            logger.info("--- Step 4: Clean up ---")
            client.delete_agent()

        logger.info("Demo completed successfully.")
        return 0

    except EnvironmentError as exc:
        logger.error("Configuration error: %s", exc)
        return 1
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected error: %s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
