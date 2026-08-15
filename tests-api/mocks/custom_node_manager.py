"""
Mock CustomNodeManager for testing purposes
"""

class CustomNodeManager:
    """
    Mock implementation of the CustomNodeManager class
    """
    instance = None
    
    def __init__(self):
        self.custom_nodes = {}
        self.node_paths = []
        self.refresh_timeout = None
        
    def get_node_path(self, node_class):
        """
        Mock implementation to get the path for a node class
        """
        return self.custom_nodes.get(node_class, None)
        
    def update_node_paths(self):
        """
        Mock implementation to update node paths
        """
        pass