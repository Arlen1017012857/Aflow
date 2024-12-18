import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock
from aflow.models.tool_manager import ToolManager

class MockRecord:
    def __init__(self, data):
        self._data = data
        
    def __getitem__(self, key):
        return self._data[key]

class MockResult:
    def __init__(self, records):
        self._records = records
        self._current = 0
        
    def single(self):
        return self._records[0] if self._records else None
        
    def __iter__(self):
        return self
        
    def __next__(self):
        if self._current >= len(self._records):
            raise StopIteration
        record = self._records[self._current]
        self._current += 1
        return record

class MockSession:
    def __init__(self):
        self.transaction = MagicMock()
        self._tools = {}  # In-memory tool storage
        
    def __enter__(self):
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        pass
        
    def run(self, query, **kwargs):
        if "MATCH (tool:Tool {name: $name}) RETURN tool" in query:
            # Tool lookup
            name = kwargs.get("name")
            if name in self._tools:
                return MockResult([MockRecord({"tool": self._tools[name]})])
            return MockResult([])
            
        elif "MATCH (tool:Tool {name: $name}) RETURN count(tool)" in query:
            # Tool existence check
            name = kwargs.get("name")
            return MockResult([MockRecord({"exists": name in self._tools})])
            
        elif "CREATE (tool:Tool" in query:
            # Tool creation
            tool = {
                "name": kwargs.get("name"),
                "description": kwargs.get("description"),
                "category": kwargs.get("category"),
                "embedding": kwargs.get("embedding")
            }
            self._tools[tool["name"]] = tool
            return MockResult([MockRecord({"tool": tool})])
            
        elif "MATCH (tool:Tool {name: $name}) DELETE tool" in query:
            # Tool deletion
            name = kwargs.get("name")
            if name in self._tools:
                del self._tools[name]
            return MockResult([])
            
        elif "MATCH (tool:Tool)" in query and "gds.similarity.cosine" in query:
            # Tool search
            results = []
            for tool in self._tools.values():
                if kwargs.get("query", "").lower() in tool["description"].lower():
                    results.append(MockRecord({"tool": tool}))
            return MockResult(results[:kwargs.get("limit", 10)])
            
        return MockResult([])

class MockNeo4jManager:
    def __init__(self):
        self.session = MockSession()
        
    def get_session(self):
        return self.session

class MockRetrieverManager:
    def __init__(self):
        self.embedder = MagicMock()
        self.embedder.embed_query.return_value = [0.1] * 768  # Mock embedding vector

class TestToolManager(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory for test tools
        self.test_tools_dir = tempfile.mkdtemp()
        
        # Initialize managers
        self.neo4j_manager = MockNeo4jManager()
        self.retriever_manager = MockRetrieverManager()
        
        # Initialize ToolManager
        self.tool_manager = ToolManager(
            neo4j_manager=self.neo4j_manager,
            retriever_manager=self.retriever_manager,
            tools_dir=self.test_tools_dir
        )
        
    def tearDown(self):
        # Clean up test directory
        shutil.rmtree(self.test_tools_dir)
        self.tool_manager.cleanup()
        
    def test_create_tool(self):
        """Test creating a new tool"""
        # Create a test tool file
        category = "test_category"
        tool_name = "TestTool"
        tool_content = '''
class TestTool:
    """A test tool for testing purposes"""
    def execute(self):
        return "Test tool executed"
'''
        category_dir = os.path.join(self.test_tools_dir, category)
        os.makedirs(category_dir, exist_ok=True)
        tool_path = os.path.join(category_dir, f"{tool_name}.py")
        
        with open(tool_path, 'w') as f:
            f.write(tool_content)
            
        # Wait for tool manager to process the file
        self.tool_manager.scan_tools()
        
        # Verify tool was created in database
        with self.neo4j_manager.get_session() as session:
            result = session.run("""
                MATCH (tool:Tool {name: $name})
                RETURN tool
                """,
                name=tool_name
            ).single()
            
            self.assertIsNotNone(result)
            tool = result["tool"]
            self.assertEqual(tool["name"], tool_name)
            self.assertEqual(tool["category"], category)
            self.assertIn("test tool", tool["description"].lower())
            
    def test_update_tool(self):
        """Test updating an existing tool"""
        # Create initial tool
        category = "test_category"
        tool_name = "UpdateTool"
        initial_content = '''
class UpdateTool:
    """Initial description"""
    def execute(self):
        return "Initial version"
'''
        category_dir = os.path.join(self.test_tools_dir, category)
        os.makedirs(category_dir, exist_ok=True)
        tool_path = os.path.join(category_dir, f"{tool_name}.py")
        
        with open(tool_path, 'w') as f:
            f.write(initial_content)
            
        self.tool_manager.scan_tools()
        
        # Update tool content
        updated_content = '''
class UpdateTool:
    """Updated description"""
    def execute(self):
        return "Updated version"
'''
        with open(tool_path, 'w') as f:
            f.write(updated_content)
            
        self.tool_manager.scan_tools()
        
        # Verify tool was updated
        with self.neo4j_manager.get_session() as session:
            result = session.run("""
                MATCH (tool:Tool {name: $name})
                RETURN tool
                """,
                name=tool_name
            ).single()
            
            self.assertIsNotNone(result)
            tool = result["tool"]
            self.assertEqual(tool["name"], tool_name)
            self.assertEqual(tool["category"], category)
            self.assertIn("updated description", tool["description"].lower())
            
    def test_delete_tool(self):
        """Test deleting a tool"""
        # Create a tool
        category = "test_category"
        tool_name = "DeleteTool"
        tool_content = '''
class DeleteTool:
    """A tool to be deleted"""
    def execute(self):
        return "Will be deleted"
'''
        category_dir = os.path.join(self.test_tools_dir, category)
        os.makedirs(category_dir, exist_ok=True)
        tool_path = os.path.join(category_dir, f"{tool_name}.py")
        
        with open(tool_path, 'w') as f:
            f.write(tool_content)
            
        self.tool_manager.scan_tools()
        
        # Delete the tool file
        os.remove(tool_path)
        self.tool_manager.scan_tools()
        
        # Verify tool was deleted from database
        with self.neo4j_manager.get_session() as session:
            result = session.run("""
                MATCH (tool:Tool {name: $name})
                RETURN count(tool) as count
                """,
                name=tool_name
            ).single()
            
            self.assertEqual(result["count"], 0)
            
    def test_search_tools(self):
        """Test searching for tools"""
        # Create multiple tools
        tools = [
            ("SearchTool1", "A tool for searching text"),
            ("SearchTool2", "A tool for searching images"),
            ("OtherTool", "A different kind of tool")
        ]
        
        category = "test_category"
        category_dir = os.path.join(self.test_tools_dir, category)
        os.makedirs(category_dir, exist_ok=True)
        
        for tool_name, description in tools:
            tool_content = f'''
class {tool_name}:
    """{description}"""
    def execute(self):
        return "Test execution"
'''
            tool_path = os.path.join(category_dir, f"{tool_name}.py")
            with open(tool_path, 'w') as f:
                f.write(tool_content)
                
        self.tool_manager.scan_tools()
        
        # Search for tools
        results = self.tool_manager.search_tools("search", limit=2)
        
        # Verify search results
        self.assertEqual(len(results), 2)
        result_names = {tool["name"] for tool in results}
        self.assertTrue("SearchTool1" in result_names)
        self.assertTrue("SearchTool2" in result_names)
        
if __name__ == '__main__':
    unittest.main()
