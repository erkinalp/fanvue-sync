import yaml
import os
from collections import defaultdict

class AddressBook:
    def __init__(self, filepath='addressbook.yaml'):
        self.filepath = filepath
        self.lookup = {}
        self.reverse_lookup = defaultdict(set)
        self.load()

    def load(self):
        if os.path.exists(self.filepath):
            with open(self.filepath, 'r') as f:
                data = yaml.safe_load(f) or {}
                # Data format: uuid: [mxid1, mxid2]
                for uuid, mxids in data.items():
                    if isinstance(mxids, str):
                        mxids = [mxids]
                    self.lookup[uuid] = set(mxids)
                    for mxid in mxids:
                        self.reverse_lookup[mxid].add(uuid)

    def save(self):
        data = {uuid: list(mxids) for uuid, mxids in self.lookup.items()}
        with open(self.filepath, 'w') as f:
            yaml.dump(data, f)

    def get_mxids(self, uuid):
        return self.lookup.get(uuid, set())

    def add(self, uuid, mxid):
        if uuid not in self.lookup:
            self.lookup[uuid] = set()
        self.lookup[uuid].add(mxid)
        self.reverse_lookup[mxid].add(uuid)
        self.save()

    def remove(self, uuid, mxid):
        if uuid in self.lookup:
            self.lookup[uuid].discard(mxid)
            if not self.lookup[uuid]:
                del self.lookup[uuid]
            self.save()
