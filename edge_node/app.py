"""
Nghiệp vụ Raft nằm trong application/consensus.py.
Điểm khởi động nằm trong bootstrap.py.
"""

from .application.consensus import RaftNode
from .bootstrap import main

__all__ = [
    "RaftNode",
    "main"
]


if __name__ == "__main__":
    main()