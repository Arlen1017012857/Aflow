import os
import json
import hashlib
from typing import Dict, List, Optional, Set
from dataclasses import dataclass
import ast

@dataclass
class MerkleNode:
    """Merkle树节点，用于表示文件、目录或函数
    
    Attributes:
        hash: 节点的哈希值
        path: 节点的路径（对于函数，是文件路径加函数名）
        children: 子节点字典，key为名称，value为MerkleNode
        is_file: 是否为文件
        is_function: 是否为函数
        content_hash: 内容的哈希值
        function_name: 函数名（仅对函数节点有效）
        function_doc: 函数文档（仅对函数节点有效）
    """
    hash: str
    path: str
    children: Dict[str, 'MerkleNode']
    is_file: bool
    is_function: bool = False
    content_hash: Optional[str] = None
    function_name: Optional[str] = None
    function_doc: Optional[str] = None

class MerkleTree:
    def __init__(self, root_dir: str):
        """初始化Merkle Tree
        
        Args:
            root_dir: 根目录路径
        """
        self.root_dir = root_dir
        self.root = self._build_tree(root_dir)
        self.previous_root = None
        self.changed_functions = {}  # 记录每个文件中发生变化的函数
    
    def _calculate_file_hash(self, file_path: str) -> str:
        """计算文件的SHA-256哈希值
        
        Args:
            file_path: 文件路径
            
        Returns:
            str: 文件的SHA-256哈希值
        """
        sha256_hash = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                for byte_block in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(byte_block)
            return sha256_hash.hexdigest()
        except Exception as e:
            print(f"Error calculating hash for {file_path}: {e}")
            return ""

    def _calculate_function_hash(self, source: str) -> str:
        """计算函数代码的哈希值
        
        Args:
            source: 函数的源代码
            
        Returns:
            str: 函数代码的SHA-256哈希值
        """
        return hashlib.sha256(source.encode()).hexdigest()

    def _extract_functions(self, file_path: str) -> List[MerkleNode]:
        """从Python文件中提取函数节点
        
        Args:
            file_path: Python文件路径
            
        Returns:
            List[MerkleNode]: 函数节点列表
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                tree = ast.parse(content)

            functions = []
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    if node.name.startswith('_'):
                        continue
                        
                    # 获取函数源代码
                    func_source = ast.get_source_segment(content, node)
                    if not func_source:
                        continue

                    # 计算函数哈希值
                    func_hash = self._calculate_function_hash(func_source)
                    
                    # 获取函数文档
                    func_doc = ast.get_docstring(node)
                    
                    # 创建函数节点
                    func_node = MerkleNode(
                        hash=func_hash,
                        path=f"{file_path}::{node.name}",
                        children={},
                        is_file=False,
                        is_function=True,
                        content_hash=func_hash,
                        function_name=node.name,
                        function_doc=func_doc
                    )
                    functions.append(func_node)
            
            return functions
        except Exception as e:
            print(f"Error extracting functions from {file_path}: {e}")
            return []

    def _build_tree(self, path: str) -> MerkleNode:
        """递归构建目录的Merkle树
        
        Args:
            path: 当前处理的路径
            
        Returns:
            MerkleNode: 构建的Merkle树节点
        """
        print(f"Building tree for path: {path}")
        children = {}
        is_file = os.path.isfile(path)
        content_hash = None
        
        if is_file and path.endswith('.py'):
            content_hash = self._calculate_file_hash(path)
            # 对Python文件，提取函数并作为子节点
            function_nodes = self._extract_functions(path)
            for func_node in function_nodes:
                children[func_node.function_name] = func_node
            # 文件节点的哈希值包含所有函数节点的哈希
            child_hashes = sorted(child.hash for child in children.values())
            hash_value = hashlib.sha256(
                (content_hash + ''.join(child_hashes)).encode()
            ).hexdigest()
        elif is_file:
            content_hash = self._calculate_file_hash(path)
            hash_value = content_hash
        else:
            # Process directory
            try:
                for name in os.listdir(path):
                    if name.startswith('.') or name == '__pycache__':
                        continue
                    child_path = os.path.join(path, name)
                    children[name] = self._build_tree(child_path)
            except Exception as e:
                print(f"Error processing directory {path}: {e}")
            
            # Calculate directory hash from children
            child_hashes = sorted(child.hash for child in children.values())
            hash_value = hashlib.sha256(''.join(child_hashes).encode()).hexdigest()
        
        return MerkleNode(
            hash=hash_value,
            path=path,
            children=children,
            is_file=is_file,
            content_hash=content_hash
        )

    def get_changes(self) -> Dict[str, Set[str]]:
        """获取自上次更新以来的文件变化
        
        Returns:
            Dict[str, Set[str]]: 包含added、modified和removed三个键的字典，
                                值为对应的文件路径集合
        """
        if not self.previous_root:
            return {
                'added': {node.path for node in self._get_all_files(self.root)},
                'modified': set(),
                'removed': set()
            }
        
        added = set()
        modified = set()
        removed = set()
        
        self._compare_nodes(self.root, self.previous_root, added, modified, removed)
        
        return {
            'added': {path for path in added if path.endswith('.py')},
            'modified': {path for path in modified if path.endswith('.py')},
            'removed': {path for path in removed if path.endswith('.py')}
        }

    def _compare_nodes(self, node1: Optional[MerkleNode], node2: Optional[MerkleNode], 
                      added: Set[str], modified: Set[str], removed: Set[str]):
        """递归比较两个节点并收集变化
        
        Args:
            node1: 当前树的节点
            node2: 上一个树的节点
            added: 新增文件的集合
            modified: 修改文件的集合
            removed: 删除文件的集合
        """
        if not node1 and not node2:
            return
            
        if not node2:  # 新增
            if node1.is_file:
                added.add(node1.path)
            elif node1.is_function:
                # 新增函数时，将其父文件标记为修改
                parent_path = node1.path.split('::')[0]
                modified.add(parent_path)
            else:
                for child in node1.children.values():
                    self._compare_nodes(child, None, added, modified, removed)
            return
            
        if not node1:  # 删除
            if node2.is_file:
                removed.add(node2.path)
            elif node2.is_function:
                # 删除函数时，将其父文件标记为修改
                parent_path = node2.path.split('::')[0]
                modified.add(parent_path)
            else:
                for child in node2.children.values():
                    self._compare_nodes(None, child, added, modified, removed)
            return
        
        # 比较两个节点
        if node1.is_file and node2.is_file:
            if node1.hash != node2.hash:
                modified.add(node1.path)
            # 如果是Python文件，比较函数节点
            if node1.path.endswith('.py'):
                self._compare_function_nodes(node1, node2, modified)
        else:
            # 比较目录内容
            all_children = set(node1.children.keys()) | set(node2.children.keys())
            for child_name in all_children:
                child1 = node1.children.get(child_name)
                child2 = node2.children.get(child_name)
                self._compare_nodes(child1, child2, added, modified, removed)
    
    def _compare_function_nodes(self, file_node1: MerkleNode, file_node2: MerkleNode, modified: Set[str]):
        """比较两个文件节点中的函数节点
        
        Args:
            file_node1: 当前文件节点
            file_node2: 上一个文件节点
            modified: 修改文件的集合
        """
        # 获取两个文件中的所有函数名
        funcs1 = {name: node for name, node in file_node1.children.items() if node.is_function}
        funcs2 = {name: node for name, node in file_node2.children.items() if node.is_function}
        
        # 检查函数变化
        all_funcs = set(funcs1.keys()) | set(funcs2.keys())
        changed_funcs = set()
        
        for func_name in all_funcs:
            func1 = funcs1.get(func_name)
            func2 = funcs2.get(func_name)
            
            if not func2:  # 新增函数
                print(f"New function added: {func_name}")
                changed_funcs.add(func_name)
                modified.add(file_node1.path)
            elif not func1:  # 删除函数
                print(f"Function removed: {func_name}")
                changed_funcs.add(func_name)
                modified.add(file_node2.path)
            elif func1.hash != func2.hash:  # 函数修改
                print(f"Function modified: {func_name}")
                changed_funcs.add(func_name)
                modified.add(file_node1.path)
        
        # 记录文件中发生变化的函数
        if changed_funcs:
            self.changed_functions[file_node1.path] = changed_funcs

    def update(self) -> Dict[str, Set[str]]:
        """更新树并返回变化的文件
        
        Returns:
            Dict[str, Set[str]]: 文件变化信息
        """
        print("Updating Merkle tree...")
        # Store previous root
        self.previous_root = self.root
        
        # Reset changed functions
        self.changed_functions = {}
        
        # Rebuild tree
        print(f"Building new tree from {self.root_dir}")
        self.root = self._build_tree(self.root_dir)
        
        # Get changes
        added = set()
        modified = set()
        removed = set()
        
        print("Comparing old and new trees...")
        self._compare_nodes(self.root, self.previous_root, added, modified, removed)
        
        return {
            'added': {path for path in added if path.endswith('.py')},
            'modified': {path for path in modified if path.endswith('.py')},
            'removed': {path for path in removed if path.endswith('.py')}
        }

    def _get_all_files(self, node: MerkleNode) -> List[MerkleNode]:
        """获取节点下的所有文件节点
        
        Args:
            node: 起始节点
            
        Returns:
            List[MerkleNode]: 文件节点列表
        """
        if node.is_file:
            return [node]
            
        files = []
        for child in node.children.values():
            files.extend(self._get_all_files(child))
        return files

    def get_state(self) -> dict:
        """获取当前状态
        
        Returns:
            dict: 包含当前状态的字典
        """
        def node_to_dict(node: MerkleNode) -> dict:
            return {
                'hash': node.hash,
                'path': node.path,
                'children': {name: node_to_dict(child) for name, child in node.children.items()},
                'is_file': node.is_file,
                'content_hash': node.content_hash,
                'is_function': node.is_function,
                'function_name': node.function_name,
                'function_doc': node.function_doc
            }
        
        return {
            'root_dir': self.root_dir,
            'root': node_to_dict(self.root) if self.root else None,
            'previous_root': node_to_dict(self.previous_root) if self.previous_root else None
        }
    
    def load_state(self, state: dict):
        """从状态字典加载
        
        Args:
            state: 状态字典
        """
        def dict_to_node(data: dict) -> MerkleNode:
            return MerkleNode(
                hash=data['hash'],
                path=data['path'],
                children={name: dict_to_node(child) for name, child in data['children'].items()},
                is_file=data['is_file'],
                content_hash=data['content_hash'],
                is_function=data.get('is_function', False),
                function_name=data.get('function_name'),
                function_doc=data.get('function_doc')
            )
        
        self.root_dir = state['root_dir']
        self.root = dict_to_node(state['root']) if state['root'] else None
        self.previous_root = dict_to_node(state['previous_root']) if state['previous_root'] else None

    def visualize(self, node: Optional[MerkleNode] = None, indent: str = "", is_last: bool = True) -> None:
        """在终端中可视化显示Merkle树结构
        
        Args:
            node: 要显示的节点，默认为根节点
            indent: 当前缩进
            is_last: 是否是父节点的最后一个子节点
        """
        if node is None:
            node = self.root
            print("\nMerkle Tree Structure:")
        
        # 显示当前节点
        connector = "└── " if is_last else "├── "
        name = os.path.basename(node.path)
        if node.is_function:
            print(f"{indent}{connector}🔧 {name} ({node.function_name})")
        elif node.is_file:
            print(f"{indent}{connector}📄 {name}")
        else:
            print(f"{indent}{connector}📁 {name}")
        
        # 计算下一级缩进
        next_indent = indent + ("    " if is_last else "│   ")
        
        # 显示子节点
        children = list(node.children.items())
        for i, (child_name, child_node) in enumerate(children):
            is_last_child = i == len(children) - 1
            self.visualize(child_node, next_indent, is_last_child)
