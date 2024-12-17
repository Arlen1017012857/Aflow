import os
from neo4j import GraphDatabase

class Neo4jManager:
    def __init__(self, uri: str = None, user: str = None, password: str = None, database: str = "neo4j"):
        """Initialize Neo4j database connection manager"""
        uri = uri or os.getenv("NEO4J_URI", "neo4j://localhost:7687")
        user = user or os.getenv("NEO4J_USER", "neo4j")
        password = password or os.getenv("NEO4J_PASSWORD")
        
        if not password:
            raise ValueError("Neo4j password must be provided either through constructor or NEO4J_PASSWORD environment variable")
            
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self.database = database

    def get_session(self):
        """Get a new database session"""
        return self.driver.session(database=self.database)

    def close(self):
        """Close the database connection"""
        self.driver.close()
