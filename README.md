# Project Title
Aflow

# Description
Aflow is a Python-based tool management and workflow automation system that integrates with Neo4j for data management and retrieval. It allows users to create, update, and manage tools, tasks, and workflows efficiently.

## Features
- Manage tools and their properties.
- Create and execute tasks associated with specific tools.
- Define and run workflows that consist of multiple tasks.
- Hybrid search capabilities for tools, tasks, and workflows.
- **Function-Level Code Change Detection**: Automatically detects code changes at the function level and synchronizes the database accordingly.
- **Dynamic Tool Import and Parameter Capture**: When executing tasks, tools are dynamically imported, and the necessary parameters are automatically captured for execution.

# Technical Architecture and Implementation

The Aflow project is built using a modular architecture that leverages various components to manage tools, tasks, and workflows effectively. The key components include:

1. **AflowManager**: The central management class that orchestrates interactions between different components, including tool management, task execution, and workflow orchestration. It initializes necessary managers for database connections and retrieval.

2. **Database Integration**: Utilizes Neo4j as the underlying database, enabling efficient storage and retrieval of tools, tasks, and workflows. The integration is facilitated through the `Neo4jManager`, which handles all database operations.

3. **Dynamic Tool Management**: Tools are dynamically imported and managed, allowing for flexible execution of tasks based on user requirements. This includes automatic detection of code changes and synchronization with the database.

4. **Workflow Automation**: Supports the creation and execution of complex workflows that consist of multiple interconnected tasks, enhancing productivity and automation.

5. **Hybrid Search Capabilities**: Implements advanced search functionalities that allow users to retrieve tools, tasks, and workflows using hybrid retrieval methods, improving the overall user experience.

# Installation
1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd Aflow
   ```
2. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Set up your environment variables in a `.env` file based on the provided `.env.example`.

# Usage
To run the application, execute:
```bash
python main.py
```

# Dependencies
- `python-dotenv`
- `neo4j`
- `neo4j-graphrag`
- `openai`
- `requests`
- `watchdog`

# Contributing
Contributions are welcome! Please submit a pull request or open an issue to discuss changes.

# License
This project is licensed under the MIT License.
