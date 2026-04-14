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

import sys
import httpx
from dotenv import load_dotenv

load_dotenv(override=True)


def main() -> int:
    """Run the console demo and return an exit code."""
    print("\n" + "=" * 60)
    print("\nJSON input → AI Foundry Agent → MCP Demo")
    print("\nThis demo sends structured JSON input to an Azure AI Foundry agent that uses variables for MCP server input when making call." )
    print("=" * 60)
    print("\nStarting demo...")
    
    # ----------------------------------------------------------
    system_alert_message = {
        "json_input": {
            "user_prompt": "Notify the on-call engineer about incident INC7788 via email.",
            "recipient": "kunhoko@kakao.com",
            "subject": "Incident[ID: INC7788] Notification",
            "incidentId": "INC7788"
        },
    }
    print(f"\nSystem_alert_message is system_alert_message={system_alert_message}")
    
    response = httpx.post("http://localhost:8080/api/messages", json=system_alert_message, timeout=60.0)
    print(f"\nResponse status: {response.status_code}")
    if response.is_success:
        print(f"\nResponse from API: {response.json()}")

if __name__ == "__main__":
    sys.exit(main())
