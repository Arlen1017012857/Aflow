import os
import json
import hashlib
from typing import Dict, List, Optional, Set
from dataclasses import dataclass

@dataclass
class MerkleNode:
    """Merkle树节点，用于表示文件或目录
    
    Attributes:
        hash: 节点的哈希值（对于目录，是所有子节点哈希的组合；对于文件，等同于content_hash）
        path: 节点的路径
        children: 子节点字典，key为名称，value为MerkleNode
        is_file: 是否为文件
        content_hash: 文件内容的哈希值（仅对文件有效）
    """
    hash: str
    path: str
    children: Dict[str, 'MerkleNode']
    is_file: bool
    content_hash: Optional[str] = None

class MerkleTree:
    def __init__(self, root_dir: str):
        """初始化Merkle Tree
        
        Args:
            root_dir: 根目录路径
        """
        self.root_dir = root_dir
        self.root = self._build_tree(root_dir)
        self.previous_root = None
    
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
        
        if is_file:
            content_hash = self._calculate_file_hash(path)
            hash_value = content_hash
            print(f"File hash for {path}: {hash_value}")
        else:
            # Process directory
            print(f"Processing directory: {path}")
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
            print(f"Directory hash for {path}: {hash_value}")
        
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
            else:
                for child in node1.children.values():
                    self._compare_nodes(child, None, added, modified, removed)
            return
            
        if not node1:  # 删除
            if node2.is_file:
                removed.add(node2.path)
            else:
                for child in node2.children.values():
                    self._compare_nodes(None, child, added, modified, removed)
            return
        
        if node1.is_file and node2.is_file:
            if node1.hash != node2.hash:
                modified.add(node1.path)
            return
        
        # 比较目录内容
        all_children = set(node1.children.keys()) | set(node2.children.keys())
        for child_name in all_children:
            child1 = node1.children.get(child_name)
            child2 = node2.children.get(child_name)
            self._compare_nodes(child1, child2, added, modified, removed)

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

    def update(self) -> Dict[str, Set[str]]:
        """更新树并返回变化的文件
        
        Returns:
            Dict[str, Set[str]]: 文件变化信息
        """
        print("Updating Merkle tree...")
        # Store previous root
        old_root = self.previous_root
        
        # Rebuild tree
        print(f"Building new tree from {self.root_dir}")
        self.root = self._build_tree(self.root_dir)
        
        # Get changes
        added = set()
        modified = set()
        removed = set()
        
        print("Comparing old and new trees...")
        if old_root is None:
            # First run, treat all Python files as added
            print("First run, treating all Python files as added")
            for node in self._get_all_files(self.root):
                if node.path.endswith('.py'):
                    added.add(node.path)
        else:
            self._compare_nodes(self.root, old_root, added, modified, removed)
        
        # Update previous root after comparison
        self.previous_root = self.root
        
        changes = {
            'added': added,
            'modified': modified,
            'removed': removed
        }
        print(f"Found changes: {changes}")
        return changes
    
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
                'content_hash': node.content_hash
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
                content_hash=data['content_hash']
            )
        
        self.root_dir = state['root_dir']
        self.root = dict_to_node(state['root']) if state['root'] else None
        self.previous_root = dict_to_node(state['previous_root']) if state['previous_root'] else None
