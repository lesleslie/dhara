"""
$URL$
$Id$
"""


from random import choice

from druva.storage.file import TempFileStorage
from druva.storage_server import StorageServer
from druva.utils import as_bytes, read


class Test:
    def test_check_storage_server(self):
        storage = TempFileStorage()
        host = "127.0.0.1"
        port = 2972
        server = StorageServer(storage, host=host, port=port)
        file = "test.durus_server"
        server = StorageServer(storage, address=file)

    def test_check_receive(self):
        class Dribble:
            def recv(x, n):
                return as_bytes(choice(["a", "bb"])[:n])

        fake_socket = Dribble()
        read(fake_socket, 30)
