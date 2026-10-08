"""Conservative short-term body association for a stationary recognition monitor.

This is *not* BoT-SORT or a navigation controller. IDs describe temporary body
associations, never permanent human identities. Optional appearance recovery
allows a selected body to return after a bounded, verified occlusion.
"""
from __future__ import annotations

import math
import threading

import numpy as np


def _iou(a, b):
    lo = np.maximum(a[:2], b[:2])
    hi = np.minimum(a[2:], b[2:])
    area = float(np.prod(np.maximum(hi - lo, 0)))
    union = float(np.prod(a[2:] - a[:2]) + np.prod(b[2:] - b[:2]) - area)
    return area / max(union, 1e-8)


def _depth(value):
    if value is None:
        return None
    value = float(value)
    return value if math.isfinite(value) and value > 0 else None


class ConservativeTracker:
    """update([{bbox:[x1,y1,x2,y2], depth_m:float|None, ...}], now).

    Returns only currently visible tracks, preserving detection extras and
    adding track_id, first_seen, last_seen, visible=True. Coordinates may be
    pixels or normalized, but all updates must use the same frame/units.
    A briefly missing selected track can be held as invisible for at most .6s;
    strong ambiguity or a competing strong detection clears it immediately.
    Opt-in appearance recovery has a separate fixed eight-second deadline.
    """

    def __init__(self, max_missing_s=0.6, ambiguity_margin=0.18, max_depth_jump_m=0.6,
                 strong_confidence=.45, weak_confidence=.18, max_weak_s=1.2,
                 occlusion_reid=False):
        self.max_missing_s = float(max_missing_s)
        self.ambiguity_margin = float(ambiguity_margin)
        self.max_depth_jump_m = float(max_depth_jump_m)
        self.strong_confidence = float(strong_confidence)
        self.weak_confidence = float(weak_confidence)
        self.max_weak_s = float(max_weak_s)
        self._next_id = 1
        self._tracks = {}
        self._visible_ids = set()
        self._last_time = None
        self.selected_track_id = None
        self.last_events = {}
        self._lock = threading.RLock()
        self.occlusion_reid = bool(occlusion_reid)
        # Session-only appearance vectors never enter public track dictionaries.
        self._appearance_templates = {}
        # Private, session-only body descriptors anchored by a fresh face
        # confirmation. They are not a persistent identity database.
        self._face_anchored_templates = []
        self._face_anchored_track_id = None
        self._occlusion_episode = None

    def select(self, track_id):
        with self._lock:
            track_id = int(track_id)
            if track_id not in self._visible_ids:
                raise ValueError("The selected person is no longer visible")
            if self._tracks[track_id].get("association_ambiguous"):
                raise ValueError("People overlap; wait for an unambiguous target")
            if self._tracks[track_id].get("observation_strength") == "weak":
                raise ValueError("Wait for a clear body detection before selecting")
            if self._occlusion_episode is not None:
                self._cancel_occlusion('manual_selection_changed')
            if self.selected_track_id != track_id:
                self._face_anchored_templates.clear()
                self._face_anchored_track_id = None
            self.selected_track_id = track_id
            return track_id

    def clear_selection(self):
        with self._lock:
            if self._occlusion_episode is not None:
                self._cancel_occlusion('manual_unlock')
            self.selected_track_id = None
            self._face_anchored_templates.clear()
            self._face_anchored_track_id = None
            self.last_events['selected_hold'] = None

    def reset(self):
        with self._lock:
            self._tracks.clear()
            self._visible_ids.clear()
            self.selected_track_id = None
            self._last_time = None
            self.last_events = {}
            self._appearance_templates.clear()
            self._face_anchored_templates.clear()
            self._face_anchored_track_id = None
            self._occlusion_episode = None
            # Deliberately do not reuse IDs after reset.

    def recovery_ready(self, track_id, now):
        """Whether a current track has fresh private appearance templates.

        This is a readiness indicator, not a claim of face identity or a
        guarantee that an occluded person can be recovered unambiguously.
        """
        if not self.occlusion_reid or track_id is None:
            return False
        try:
            track_id, now = int(track_id), float(now)
        except (TypeError, ValueError, OverflowError):
            return False
        if not math.isfinite(now):
            return False
        with self._lock:
            episode = self._occlusion_episode
            active = track_id in self._tracks or (episode and episode['track_id'] == track_id and
                                                  now <= episode['deadline_mono'])
            return bool(active and self._fresh_templates(track_id, now))

    def anchor_face_appearance(self, track_id, embedding, now):
        """Learn the selected body's clothing/shape only on a fresh face match.

        The worker supplies the face evidence; this method refuses a missing,
        weak, or ambiguous body. Descriptors stay in RAM for this session.
        """
        vector = self._embedding(embedding)
        if vector is None:
            return False
        try:
            track_id, now = int(track_id), float(now)
        except (TypeError, ValueError, OverflowError):
            return False
        if not math.isfinite(now):
            return False
        with self._lock:
            row = self._tracks.get(track_id)
            if (self.selected_track_id != track_id or track_id not in self._visible_ids or
                    row is None or row.get('association_ambiguous') or
                    row.get('observation_strength') != 'strong' or
                    not 0 <= now-row['last_seen'] <= .5):
                return False
            if self._face_anchored_track_id != track_id:
                self._face_anchored_templates.clear()
                self._face_anchored_track_id = track_id
            if self._face_anchored_templates and max(
                    float(np.dot(vector, previous)) for previous in self._face_anchored_templates) < .70:
                # A newly verified face with different clothing starts a new
                # session template instead of blending the two appearances.
                self._face_anchored_templates.clear()
            self._face_anchored_templates.append(vector)
            del self._face_anchored_templates[:-8]
            return True

    def face_appearance_status(self):
        with self._lock:
            count = len(self._face_anchored_templates) if (
                self._face_anchored_track_id == self.selected_track_id and
                self.selected_track_id is not None) else 0
            return dict(ready=count >= 2, samples=count)

    @staticmethod
    def _embedding(value):
        try:
            vector = np.asarray(value, dtype=np.float32).reshape(-1)
        except (TypeError, ValueError):
            return None
        if vector.size != 512 or not np.isfinite(vector).all():
            return None
        norm = float(np.linalg.norm(vector))
        if not math.isfinite(norm) or norm <= 1e-8:
            return None
        return (vector / norm).copy()

    def _fresh_templates(self, track_id, now):
        templates = [(stamp, vector) for stamp, vector in self._appearance_templates.get(track_id, [])
                     if 0 <= now-stamp <= 10.]
        if templates:
            self._appearance_templates[track_id] = templates[-4:]
        else:
            self._appearance_templates.pop(track_id, None)
        return [vector for _, vector in templates]

    @staticmethod
    def _input_index(row, detections):
        matches = []
        for index, detection in enumerate(detections):
            try:
                same = (np.array_equal(np.asarray(row['bbox'], dtype=float),
                                       np.asarray(detection['bbox'], dtype=float)) and
                        abs(float(row['confidence'])-float(detection.get('confidence', 1.))) < 1e-7)
            except (TypeError, ValueError, KeyError):
                same = False
            if same:
                matches.append(index)
        return matches[0] if len(matches) == 1 else None

    def _record_appearance(self, before, rows, detections, embeddings, now, previous_time):
        for row in rows:
            track_id = row['track_id']
            prior = before.get(track_id)
            moderate_selected = (track_id == self.selected_track_id and len(rows) == 1 and
                                 row.get('observation_strength') == 'weak' and
                                 row.get('continuity_evidence') == 'stable_moderate_observation' and
                                 row.get('body_continuity_streak', 0) >= 3)
            if (row.get('association_ambiguous') or
                    (row.get('observation_strength') != 'strong' and not moderate_selected) or
                    prior is None or prior.get('association_ambiguous') or
                    (prior.get('observation_strength') != 'strong' and
                     prior.get('continuity_evidence') != 'stable_moderate_observation') or
                    prior['last_seen'] != previous_time or not 0 < now-prior['last_seen'] <= .3):
                continue
            index = self._input_index(row, detections)
            vector = embeddings.get(index)
            if vector is None:
                continue
            self._fresh_templates(track_id, now)
            templates = self._appearance_templates.setdefault(track_id, [])
            # Do not learn an abrupt appearance replacement into the template.
            # A moderate observation may refresh a prior strong template,
            # but cannot create one or weaken the similarity threshold.
            if moderate_selected and not templates:
                continue
            threshold = .88 if moderate_selected else .82
            if templates and max(float(np.dot(vector, previous)) for _, previous in templates) < threshold:
                continue
            templates.append((now, vector.copy()))
            del templates[:-4]
        valid_ids = set(self._tracks)
        if self._occlusion_episode:
            valid_ids.add(self._occlusion_episode['track_id'])
        for track_id in list(self._appearance_templates):
            if track_id not in valid_ids:
                self._appearance_templates.pop(track_id, None)
            else:
                self._fresh_templates(track_id, now)

    @staticmethod
    def _recovery_geometry(previous, candidate):
        try:
            a, b = np.asarray(previous['bbox'], dtype=float), np.asarray(candidate['bbox'], dtype=float)
            if a.shape != (4,) or b.shape != (4,) or not np.isfinite(b).all():
                return False
            aw, ah = a[2:] - a[:2]
            bw, bh = b[2:] - b[:2]
            if min(aw, ah, bw, bh) <= 0 or not .5 <= bw/aw <= 2. or not .35 <= bh/ah <= 2.8:
                return False
            dx, dy = abs((b[:2]+b[2:]-a[:2]-a[2:])/2)
            if dx > 1.5*aw or dy > ah:
                return False
            da, db = _depth(previous.get('depth_m')), _depth(candidate.get('depth_m'))
            return da is None or db is None or abs(da-db) <= .8
        except (TypeError, ValueError, KeyError):
            return False

    @staticmethod
    def _same_recovery_candidate(previous, candidate):
        a, b = np.asarray(previous['bbox']), np.asarray(candidate['bbox'])
        if _iou(a, b) < .5:
            return False
        size = np.maximum((a[2:]-a[:2]+b[2:]-b[:2])/2, 1e-6)
        if np.linalg.norm((a[:2]+a[2:]-b[:2]-b[2:])/2/size) > .3:
            return False
        da, db = _depth(previous.get('depth_m')), _depth(candidate.get('depth_m'))
        return da is None or db is None or abs(da-db) <= .25

    @staticmethod
    def _appearance_candidate_complete(previous, candidate):
        """A cropped torso is too different from a full-body ReID template.

        Keep its geometry reserved during the occlusion wait, but do not let
        one exposed shoulder/torso reject or reclaim the selected identity.
        """
        try:
            old = np.asarray(previous['bbox'], dtype=float)
            new = np.asarray(candidate['bbox'], dtype=float)
            old_size, new_size = old[2:]-old[:2], new[2:]-new[:2]
            return bool(np.isfinite(old_size).all() and np.isfinite(new_size).all() and
                        np.all(old_size > 0) and np.all(new_size > 0) and
                        new_size[0]/old_size[0] >= .65 and
                        new_size[1]/old_size[1] >= .65)
        except (KeyError, TypeError, ValueError):
            return False

    def _cancel_occlusion(self, reason):
        episode = self._occlusion_episode
        if episode is None:
            return None
        track_id = episode['track_id']
        self._tracks.pop(track_id, None)
        self._visible_ids.discard(track_id)
        self._appearance_templates.pop(track_id, None)
        self.selected_track_id = None
        self._occlusion_episode = None
        self.last_events['occlusion_reid_reason'] = reason
        self.last_events['selected_hold'] = None
        return track_id

    def _occlusion_hold(self, now, reason='waiting_for_observation'):
        episode = self._occlusion_episode
        self.selected_track_id = episode['track_id']
        self.last_events['selected_hold'] = dict(
            track_id=episode['track_id'], last_seen=episode['last_seen'],
            missing_age_s=now-episode['last_seen'], deadline_mono=episode['deadline_mono'],
            reason='occlusion_reid_wait')
        self.last_events['selection_cleared'] = False
        self.last_events['occlusion_reid_reason'] = reason

    def _finish_cancelled_update(self, detections, now, embeddings, reason):
        retired = self._cancel_occlusion(reason)
        before, previous_time = dict(self._tracks), self._last_time
        rows = self._update_core(detections, now, appearance_embeddings=embeddings)
        self._record_appearance(before, rows, detections, embeddings, now, previous_time)
        self.last_events['selection_cleared'] = True
        self.last_events['occlusion_reid_reason'] = reason
        if retired is not None:
            self.last_events['retired_ids'] = sorted(set(self.last_events['retired_ids']) | {retired})
        return rows

    def _update_occlusion(self, detections, now, embeddings):
        episode = self._occlusion_episode
        if now > episode['deadline_mono']:
            return self._finish_cancelled_update(detections, now, embeddings, 'occlusion_deadline_expired')
        templates = self._fresh_templates(episode['track_id'], now)
        if not templates:
            return self._finish_cancelled_update(detections, now, embeddings, 'appearance_template_expired')
        candidates = []
        reserved = set()
        for index, detection in enumerate(detections):
            if self._recovery_geometry(episode['track'], detection):
                reserved.add(index)
                if (float(detection.get('confidence', 1.)) >= self.strong_confidence and
                        self._appearance_candidate_complete(episode['track'], detection)):
                    candidates.append((index, detection))
        # An established different track is stronger ownership evidence than
        # a similar outfit. Never steal its plausible current observation.
        for _, candidate in candidates:
            for other in self._tracks.values():
                if (not other.get('association_ambiguous') and now-other['last_seen'] <= self.max_missing_s and
                        math.isfinite(self._cost(other, candidate, now))):
                    return self._finish_cancelled_update(detections, now, embeddings, 'candidate_has_other_track')
        ranked = []
        missing_embedding = False
        for index, candidate in candidates:
            vector = embeddings.get(index)
            if vector is None:
                missing_embedding = True
            else:
                ranked.append((max(float(np.dot(vector, template)) for template in templates), index, candidate))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        if ranked and not missing_embedding:
            if ranked[0][0] < .82:
                return self._finish_cancelled_update(detections, now, embeddings, 'appearance_mismatch')
            if len(ranked) > 1 and ranked[0][0]-ranked[1][0] < .08:
                return self._finish_cancelled_update(detections, now, embeddings, 'recovery_candidates_ambiguous')
        winner = ranked[0] if ranked and not missing_embedding else None
        pending = episode.get('pending')
        verified = bool(winner and pending and pending['seen_at'] == self._last_time and
                        0 < now-pending['seen_at'] <= .3 and
                        self._same_recovery_candidate(pending['candidate'], winner[2]) and
                        float(np.dot(pending['embedding'], embeddings[winner[1]])) >= .82)
        if winner:
            episode['pending'] = dict(candidate=dict(winner[2]), embedding=embeddings[winner[1]].copy(), seen_at=now)
        else:
            episode['pending'] = None
        # Candidate boxes remain private during verification. Other, unrelated
        # people may continue to have their own freshly observed public tracks.
        other_detections = [row for index, row in enumerate(detections) if index not in reserved]
        before, previous_time = dict(self._tracks), self._last_time
        self.selected_track_id = None
        rows = self._update_core(other_detections, now)
        self._record_appearance(before, rows, detections, embeddings, now, previous_time)
        if self.last_events['ambiguous']:
            retired = self._cancel_occlusion('other_tracks_ambiguous')
            self.last_events['selection_cleared'] = True
            self.last_events['retired_ids'] = sorted(set(self.last_events['retired_ids']) | {retired})
            return rows
        if not verified:
            reason = ('embedding_unavailable' if missing_embedding else
                      'confirming_same_candidate' if winner else 'waiting_for_observation')
            self._occlusion_hold(now, reason)
            return rows
        score, index, candidate = winner
        track_id = episode['track_id']
        proof = dict(track_id=track_id, episode_last_seen=episode['last_seen'], verified=True,
                     method='appearance_geometry_unique', recovered_mono=now, candidate_count=1)
        recovered = dict(candidate, bbox=list(map(float, candidate['bbox'])), confidence=float(candidate.get('confidence', 1.)),
                         depth_m=_depth(candidate.get('depth_m')), track_id=track_id,
                         first_seen=episode['track']['first_seen'], last_seen=now, visible=True,
                         association_ambiguous=False, observation_strength='strong', last_strong_seen=now,
                         last_reliable_body_seen=now, body_continuity_streak=1,
                         continuity_evidence='strong_detection', recovery_proof=proof)
        self._tracks[track_id] = recovered
        self._visible_ids.add(track_id)
        self.selected_track_id = track_id
        self._occlusion_episode = None
        self._appearance_templates.setdefault(track_id, []).append((now, embeddings[index].copy()))
        self._appearance_templates[track_id] = self._appearance_templates[track_id][-4:]
        self.last_events.update(selected_hold=None, selection_cleared=False, occlusion_reid_reason='recovered')
        return rows + [dict(recovered)]

    def update(self, detections, now, appearance_embeddings=None):
        """Associate observations; optional 512-D descriptors stay in private RAM.

        Descriptor keys refer to positions in the original ``detections`` list.
        Occlusion re-identification is opt-in and emits no motion authorization.
        """
        if not self.occlusion_reid:
            return self._update_core(detections, now)
        now = float(now)
        if not math.isfinite(now):
            raise ValueError('Timestamp must be finite')
        detections = [dict(detection) for detection in detections]
        # Keep the validation contract even when recovery withholds candidates.
        for detection in detections:
            bbox = np.asarray(detection.get('bbox'), dtype=float).reshape(-1)
            score = float(detection.get('confidence', 1.))
            if bbox.size != 4 or not np.isfinite(bbox).all() or np.any(bbox[2:] <= bbox[:2]):
                raise ValueError('Expected a finite positive-area [x1,y1,x2,y2] box')
            if not math.isfinite(score) or not 0 <= score <= 1:
                raise ValueError('Confidence must be between zero and one')
            detection['bbox'] = bbox.tolist()
            detection['confidence'] = score
            detection['depth_m'] = _depth(detection.get('depth_m'))
        embeddings = {}
        if hasattr(appearance_embeddings, 'items'):
            for index, value in appearance_embeddings.items():
                if type(index) is int and 0 <= index < len(detections):
                    vector = self._embedding(value)
                    if vector is not None:
                        embeddings[index] = vector
        with self._lock:
            if self._last_time is not None and now <= self._last_time:
                self.reset()
            if self._occlusion_episode is not None:
                return self._update_occlusion(detections, now, embeddings)
            before, previous_time = dict(self._tracks), self._last_time
            selected = self.selected_track_id
            old = before.get(selected)
            templates_ready = bool(old and self._fresh_templates(selected, now))
            rows = self._update_core(detections, now, appearance_embeddings=embeddings)
            # A real missed observation may start a fixed episode. A present
            # conflicting/ambiguous candidate cannot be relabelled as absence.
            actual_miss = (old is not None and old['last_seen'] == previous_time and
                           not any(row['track_id'] == selected for row in rows) and
                           not self.last_events['ambiguous'] and
                           not any(float(row.get('confidence', 1.)) >= self.weak_confidence and
                                   self._recovery_geometry(old, row) for row in detections))
            if templates_ready and actual_miss and 0 <= now-old['last_seen'] <= .6:
                self._tracks.pop(selected, None)
                self._visible_ids.discard(selected)
                self._occlusion_episode = dict(track_id=selected, track=dict(old), last_seen=old['last_seen'],
                                                deadline_mono=old['last_seen']+8., pending=None)
                self._occlusion_hold(now)
            self._record_appearance(before, rows, detections, embeddings, now, previous_time)
            return rows

    @staticmethod
    def _reliable_body_seen(old):
        """Last strong detection or independently qualified body continuation.

        This clock is not face evidence and never changes last_strong_seen.
        """
        strong = old.get('last_strong_seen', old['last_seen'])
        return max(strong, old.get('last_reliable_body_seen', strong))

    def _stable_moderate(self, old, new, now, previous_time):
        """Qualify a fresh, adjacent moderate observation, not a prediction.

        The caller also requires exactly one old track and one new detection.
        Unknown depth stays unknown; stricter image agreement permits body
        continuity but cannot make that observation ready for motion or faces.
        """
        if (not .30 <= new['confidence'] < self.strong_confidence or
                old.get('_awaiting_strong') or previous_time is None or
                old['last_seen'] != previous_time or
                not 0 < now-old['last_seen'] <= min(.3, self.max_missing_s)):
            return False
        a, b = np.asarray(old['bbox']), np.asarray(new['bbox'])
        aw, ah = a[2:] - a[:2]
        bw, bh = b[2:] - b[:2]
        if (not .65 <= bw/aw <= 1.55 or not .45 <= bh/ah <= 2.2 or
                _iou(a, b) < .4):
            return False
        top_dx = abs((a[0]+a[2]-b[0]-b[2])/2) / min(aw, bw)
        top_dy = abs(a[1]-b[1]) / min(ah, bh)
        if top_dx > .15 or top_dy > .10:
            return False
        da, db = _depth(old.get('depth_m')), _depth(new.get('depth_m'))
        return da is None or db is None or abs(da-db) <= min(.25, self.max_depth_jump_m)

    def _cost(self, old, new, now, stable_moderate=False):
        a, b = np.asarray(old["bbox"]), np.asarray(new["bbox"])
        center_a, center_b = (a[:2] + a[2:]) / 2, (b[:2] + b[2:]) / 2
        # Normalize each axis separately: a tall body must not permit a huge
        # sideways jump merely because the image box is tall.
        scale = np.maximum(((a[2:] - a[:2]) + (b[2:] - b[:2])) / 2, 1e-6)
        displacement = float(np.linalg.norm((center_a - center_b) / scale))
        overlap = _iou(a, b)
        if displacement > 1.0 or (overlap < 0.08 and displacement > 0.50):
            return math.inf
        weak = new['confidence'] < self.strong_confidence
        if weak and old.get('_awaiting_strong'):
            # Once weak alternatives became uncertain, another weak box is
            # not a new sighting and cannot refresh or resolve that wait.
            return math.inf
        # A weak or recently missed body needs tighter geometric agreement;
        # weak detections can continue a track, never establish a new one.
        if weak or now-old['last_seen'] > .25:
            if overlap < .25 or displacement > .65:
                return math.inf
        sustained_moderate = stable_moderate and old.get('body_continuity_streak', 0) >= 2
        if (weak and not sustained_moderate and
                now-self._reliable_body_seen(old) > self.max_weak_s):
            return math.inf
        old_d, new_d = _depth(old.get("depth_m")), _depth(new.get("depth_m"))
        depth_cost = 0.0
        if old_d is not None and new_d is not None:
            jump = abs(old_d - new_d)
            if jump > self.max_depth_jump_m:
                return math.inf
            if weak and jump > .35:
                return math.inf
            depth_cost = jump / self.max_depth_jump_m
        return 1 - overlap + 0.3 * displacement + 0.3 * depth_cost

    def _update_core(self, detections, now, appearance_embeddings=None):
        now = float(now)
        if not math.isfinite(now):
            raise ValueError("Timestamp must be finite")
        incoming = []
        incoming_indices = []
        for source_index, detection in enumerate(detections):
            item = dict(detection)
            bbox = np.asarray(item.get("bbox"), dtype=float).reshape(-1)
            if bbox.size != 4 or not np.isfinite(bbox).all() or np.any(bbox[2:] <= bbox[:2]):
                raise ValueError("Expected a finite positive-area [x1,y1,x2,y2] box")
            item["bbox"] = bbox.tolist()
            item["depth_m"] = _depth(item.get("depth_m"))
            item['confidence'] = float(item.get('confidence', 1.))
            if not math.isfinite(item['confidence']) or not 0 <= item['confidence'] <= 1:
                raise ValueError('Confidence must be between zero and one')
            if item['confidence'] < self.weak_confidence:
                continue
            incoming.append(item)
            incoming_indices.append(source_index)
        with self._lock:
            previous_selection = self.selected_track_id
            previous_time = self._last_time
            retired = []
            if self._last_time is not None and now <= self._last_time:
                retired.extend(self._tracks)
                self.reset()
            self._last_time = now
            for track_id, track in list(self._tracks.items()):
                expired_wait = (track.get('_awaiting_strong') and
                                now-track['last_seen'] > min(.6, self.max_missing_s))
                if (now - track["last_seen"] > self.max_missing_s or
                        track.get('association_ambiguous') or expired_wait):
                    retired.append(track_id)
                    del self._tracks[track_id]
            old_ids = sorted(self._tracks)
            costs = np.full((len(old_ids), len(incoming)), np.inf)
            moderate_pairs = set()
            for i, track_id in enumerate(old_ids):
                for j, item in enumerate(incoming):
                    stable = (len(old_ids) == 1 and len(incoming) == 1 and
                              self._stable_moderate(self._tracks[track_id], item, now, previous_time))
                    if stable:
                        moderate_pairs.add((i, j))
                    costs[i, j] = self._cost(self._tracks[track_id], item, now, stable_moderate=stable)

            # A face-confirmed session may use its current clothing descriptor
            # to resolve a unique candidate among multiple people. Appearance
            # never creates a new identity, revives an expired track, or
            # overrides an established different body's plausible ownership.
            selected = self.selected_track_id
            if (selected in old_ids and self._face_anchored_track_id == selected and
                    len(self._face_anchored_templates) >= 2 and len(incoming) >= 2 and
                    hasattr(appearance_embeddings, 'get')):
                i = old_ids.index(selected)
                ranked = []
                for j, item in enumerate(incoming):
                    if item['confidence'] < self.strong_confidence or not math.isfinite(costs[i, j]):
                        continue
                    vector = self._embedding(appearance_embeddings.get(incoming_indices[j]))
                    if vector is not None:
                        similarity = max(float(np.dot(vector, template))
                                         for template in self._face_anchored_templates)
                        ranked.append((similarity, j))
                ranked.sort(reverse=True)
                if (len(ranked) >= 2 and ranked[0][0] >= .82 and
                        ranked[0][0]-ranked[1][0] >= .08):
                    winner = ranked[0][1]
                    other_claim = any(k != i and math.isfinite(costs[k, winner]) and
                                      costs[k, winner] <= costs[i, winner] + .2
                                      for k in range(len(old_ids)))
                    if not other_claim:
                        for j in range(len(incoming)):
                            if j != winner:
                                costs[i, j] = math.inf
                        costs[i, winner] = min(costs[i, winner], -.25)

            def same_plane(j, k):
                dj, dk = incoming[j]["depth_m"], incoming[k]["depth_m"]
                return dj is None or dk is None or abs(dj - dk) < .35

            def association_stage(old_indices, new_indices, enforce_overlap=True):
                """Ambiguity and assignment must share the exact same pool.

                Merely sorting strong detections first after a global ambiguity
                pass would still let an unaccepted weak duplicate retire a good
                strong match.  Each stage can affect only its own old indices.
                """
                bad_old, bad_new = set(), set()
                for i in old_indices:
                    ranked = sorted((costs[i, j], j) for j in new_indices
                                    if math.isfinite(costs[i, j]))
                    if len(ranked) > 1 and ranked[1][0] - ranked[0][0] <= self.ambiguity_margin:
                        bad_old.add(i)
                        bad_new.update(j for c, j in ranked if c - ranked[0][0] <= self.ambiguity_margin)
                for j in new_indices:
                    ranked = sorted((costs[i, j], i) for i in old_indices
                                    if math.isfinite(costs[i, j]))
                    if len(ranked) > 1 and ranked[1][0] - ranked[0][0] <= self.ambiguity_margin:
                        bad_new.add(j)
                        bad_old.update(i for c, i in ranked if c - ranked[0][0] <= self.ambiguity_margin)
                # Genuine strong/strong overlap remains ambiguous, including
                # the first frame before either body has a historical track.
                for offset, j in enumerate(new_indices):
                    for k in new_indices[:offset]:
                        if (enforce_overlap and same_plane(j, k) and
                                _iou(np.asarray(incoming[j]['bbox']), np.asarray(incoming[k]['bbox'])) > .35):
                            bad_old.update(i for i in old_indices
                                           if math.isfinite(costs[i, j]) or math.isfinite(costs[i, k]))
                            bad_new.update((j, k))
                matched, used = {}, set()
                candidates = sorted((costs[i, j], i, j) for i in old_indices for j in new_indices
                                    if math.isfinite(costs[i, j]) and i not in bad_old and j not in bad_new)
                for cost, i, j in candidates:
                    if i not in used and j not in matched:
                        matched[j] = old_ids[i]
                        used.add(i)
                return matched, used, bad_old, bad_new

            strong_indices = [j for j, item in enumerate(incoming)
                              if item['confidence'] >= self.strong_confidence]
            assignments, used_old, ambiguous_old, ambiguous_new = association_stage(
                list(range(len(old_ids))), strong_indices)
            remaining_old = [i for i in range(len(old_ids)) if i not in used_old and i not in ambiguous_old]
            accepted_strong = [j for j in strong_indices if j not in ambiguous_new]

            def overlaps_accepted_strong(j):
                a = np.asarray(incoming[j]['bbox'])
                for k in accepted_strong:
                    if not same_plane(j, k):
                        continue
                    b = np.asarray(incoming[k]['bbox'])
                    intersection = float(np.prod(np.maximum(0, np.minimum(a[2:], b[2:]) -
                                                                    np.maximum(a[:2], b[:2]))))
                    smaller = min(float(np.prod(a[2:] - a[:2])), float(np.prod(b[2:] - b[:2])))
                    if _iou(a, b) > .35 or intersection / max(smaller, 1e-8) >= .9:
                        return True
                return False

            weak_indices = [j for j, item in enumerate(incoming)
                            if item['confidence'] < self.strong_confidence
                            and not overlaps_accepted_strong(j)
                            and any(math.isfinite(costs[i, j]) for i in remaining_old)]
            # A low-score duplicate alone is not evidence of a second person.
            # For a sole remaining old body, cost runner-up ambiguity still
            # rejects competing continuations; overlap alone is insufficient.
            # When multiple old bodies compete, preserve the overlap veto.
            weak_matches, weak_used, weak_bad_old, weak_bad_new = association_stage(
                remaining_old, weak_indices, enforce_overlap=len(remaining_old) > 1)
            # A sole, explicitly selected historical body can wait through a
            # weak runner-up tie without choosing either candidate.  This is
            # not general occlusion recovery: a second old body, any strong
            # detection, or an unselected track keeps the cancellation rules.
            if (len(old_ids) == 1 and self.selected_track_id == old_ids[0] and
                    not strong_indices and weak_bad_old == {0}):
                self._tracks[old_ids[0]]['_awaiting_strong'] = True
                weak_bad_old.clear()
            # Strong matches are frozen: weak candidates may continue only an
            # unmatched old track and may never retire or steal a strong one.
            assignments.update(weak_matches)
            used_old.update(weak_used)
            ambiguous_old.update(weak_bad_old)
            ambiguous_new.update(weak_bad_new)
            for i in ambiguous_old:
                track_id = old_ids[i]
                retired.append(track_id)
                self._tracks.pop(track_id, None)
            visible = []
            old_indices = {track_id: i for i, track_id in enumerate(old_ids)}
            for j, item in enumerate(incoming):
                track_id = assignments.get(j)
                weak = item['confidence'] < self.strong_confidence
                if track_id is None:
                    if weak:
                        continue
                    track_id = self._next_id
                    self._next_id += 1
                    first_seen = now
                    last_strong = now
                    continuity_streak = 1
                    reliable_body_seen = now
                    continuity_evidence = 'strong_detection'
                else:
                    old = self._tracks[track_id]
                    first_seen = old["first_seen"]
                    last_strong = old.get('last_strong_seen', now) if weak else now
                    stable = (old_indices[track_id], j) in moderate_pairs
                    continuity_streak = min(255, old.get('body_continuity_streak', 0)+1) if stable else (0 if weak else 1)
                    qualified = weak and stable and continuity_streak >= 3
                    reliable_body_seen = now if not weak or qualified else self._reliable_body_seen(old)
                    continuity_evidence = ('strong_detection' if not weak else
                                           'stable_moderate_observation' if qualified else 'bounded_weak_observation')
                track = dict(item, track_id=track_id, first_seen=first_seen, last_seen=now,
                             visible=True, association_ambiguous=j in ambiguous_new,
                             observation_strength='weak' if weak else 'strong', last_strong_seen=last_strong,
                             last_reliable_body_seen=reliable_body_seen,
                             body_continuity_streak=continuity_streak, continuity_evidence=continuity_evidence)
                self._tracks[track_id] = track
                visible.append(dict(track))
            self._visible_ids = {t["track_id"] for t in visible}
            selected_hold = None
            hold_diagnostic_reason = None
            if self.selected_track_id not in self._visible_ids:
                old = self._tracks.get(self.selected_track_id)
                near_rejected_weak = False
                if old:
                    a = np.asarray(old['bbox'])
                    for j, item in enumerate(incoming):
                        if item['confidence'] >= self.strong_confidence or j in weak_indices:
                            continue
                        b = np.asarray(item['bbox'])
                        scale = np.maximum(((a[2:] - a[:2]) + (b[2:] - b[:2])) / 2, 1e-6)
                        displacement = float(np.linalg.norm(((a[:2] + a[2:]) - (b[:2] + b[2:])) / 2 / scale))
                        if _iou(a, b) > .05 or displacement <= 1.:
                            # A weak box near the missing person that fails
                            # geometry/depth/age gates is uncertain evidence,
                            # never a reason to silently hold their identity.
                            near_rejected_weak = True
                            break
                # No fabricated boxes/depth are returned during this wait.
                # Remote unmatched weak junk is ignored; any strong candidate,
                # viable weak candidate or nearby rejected weak ends the hold.
                waiting_for_strong = (old and old.get('_awaiting_strong') and
                                      len(old_ids) == 1 and not strong_indices)
                ordinary_miss = (not strong_indices and not weak_indices and not near_rejected_weak
                                 and not (ambiguous_old or ambiguous_new))
                if (old and (waiting_for_strong or ordinary_miss)
                        and 0 <= now-old['last_seen'] <= min(.6, self.max_missing_s)
                        and now-self._reliable_body_seen(old) <= self.max_weak_s):
                    selected_hold = dict(track_id=self.selected_track_id,
                                         last_seen=old['last_seen'], missing_age_s=now-old['last_seen'],
                                         reason='temporary_detection_miss')
                    if waiting_for_strong:
                        hold_diagnostic_reason = 'weak_runner_up_waiting_for_strong'
                else:
                    self.selected_track_id = None
            self.last_events = dict(retired_ids=sorted(set(retired)), ambiguous=bool(ambiguous_old or ambiguous_new),
                                    selection_cleared=previous_selection is not None and self.selected_track_id is None,
                                    selected_hold=selected_hold, hold_diagnostic_reason=hold_diagnostic_reason)
            return visible
