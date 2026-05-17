from dhara.btree import BNode, BTree
from dhara.collections.btree import BNode as CollectionsBNode
from dhara.collections.btree import BTree as CollectionsBTree


def test_btree_wrapper_reexports_collections_types():
    assert BTree is CollectionsBTree
    assert BNode is CollectionsBNode
