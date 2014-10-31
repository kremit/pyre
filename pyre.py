import zmq
import time
import struct
import socket
import uuid
import logging
import sys

# local modules
from . import zbeacon
from . import zhelper
from .zactor import ZActor
from .zsocket import ZSocket
from .pyre_node import PyreNode

BEACON_VERSION = 1
ZRE_DISCOVERY_PORT = 5670
REAP_INTERVAL = 1.0  # Once per second

logger = logging.getLogger(__name__)


class Pyre(object):

    def __init__(self, ctx=zmq.Context()):
        self._ctx = ctx
        self.uuid = None
        self.name = None
        self.verbose = False
        self._inbox = ZSocket(ctx, zmq.PAIR)
        self._inbox.bind("inproc://pyre-%s" %hash(self._inbox))
        #self._inbox = zhelper.zthread_fork(self._ctx, PyreNode)

        self._outbox = ZSocket(self._ctx, zmq.PAIR)

        # Start node engine and wait for it to be ready
        self.actor = ZActor(self._ctx, PyreNode, self._outbox)
        self._outbox.connect("inproc://pyre-%s" %hash(self._inbox))
        # Send name, if any, to node ending  
        if (self.name):
            self.actor.send_unicode("SET NAME", zmq.SNDMORE)
            self.actor.send_unicode(self.name)

    # Return our node UUID, after successful initialization
    def get_uuid(self):
        if not self.uuid:
            self.actor.send_unicode("UUID")
            self.uuid = uuid.UUID(bytes=self.actor.recv())
        return self.uuid

    # Return our node name, after successful initialization
    def get_name(self):
        if not self.name:
            self.actor.send_unicode("NAME")
            self.name = self.actor.recv().decode('utf-8')
        return self.name

    def set_name(self, name):
        self.actor.send_unicode("SET NAME", zmq.SNDMORE)
        self.actor.send_unicode(name)

    # Set node header value
    def set_header(self, key, value):
        self.actor.send_unicode("SET HEADER", flags=zmq.SNDMORE)
        self.actor.send_unicode(key, flags=zmq.SNDMORE)
        self.actor.send_unicode(value)

    def set_verbose(self):
        self.actor.send_unicode("SET VERBOSE")

    def set_port(self, port):
        self.actor.send_unicode("SET PORT", zmq.SNDMORE)
        self.actor.send(port)

    def set_interval(self, interval):
        self.actor.send_unicode("SET INTERVAL", zmq.SNDMORE)
        self.actor.send_unicode(interval)

    def set_interface(iface):
        logging.debug("set_interface not implemented")

    def set_endpoint(endpoint):
        self.send_unicode("SET ENDPOINT", zmq.SNDMORE)
        self.send_unicode(endpoint)

    # TODO: We haven't implemented gossiping yet
    def start(self):
        self.actor.send_unicode("START")
        # TODO wait signal

    def stop(self):
        self.actor.send_unicode("STOP", flags=zmq.DONTWAIT)

    # Receive next message from node
    def recv(self):
        return self.actor.recv()

    # Join a group
    def join(self, group):
        self.actor.send_unicode("JOIN", flags=zmq.SNDMORE)
        self.actor.send_unicode(group)

    # Leave a group
    def leave(self, group):
        self.actor.send_unicode("LEAVE", flags=zmq.SNDMORE)
        self.actor.send_unicode(group)

    # Send message to single peer; peer ID is first frame in message
    def whisper(self, peer, msg):
        self.actor.send_unicode("WHISPER", flags=zmq.SNDMORE)
        self.actor.send(peer.bytes, flags=zmq.SNDMORE)
        if isinstance(msg, list):
            self.actor.send_multipart(msg)
        else:
            self.actor.send(msg)

    # Send message to a group of peers
    def shout(self, group, msg):
        self.actor.send_unicode("SHOUT", flags=zmq.SNDMORE)
        self.actor.send_unicode(group, flags=zmq.SNDMORE)
        if isinstance(msg, list):
            self.actor.send_multipart(msg)
        else:
            self.actor.send(msg)

    # Send message to single peer; peer ID is first frame in message
    def whispers(self, peer, msg):
        self.actor.send_unicode("WHISPER", flags=zmq.SNDMORE)
        self.actor.send(peer.bytes, flags=zmq.SNDMORE)
        self.actor.send_unicode(msg)

    def shouts(self, group, msg):
        self.actor.send_unicode("SHOUT", flags=zmq.SNDMORE)
        self.actor.send_unicode(group, flags=zmq.SNDMORE)
        self.actor.send_unicode(msg)

    #  --------------------------------------------------------------------------
    #  Return list of current peers. The caller owns this list and should
    #  destroy it when finished with it.
    def get_peers(self):
        self.send("PEERS")
        peers = self.recv()
        return peers

    #  --------------------------------------------------------------------------
    #  Return the value of a header of a conected peer. 
    #  Returns null if peer or key doesn't exits.
    def get_peer_address(peer):
        self.send("PEER ENDPOINT", zmq.SNDMORE)
        self.send(peer)
        adr = self.recv()
        return peers

    #  --------------------------------------------------------------------------
    #  Return zlist of currently joined groups.
    def get_own_groups():
        self.send("OWN GROUPS");
        groups = self.recv()

    #  --------------------------------------------------------------------------
    #  Return zlist of groups known through connected peers. 
    def get_peer_groups():
        self.send("PEER GROUPS")
        groups = self.recv()
        return groups

    # Return node socket, for direct polling of socket
    def get_socket(self):
        return self.actor.resolve()

    # Set node header value
    def set_header(self, name, value, *args):
        self.actor.send_unicode("SET", flags=zmq.SNDMORE)
        self.actor.send_unicode(name, flags=zmq.SNDMORE)
        self.actor.send_unicode(value, flags=zmq.SNDMORE)

# TODO: make a unittest or selftest

def chat_task(ctx, pipe):
    n = Pyre(ctx)
    n.join("CHAT")

    poller = zmq.Poller()
    poller.register(pipe, zmq.POLLIN)
    poller.register(n.get_socket(), zmq.POLLIN)
    while(True):
        items = dict(poller.poll())
        if pipe in items and items[pipe] == zmq.POLLIN:
            message = pipe.recv()
            logger.debug("CHAT_TASK: {0}".format(message))
            n.shout("CHAT", message)

        if n.get_socket() in items and items[n.get_socket()] == zmq.POLLIN:
            cmds = n.get_socket().recv_multipart()

            type = cmds.pop(0)

            logger.debug("NODE_MSG TYPE: {0}".format(type))
            logger.debug("NODE_MSG PEER: {0}".format(uuid.UUID(bytes=cmds.pop(0))))

            if type.decode('utf-8') == "SHOUT":
                logger.debug("NODE_MSG GROUP: {0}".format(cmds.pop(0)))

            logger.debug("NODE_MSG CONT: {0}".format(cmds))


if __name__ == '__main__':
    ctx = zmq.Context()
    chat_pipe = zhelper.zthread_fork(ctx, chat_task)
    while True:
        try:
            msg = input()
            chat_pipe.send(msg.encode('utf_8'))
        except (KeyboardInterrupt, SystemExit):
            break

    logger.debug("Exiting")
