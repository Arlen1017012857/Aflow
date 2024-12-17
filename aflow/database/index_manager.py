class IndexManager:
    def __init__(self, neo4j_manager):
        self.neo4j_manager = neo4j_manager

    def init_indexes(self):
        """Initialize database indexes"""
        with self.neo4j_manager.get_session() as session:
            # Create vector indexes
            session.run("""
                CREATE VECTOR INDEX workflowEmbedding IF NOT EXISTS
                FOR (w:Workflow) ON (w.embedding)
                OPTIONS {indexConfig: {
                    `vector.dimensions`: 1536,
                    `vector.similarity_function`: 'cosine'
                }}
            """)
            session.run("""
                CREATE VECTOR INDEX taskEmbedding IF NOT EXISTS
                FOR (t:Task) ON (t.embedding)
                OPTIONS {indexConfig: {
                    `vector.dimensions`: 1536,
                    `vector.similarity_function`: 'cosine'
                }}
            """)
            session.run("""
                CREATE VECTOR INDEX toolEmbedding IF NOT EXISTS
                FOR (t:Tool) ON (t.embedding)
                OPTIONS {indexConfig: {
                    `vector.dimensions`: 1536,
                    `vector.similarity_function`: 'cosine'
                }}
            """)
            
            # Create fulltext indexes
            session.run("""
                CREATE FULLTEXT INDEX workflowFulltext IF NOT EXISTS
                FOR (w:Workflow) ON EACH [w.name, w.description]
            """)
            session.run("""
                CREATE FULLTEXT INDEX taskFulltext IF NOT EXISTS
                FOR (t:Task) ON EACH [t.name, t.description]
            """)
            session.run("""
                CREATE FULLTEXT INDEX toolFulltext IF NOT EXISTS
                FOR (t:Tool) ON EACH [t.name, t.description]
            """)
