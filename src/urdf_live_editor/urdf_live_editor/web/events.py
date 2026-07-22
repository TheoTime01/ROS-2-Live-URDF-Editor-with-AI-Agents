# Copyright 2026 theotime01
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Thread-safe publish/subscribe hub for model and validation events.

The web API turns every stage/validate/apply/rollback into a small JSON event
and fans it out to whoever is listening on the WebSocket stream. :class:`EventHub`
is that fan-out: it is plain, transport-agnostic Python (no sockets, no rclpy)
so the event contract can be exercised entirely offline. Each subscriber owns a
bounded queue; a slow consumer only ever loses its own oldest events and can
never block a publisher or another subscriber.
"""

import itertools
import queue
import threading

#: Default per-subscriber backlog. A consumer that falls this far behind starts
#: dropping its oldest events rather than stalling the publisher.
DEFAULT_BACKLOG = 1024


class Subscription:
    """A single subscriber's bounded queue of events."""

    def __init__(self, hub, maxsize):
        """Create a subscription backed by a queue of up to ``maxsize``."""
        self._hub = hub
        self._queue = queue.Queue(maxsize=maxsize)

    def get(self, timeout=None):
        """Block for the next event, raising ``queue.Empty`` on timeout."""
        return self._queue.get(timeout=timeout)

    def get_nowait(self):
        """Return the next event immediately or raise ``queue.Empty``."""
        return self._queue.get_nowait()

    def deliver(self, event):
        """Enqueue ``event``, dropping the oldest first if the queue is full."""
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(event)
            except queue.Full:
                pass

    def close(self):
        """Unsubscribe this subscription from its hub."""
        self._hub.unsubscribe(self)


class EventHub:
    """Fan-out of JSON-serializable events to every current subscriber."""

    def __init__(self, maxsize=DEFAULT_BACKLOG):
        """Start with no subscribers and a per-subscriber backlog cap."""
        self._subscribers = []
        self._lock = threading.Lock()
        self._sequence = itertools.count(1)
        self._maxsize = maxsize

    def subscribe(self):
        """Register and return a new :class:`Subscription`."""
        subscription = Subscription(self, self._maxsize)
        with self._lock:
            self._subscribers.append(subscription)
        return subscription

    def unsubscribe(self, subscription):
        """Remove ``subscription`` if it is still registered."""
        with self._lock:
            if subscription in self._subscribers:
                self._subscribers.remove(subscription)

    def publish(self, event):
        """Stamp ``event`` with a sequence number and deliver it to all."""
        stamped = dict(event)
        if 'seq' not in stamped:
            stamped['seq'] = next(self._sequence)
        with self._lock:
            targets = list(self._subscribers)
        for subscription in targets:
            subscription.deliver(stamped)
        return stamped

    def subscriber_count(self):
        """Return the number of live subscribers."""
        with self._lock:
            return len(self._subscribers)
