import sys
import os
import re
import argparse
from pathlib import Path

# Ensure paths work correctly whether running as a script or a PyInstaller frozen .exe
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).resolve().parent.parent
    
# Set BASE_DIR in environment so config.py can pick it up
os.environ["INKIFY_BASE_DIR"] = str(BASE_DIR)

from app.core.logger import setup_logging
from app.core.local_agent_db import LocalAgentDB
from app.agent_lifecycle import PrinterAgent
from app.services.startup_service import StartupService

def _extract_token_from_filename() -> str:
    """Extracts token if the executable is named like 'InkifySetup--inkify_reg_abc123.exe'"""
    try:
        filename = os.path.basename(sys.executable if getattr(sys, 'frozen', False) else sys.argv[0])
        match = re.search(r'--(inkify_reg_[a-zA-Z0-9_]+)', filename)
        if match:
            return match.group(1)
    except Exception as e:
        print(f"Failed to extract token from filename: {e}")
    return ""


def _run_pairing_loop(agent, token: str, *, pair_only: bool) -> bool:
    """
    Drives the interactive/non-interactive pairing handshake.
    Returns True if pairing succeeded, False otherwise.
    """
    while True:
        if not token:
            if pair_only and not sys.stdin.isatty():
                print("Error: No valid setup token found and no interactive terminal available.", file=sys.stderr)
                return False

            print("\nNo valid setup token found.")
            print("👉 Register or Login as Host. 👉 Go to the Inkify Dashboard 👉 Find Generate Token. 👉 Type or Copy-paste exact Token.")
            token = input("Paste your 24-hour setup token here: ").strip()

        print("\nAttempting to securely pair with Inkify Cloud...")
        success = agent.pairing_service.ensure_paired(token)
        
        if success:
            print("Agent successfully connected!")
            return True
        else:
            print("Pairing failed. The token is invalid or has expired.")
            token = ""  # Clear the variable so the loop asks the user
            
            if pair_only and not sys.stdin.isatty():
                print("Error: Pairing failed and no interactive terminal available.", file=sys.stderr)
                return False

            if pair_only:
                return False


def main():
    parser = argparse.ArgumentParser(
        description="Inkify Printer Agent", 
        formatter_class=argparse.RawDescriptionHelpFormatter, 
        epilog=(
            "  python main.py                                            # Run (must already be paired)\n"
            "  python main.py --token inkify_reg_abc123                  # Pair and run\n"
            "  python main.py --token inkify_reg_abc123 --pair-only      # Pair only (Used for Installers)\n"
        )
    )
    parser.add_argument("--token", type=str, help="Pre-provisioned registration token from the dashboard")
    parser.add_argument("--pair-only", action="store_true", help="Pair and exit immediately. Used by OS installers so they can start the service separately.")
    args = parser.parse_args()
    
    # 1. Ensure all folders exist BEFORE starting the logger!
    try:
        StartupService.initialize_environment()
    except Exception as e:
        print(f"Failed to initialize directories: {e}")
        sys.exit(1)
    
    # 2. Start logging first so everything else can log properly
    setup_logging()

    # 3. Initialize the database tables
    LocalAgentDB.initialize_schema()

    # 4. Start the main agent loop
    agent = PrinterAgent()
    
    # 5. Check if already permanently paired
    if agent.pairing_service.is_paired():
        if not args.pair_only:
            agent.run()
        sys.exit(0)
        
    # 6. Not paired — determine token source
    token = args.token or _extract_token_from_filename()

    # 7. Drive the pairing loop
    success = _run_pairing_loop(agent, token, pair_only=args.pair_only)

    if success:
        if args.pair_only:
            sys.exit(0) # Exit so the installer can finish
        print("Pairing complete! The background service will automatically start processing jobs.")
        agent.run() # Start the main event loop
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == "__main__":
    main()
