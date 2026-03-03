from app.core.logger import setup_logging
from app.services.startup_service import StartupService
from app.core.local_agent_db import LocalAgentDB
from app.agent_lifecycle import PrinterAgent


def main():
    # 1. Start logging first so everything else can log properly
    setup_logging()

    # 2. Ensure all folders exist
    StartupService.initialize_environment()

    # 3. Initialize the database tables
    LocalAgentDB.initialize_schema()

    # 4. Start the main agent loop
    agent = PrinterAgent()
    agent.run()


if __name__ == "__main__":
    main()
