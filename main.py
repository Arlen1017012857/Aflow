from aflow import AflowManager


if __name__ == "__main__":
    aflow_manager = AflowManager(uri="bolt://localhost:7687", user="neo4j", password="12345678")
    aflow_manager.search_workflows("test")
