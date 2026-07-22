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

"""Unit tests for the publish/subscribe :class:`EventHub`."""

import queue

from urdf_live_editor.web.events import EventHub


def test_publish_fans_out_to_every_subscriber():
    """Each subscriber receives every event published after it subscribed."""
    hub = EventHub()
    first = hub.subscribe()
    second = hub.subscribe()
    hub.publish({'type': 'x'})
    assert first.get(timeout=1.0)['type'] == 'x'
    assert second.get(timeout=1.0)['type'] == 'x'


def test_events_carry_monotonic_sequence_numbers():
    """The hub stamps each event with an increasing 'seq'."""
    hub = EventHub()
    sub = hub.subscribe()
    hub.publish({'type': 'a'})
    hub.publish({'type': 'b'})
    assert sub.get(timeout=1.0)['seq'] == 1
    assert sub.get(timeout=1.0)['seq'] == 2


def test_unsubscribe_stops_delivery():
    """A closed subscription no longer receives events."""
    hub = EventHub()
    sub = hub.subscribe()
    sub.close()
    assert hub.subscriber_count() == 0
    hub.publish({'type': 'x'})
    try:
        sub.get_nowait()
        assert False, 'closed subscription should have no events'
    except queue.Empty:
        pass


def test_slow_subscriber_drops_oldest_not_newest():
    """A full queue drops its oldest event so the newest still arrives."""
    hub = EventHub(maxsize=2)
    sub = hub.subscribe()
    hub.publish({'type': 'a'})
    hub.publish({'type': 'b'})
    hub.publish({'type': 'c'})
    remaining = [sub.get_nowait()['type'], sub.get_nowait()['type']]
    assert remaining == ['b', 'c']
    try:
        sub.get_nowait()
        assert False, 'queue should hold only maxsize events'
    except queue.Empty:
        pass
