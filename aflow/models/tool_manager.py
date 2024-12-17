from typing import Dict

class ToolManager:
    def __init__(self, neo4j_manager, retriever_manager):
        self.neo4j_manager = neo4j_manager
        self.retriever_manager = retriever_manager

    def create_tool(self, name: str, description: str, category: str = 'uncategorized') -> Dict:
        """Create a new tool or return existing one
        
        Args:
            name: Tool name
            description: Tool description
            category: Tool category
        """
        with self.neo4j_manager.get_session() as session:
            # Check if tool exists
            existing_tool = session.run("""
                MATCH (tool:Tool {name: $name})
                RETURN tool
                LIMIT 1
                """,
                name=name
            ).single()
            
            if existing_tool:
                return existing_tool["tool"]
            
            # Create embedding vector
            embedding = self.retriever_manager.embedder.embed_query(f"{name} {description}")
            
            # Create new tool
            result = session.run("""
                CREATE (tool:Tool {
                    name: $name,
                    description: $description,
                    category: $category,
                    embedding: $embedding
                })
                RETURN tool
                LIMIT 1
                """,
                name=name,
                description=description,
                category=category,
                embedding=embedding
            )
            
            record = result.single()
            return record["tool"] if record else None

    def update_tool(self, name: str, description: str = None, category: str = None) -> Dict:
        """Update existing tool properties
        
        Args:
            name: Tool name
            description: Tool description
            category: Tool category
        """
        with self.neo4j_manager.get_session() as session:
            # Check if tool exists
            exists = session.run("""
                MATCH (tool:Tool {name: $name})
                RETURN count(tool) > 0 as exists
                """,
                name=name
            ).single()["exists"]
            
            if not exists:
                raise ValueError(f"Tool '{name}' does not exist. Use create_tool to create new tools.")
            
            # Create new embedding vector
            embedding = self.retriever_manager.embedder.embed_query(f"{name} {description if description else ''}")
            
            # Update tool properties
            result = session.run("""
                MATCH (tool:Tool {name: $name})
                SET tool.embedding = $embedding
                SET tool.description = CASE WHEN $description IS NULL THEN tool.description ELSE $description END
                SET tool.category = CASE WHEN $category IS NULL THEN tool.category ELSE $category END
                RETURN tool
                LIMIT 1
                """,
                name=name,
                description=description,
                category=category,
                embedding=embedding
            )
            
            record = result.single()
            return record["tool"] if record else None
