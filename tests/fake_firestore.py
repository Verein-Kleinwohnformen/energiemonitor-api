"""Kleiner Firestore-Ersatz im Speicher, gerade genug für den AggregationService."""
import copy


class Snap:
    def __init__(self, path, data):
        self.reference_path = path
        self.id = path.rsplit('/', 1)[-1]
        self._data = data

    @property
    def exists(self):
        return self._data is not None

    def to_dict(self):
        return copy.deepcopy(self._data) if self._data is not None else None


class DocRef:
    def __init__(self, db, path):
        self.db, self.path = db, path
        self.id = path.rsplit('/', 1)[-1]

    def get(self):
        self.db.reads += 1
        return Snap(self.path, self.db.store.get(self.path))

    def set(self, data):
        self.db.writes += 1
        self.db.store[self.path] = copy.deepcopy(data)

    def update(self, data):
        if self.path not in self.db.store:
            raise KeyError(self.path)
        self.db.writes += 1
        self.db.store[self.path].update(copy.deepcopy(data))

    def collection(self, name):
        return ColRef(self.db, f'{self.path}/{name}')


class ColRef:
    def __init__(self, db, path, filters=()):
        self.db, self.path, self.filters = db, path, filters

    def _children(self):
        prefix = self.path + '/'
        ids = set()
        for p in self.db.store:
            if p.startswith(prefix):
                ids.add(p[len(prefix):].split('/', 1)[0])
        return sorted(ids)

    def list_documents(self):
        return [DocRef(self.db, f'{self.path}/{i}') for i in self._children()]

    def where(self, field, op, value):
        assert op == '=='
        return ColRef(self.db, self.path, self.filters + ((field, value),))

    def stream(self):
        for i in self._children():
            path = f'{self.path}/{i}'
            data = self.db.store.get(path)
            if data is None:
                continue
            if all(data.get(f) == v for f, v in self.filters):
                self.db.reads += 1
                yield Snap(path, data)

    def document(self, i):
        return DocRef(self.db, f'{self.path}/{i}')


class FakeFirestore:
    def __init__(self):
        self.store = {}
        self.reads = 0
        self.writes = 0

    def collection(self, path):
        return ColRef(self, path)

    def document(self, path):
        return DocRef(self, path)

    def get_all(self, refs):
        for r in refs:
            yield r.get()
