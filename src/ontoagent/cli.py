"""Interactive terminal CLI for OntoAgent.

Purpose:
    Enables interactive chat sessions directly from the terminal.
    Maintains thread persistence and demonstrates full orchestration turns.
"""

import asyncio
import sys
import uuid
from langchain_core.messages import HumanMessage
from ontoagent.graph.builder import build_graph


async def run_cli() -> None:
    """Run interactive terminal session."""
    print("=" * 65)
    print(" OntoAgent Operations Copilot - Terminal CLI")
    print("=" * 65)
    print("Type 'exit' or 'quit' to end session.")
    print("Type '/role ops_manager' or '/role analyst' to switch persona.\n")

    current_role = "ops_manager"
    thread_id = str(uuid.uuid4())[:8]
    graph = build_graph()

    print(f"Active Role: {current_role} | Thread ID: {thread_id}\n")

    while True:
        try:
            user_input = input(f"[{current_role}] > ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting CLI.")
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit"):
            print("Session ended.")
            break

        if user_input.startswith("/role"):
            parts = user_input.split()
            if len(parts) > 1 and parts[1] in ("analyst", "ops_manager"):
                current_role = parts[1]
                print(f"Switched role to: {current_role}\n")
            else:
                print("Usage: /role [analyst|ops_manager]\n")
            continue

        print("\nThinking...")
        config = {"configurable": {"thread_id": thread_id}}
        input_state = {
            "messages": [HumanMessage(content=user_input)],
            "user_role": current_role,
            "actor_id": "cli_user",
        }

        try:
            output_state = await graph.ainvoke(input_state, config=config)
            answer = output_state.get("final_text") or output_state.get("answer") or "No response generated."
            citations = output_state.get("citations", [])

            print("\n" + "-" * 60)
            print(answer)
            if citations:
                print("\nCitations: " + ", ".join(citations))
            print("-" * 60 + "\n")
        except Exception as e:
            print(f"\n[Error executing turn: {str(e)}]\n")


def main() -> None:
    asyncio.run(run_cli())


if __name__ == "__main__":
    main()
