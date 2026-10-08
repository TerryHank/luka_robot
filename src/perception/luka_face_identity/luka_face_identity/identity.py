"""Offline, explicitly enrolled SFace identity matching; no camera or motion code.

The caller is responsible for rejecting small/blurred/occluded faces and ensuring
that a supplied face belongs to the selected person's body box. Identity is a
candidate until repeated observations agree. Embeddings never leave this store.
"""
from __future__ import annotations

import math
import sqlite3
import threading
import time
import unicodedata
import uuid
from pathlib import Path

import numpy as np


VOICE_DB_PATH = Path("/home/sunrise/luka_data/recordings/voiceprints/profiles.sqlite3")


def normalized_embedding(value, dimension=128):
    array = np.asarray(value, dtype=np.float32).reshape(-1)
    if array.size != dimension or not np.all(np.isfinite(array)):
        raise ValueError("Invalid face embedding dimension or non-finite values")
    norm = float(np.linalg.norm(array))
    if norm <= 1e-8:
        raise ValueError("Face embedding must not be zero")
    return array / norm


def _name(value):
    if not isinstance(value, str):
        raise ValueError("Name must be text")
    name = value.strip()
    if not name or len(name) > 40 or any(unicodedata.category(c).startswith("C") for c in name):
        raise ValueError("Name must contain 1–40 characters without control characters")
    return name


def _now(value):
    value = time.monotonic() if value is None else float(value)
    if not math.isfinite(value):
        raise ValueError("Timestamp must be finite")
    return value


class IdentityStore:
    """Thread-safe SQLite profiles with bounded normalized face samples.

    match() returns a *single-frame candidate*, not a confirmed identity. Its
    score is cosine similarity, not a probability. Thresholds need field testing.
    """

    def __init__(self, path, dimension=128, threshold=0.50, margin=0.08, max_samples=60,
                 voice_db_path=VOICE_DB_PATH):
        self.dimension = int(dimension)
        self.threshold = float(threshold)
        self.margin = float(margin)
        self.max_samples = int(max_samples)
        # Configuration is local only; never accept this path from an HTTP body.
        self.voice_db_path = Path(voice_db_path)
        if self.dimension < 1 or self.max_samples < 3 or not (0 < threshold <= 1) or margin < 0:
            raise ValueError("Invalid identity store settings")
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS profiles (
                id TEXT PRIMARY KEY, name TEXT NOT NULL,
                name_key TEXT NOT NULL UNIQUE, created_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS samples (
                profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                ordinal INTEGER NOT NULL, dimension INTEGER NOT NULL, embedding BLOB NOT NULL,
                PRIMARY KEY(profile_id, ordinal));
            CREATE TABLE IF NOT EXISTS face_voice_links (
                face_profile_id TEXT PRIMARY KEY REFERENCES profiles(id) ON DELETE CASCADE,
                voice_profile_id TEXT NOT NULL UNIQUE, linked_at REAL NOT NULL);
        """)
        self._db.commit()

    def close(self):
        with self._lock:
            self._db.close()

    def list_profiles(self):
        with self._lock:
            rows = self._db.execute("""SELECT p.id,p.name,p.created_at,COUNT(s.ordinal),
                    l.voice_profile_id,l.linked_at
                FROM profiles p LEFT JOIN samples s ON s.profile_id=p.id
                LEFT JOIN face_voice_links l ON l.face_profile_id=p.id
                GROUP BY p.id ORDER BY p.created_at,p.id""").fetchall()
            voices = self._voice_profiles() if any(r[4] is not None for r in rows) else None
            profiles = []
            for row in rows:
                profile = dict(id=row[0], name=row[1], created_at=row[2], sample_count=row[3])
                if row[4] is not None:
                    profile["voice_link"] = self._voice_link(row[4], row[5], voices)
                    if profile["voice_link"]["state"] == "linked":
                        profile["person_id"] = row[4]
                profiles.append(profile)
            return profiles

    def _voice_profiles(self):
        """Read only ready IDs/names; unavailable is distinct from a missing ID.

        Never create the voice database, load vectors, or alter speaker memory.
        A bounded busy timeout keeps monitoring responsive if enrollment is busy.
        """
        try:
            uri = self.voice_db_path.resolve().as_uri() + "?mode=ro"
            db = sqlite3.connect(uri, uri=True, timeout=0.05)
            try:
                return dict(db.execute("SELECT id,name FROM profiles WHERE ready=1"))
            finally:
                db.close()
        except (sqlite3.Error, OSError, ValueError):
            return None

    @staticmethod
    def _voice_link(voice_id, linked_at, voices):
        link = dict(state="unavailable" if voices is None else "missing", linked_at=linked_at)
        if voices is not None and voice_id in voices:
            link.update(state="linked", profile_id=voice_id, name=voices[voice_id])
        return link

    def bind_voice_profile(self, face_id, voice_id):
        """Explicitly link exact IDs, once; matching display names imply nothing.

        Existing different links are never replaced. Unlink explicitly before
        rebinding, including when an old voice was deleted and recorded again.
        The result is metadata, not evidence about who spoke a current utterance.
        """
        if any(not isinstance(value, str) or not value or len(value) > 128
               for value in (face_id, voice_id)):
            raise ValueError("Face and voice profile IDs must be nonempty text")
        with self._lock, self._db:
            self._db.execute("BEGIN IMMEDIATE")
            if self._db.execute("SELECT 1 FROM profiles WHERE id=?", (face_id,)).fetchone() is None:
                raise ValueError("Face profile does not exist")
            voices = self._voice_profiles()
            if voices is None:
                raise ValueError("Voice profile database is unavailable")
            if voice_id not in voices:
                raise ValueError("Voice profile is missing or not fully enrolled")
            previous = self._db.execute(
                "SELECT voice_profile_id,linked_at FROM face_voice_links WHERE face_profile_id=?",
                (face_id,)).fetchone()
            if previous is not None:
                if previous[0] != voice_id:
                    raise ValueError("Face profile already has a different voice link; unlink it first")
                return self._voice_link(voice_id, previous[1], voices)
            linked_at = time.time()
            try:
                self._db.execute("INSERT INTO face_voice_links VALUES(?,?,?)",
                                 (face_id, voice_id, linked_at))
            except sqlite3.IntegrityError as exc:
                raise ValueError("Voice profile is already linked to another face") from exc
            return self._voice_link(voice_id, linked_at, voices)

    def unlink_voice_profile(self, face_id):
        """Remove only the association; retain both enrollments and all memories."""
        with self._lock, self._db:
            return self._db.execute("DELETE FROM face_voice_links WHERE face_profile_id=?",
                                    (str(face_id),)).rowcount > 0

    def has_name(self, name):
        key = _name(name).casefold()
        with self._lock:
            return self._db.execute("SELECT 1 FROM profiles WHERE name_key=?", (key,)).fetchone() is not None

    def add_profile(self, name, embeddings):
        """Atomically save an explicit enrollment; duplicate names never overwrite."""
        name = _name(name)
        vectors = [normalized_embedding(v, self.dimension) for v in embeddings]
        if not 3 <= len(vectors) <= self.max_samples:
            raise ValueError("Enrollment requires 3–%d face samples" % self.max_samples)
        for index, vector in enumerate(vectors):
            if any(float(np.dot(vector, other)) >= 0.9999 for other in vectors[:index]):
                raise ValueError("Enrollment contains duplicate face samples")
        profile_id, created = uuid.uuid4().hex, time.time()
        with self._lock:
            try:
                with self._db:
                    self._db.execute("INSERT INTO profiles VALUES(?,?,?,?)", (profile_id, name, name.casefold(), created))
                    self._db.executemany("INSERT INTO samples VALUES(?,?,?,?)", [
                        (profile_id, i, self.dimension, v.astype("<f4").tobytes()) for i, v in enumerate(vectors)])
            except sqlite3.IntegrityError as exc:
                raise ValueError("A profile with this name already exists") from exc
        return dict(id=profile_id, name=name, created_at=created, sample_count=len(vectors))

    def append_samples(self, profile_id, embeddings):
        """Add consented pose samples without replacing the profile or voice link."""
        vectors = [normalized_embedding(v, self.dimension) for v in embeddings]
        if len(vectors) < 3:
            raise ValueError("At least three additional face samples are required")
        with self._lock, self._db:
            self._db.execute("BEGIN IMMEDIATE")
            row = self._db.execute("SELECT name,created_at FROM profiles WHERE id=?",
                                   (str(profile_id),)).fetchone()
            if row is None:
                raise ValueError("Face profile does not exist")
            existing = self._db.execute("SELECT ordinal,dimension,embedding FROM samples WHERE profile_id=? ORDER BY ordinal",
                                        (str(profile_id),)).fetchall()
            if len(existing) + len(vectors) > self.max_samples:
                raise ValueError("Face profile sample limit reached")
            saved = [np.frombuffer(data, dtype="<f4") for _, dimension, data in existing
                     if dimension == self.dimension and len(data) == self.dimension * 4]
            for index, vector in enumerate(vectors):
                if any(float(np.dot(vector, other)) >= 0.9999 for other in saved + vectors[:index]):
                    raise ValueError("Additional enrollment contains duplicate face samples")
            ordinal = max((item[0] for item in existing), default=-1) + 1
            self._db.executemany("INSERT INTO samples VALUES(?,?,?,?)", [
                (str(profile_id), ordinal + i, self.dimension, vector.astype("<f4").tobytes())
                for i, vector in enumerate(vectors)])
            return dict(id=str(profile_id), name=row[0], created_at=row[1],
                        sample_count=len(existing) + len(vectors))

    def delete_profile(self, profile_id):
        with self._lock, self._db:
            return self._db.execute("DELETE FROM profiles WHERE id=?", (str(profile_id),)).rowcount > 0

    def match(self, embedding, threshold=None):
        vector = normalized_embedding(embedding, self.dimension)
        threshold = self.threshold if threshold is None else float(threshold)
        if not 0 < threshold <= 1:
            raise ValueError("Invalid identity matching threshold")
        with self._lock:
            rows = self._db.execute("""SELECT p.id,p.name,s.dimension,s.embedding FROM profiles p
                JOIN samples s ON s.profile_id=p.id ORDER BY p.id,s.ordinal""").fetchall()
        scores = {}
        names = {}
        for profile_id, name, dimension, data in rows:
            if dimension != self.dimension or len(data) != dimension * 4:
                continue
            stored = np.frombuffer(data, dtype="<f4")
            score = float(np.dot(stored, vector))
            if not math.isfinite(score):
                continue
            scores.setdefault(profile_id, []).append(score)
            names[profile_id] = name
        # Two samples must agree: one unusually similar saved frame cannot win.
        ranked = sorted(((float(np.mean(sorted(values, reverse=True)[:2])), profile_id)
                         for profile_id, values in scores.items() if len(values) >= 2), reverse=True)
        if not ranked:
            return dict(known=False, profile_id=None, name=None, similarity=None, margin=None, reason="no_profiles")
        best, profile_id = ranked[0]
        gap = best - ranked[1][0] if len(ranked) > 1 else None
        accepted = best >= threshold and (gap is None or gap >= self.margin)
        reason = "candidate" if accepted else ("low_similarity" if best < threshold else "ambiguous_identity")
        return dict(known=accepted, profile_id=profile_id if accepted else None,
                    name=names[profile_id] if accepted else None, similarity=best, margin=gap, reason=reason)


class EnrollmentManager:
    """One explicit, cancellable enrollment bound to a single visible track.

    start(name, track_id); add_sample(...); finish(). Samples only reach SQLite
    on finish(), after >= required (3). Eight diverse frames are the target.
    Call on_tracks(visible_ids) each frame, so losing the target cancels enrollment.
    """

    def __init__(self, store, required=3, target=12, timeout_s=90.0, min_interval_s=0.25):
        self.store = store
        self.required = int(required)
        self.target = min(int(target), store.max_samples)
        if not 3 <= self.required <= self.target:
            raise ValueError("Invalid enrollment sample count")
        self.timeout_s = float(timeout_s)
        self.min_interval_s = float(min_interval_s)
        self._lock = threading.RLock()
        self._session = None
        self._last = dict(state="idle", active=False, samples=0, required=self.required, target=self.target)

    def status(self):
        with self._lock:
            if self._session is None:
                return dict(self._last)
            s = self._session
            return dict(state="ready" if len(s["vectors"]) >= self.required else "collecting", active=True,
                        name=s["name"], profile_id=s['profile_id'],
                        mode='supplement' if s['profile_id'] is not None else 'new',
                        track_id=s["track_id"], samples=len(s["vectors"]),
                        required=self.required, target=self.target, reason=s.get("reason", "collecting"))

    def start(self, name, track_id, now=None, profile_id=None):
        name = _name(name)
        if track_id is None:
            raise ValueError("Select one visible person before enrollment")
        if profile_id is None and self.store.has_name(name):
            raise ValueError("This name is already enrolled; remove the old profile to replace it")
        if profile_id is not None:
            profile = next((p for p in self.store.list_profiles() if p['id'] == str(profile_id)), None)
            if profile is None or profile['name'] != name:
                raise ValueError("Selected face profile does not exist")
            if profile['sample_count'] + self.target > self.store.max_samples:
                raise ValueError("Face profile has no room for another pose enrollment")
        with self._lock:
            if self._session is not None:
                raise ValueError("An enrollment is already in progress")
            self._session = dict(name=name, profile_id=str(profile_id) if profile_id is not None else None,
                                 track_id=int(track_id), started=_now(now),
                                 last_sample=None, vectors=[], reason="collecting")
            return self.status()

    def cancel(self, reason="cancelled"):
        with self._lock:
            self._last = self.status()
            self._last.update(state="cancelled", active=False, reason=str(reason))
            self._session = None
            return self.status()

    def on_tracks(self, visible_ids, now=None):
        now = _now(now)
        with self._lock:
            if self._session is not None:
                if self._session["track_id"] not in set(visible_ids):
                    return self.cancel("target_lost")
                if now - self._session["started"] > self.timeout_s:
                    return self.cancel("timeout")
            return self.status()

    def add_sample(self, track_id, embedding, quality_ok=True, now=None):
        now = _now(now)
        with self._lock:
            s = self._session
            if s is None:
                return self.status()
            if int(track_id) != s["track_id"]:
                return self.cancel("track_changed")
            if now < s["started"] or now - s["started"] > self.timeout_s:
                return self.cancel("timeout")
            if not quality_ok:
                s["reason"] = "low_quality"
                return self.status()
            if len(s["vectors"]) >= self.target:
                s["reason"] = "target_reached"
                return self.status()
            if s["last_sample"] is not None and now - s["last_sample"] < self.min_interval_s:
                s["reason"] = "sample_too_soon"
                return self.status()
            vector = normalized_embedding(embedding, self.store.dimension)
            similarities = [float(np.dot(vector, old)) for old in s["vectors"]]
            if similarities and max(similarities) >= 0.9999:
                s["reason"] = "duplicate_sample"
                return self.status()
            # A different face must not contaminate an enrollment even if a
            # body-track association upstream was wrong.
            if similarities:
                # Supplementary poses may legitimately be far from the first
                # frontal embedding. Require a gradual transition against
                # recent frames while the selected body track remains intact.
                floor = 0.30 if s['profile_id'] is not None else self.store.threshold
                reference = max(similarities[-3:]) if s['profile_id'] is not None else min(similarities)
                if reference < floor:
                    if s['profile_id'] is not None:
                        s['reason'] = 'angle_jump'
                        return self.status()
                    return self.cancel("face_changed")
            s["vectors"].append(vector)
            s["last_sample"] = now
            s["reason"] = "target_reached" if len(s["vectors"]) >= self.target else "sample_added"
            return self.status()

    def finish(self, now=None):
        now = _now(now)
        with self._lock:
            if self._session is None:
                raise ValueError("No active enrollment")
            if now < self._session["started"] or now - self._session["started"] > self.timeout_s:
                self.cancel("timeout")
                raise ValueError("Enrollment has expired; start a new enrollment")
            if len(self._session["vectors"]) < self.required:
                raise ValueError("At least %d diverse face samples are required" % self.required)
            profile = (self.store.append_samples(self._session['profile_id'], self._session['vectors'])
                       if self._session['profile_id'] is not None else
                       self.store.add_profile(self._session["name"], self._session["vectors"]))
            self._last = self.status()
            self._last.update(state="complete", active=False, reason="saved", profile=profile)
            self._session = None
            return self.status()


class IdentityRecognizer:
    """Per-track multi-frame confirmation; unknown or conflicting faces revoke it.

    A body track ID must never be reused. Call prune() with visible IDs each
    frame. Skipping observe() when no face is visible does not assert a new ID.
    """

    def __init__(self, store, confirmations=3, max_gap_s=1.5):
        self.store = store
        self.confirmations = max(2, int(confirmations))
        self.max_gap_s = float(max_gap_s)
        self._states = {}
        self._lock = threading.RLock()

    def forget(self, track_id):
        with self._lock:
            self._states.pop(int(track_id), None)

    def prune(self, active_ids):
        keep = set(active_ids)
        with self._lock:
            for track_id in list(self._states):
                if track_id not in keep:
                    del self._states[track_id]

    def observe(self, track_id, embedding, now=None, confirmations=None, min_similarity=None):
        now = _now(now)
        track_id = int(track_id)
        required = self.confirmations if confirmations is None else int(confirmations)
        if required < self.confirmations:
            raise ValueError("Identity confirmations cannot be relaxed")
        result = self.store.match(embedding, threshold=min_similarity)
        with self._lock:
            previous = self._states.get(track_id)
            if not result["known"]:
                self._states.pop(track_id, None)
                return dict(result, confirmations=0, required=self.confirmations)
            same = (previous and previous["profile_id"] == result["profile_id"]
                    and previous.get("required", self.confirmations) == required
                    and 0 < now - previous["time"] <= self.max_gap_s)
            count = min(required, previous["count"] + 1) if same else 1
            self._states[track_id] = dict(profile_id=result["profile_id"], count=count, time=now,
                                          required=required)
            confirmed = count >= required
            return dict(result, known=confirmed, name=result["name"] if confirmed else None,
                        profile_id=result["profile_id"] if confirmed else None,
                        reason="confirmed" if confirmed else "confirming", confirmations=count, required=required)
