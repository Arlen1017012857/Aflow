import os
from dotenv import load_dotenv

def load_config():
    """Load configuration from .env file"""
    load_dotenv()
    
    return {
        # Neo4j configuration
        'neo4j': {
            'uri': os.getenv('NEO4J_URI', 'neo4j://localhost:7687'),
            'user': os.getenv('NEO4J_USER', 'neo4j'),
            'password': os.getenv('NEO4J_PASSWORD'),
            'database': os.getenv('NEO4J_DATABASE', 'neo4j')
        },
        # Embedder configuration
        'embedder': {
            'api_key': os.getenv('EMBEDDER_API_KEY', 'ollama'),
            'base_url': os.getenv('EMBEDDER_BASE_URL', 'https://api.openai.com/v1'),
            'model': os.getenv('EMBEDDER_MODEL', 'text-embedding-ada-002')
        }
    }
